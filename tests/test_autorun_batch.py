"""Auto Run batch verification tests.

Phase 2 (folder scan service â€” api/gdrive_import.py):
F1  extract_drive_folder_id: accepted folder-link shapes + strict rejections
F2  scan_drive_folder via fake httpx client (embedded file-explorer listing)
F3  download_drive_file_by_id: happy path + invalid ID + status mapping
F4  single-file import regressions (folder links still rejected, refactor 1:1)

Phase 3 (batch engine â€” api/autorun_batch.py):
F5  AR_ naming + collisions (resolved Q3)
F6  resolve_step6_config mapping + first_not_done_step (resolved Q6)
F7  manifest write/read round-trip
F8  engine: queue, per-PDF sequential steps, failure isolation
F9  retry guards (resolved Q9)
F10 startup auto-resume (resolved Q12)

Phase 1 (history-progress-cache plan):
F11 durable per-step `steps` map in the manifest (done/error/skipped/not-reached)
F12 merge_live_status: job_manager overlays manifest steps; response-only
F15 write_manifest failure → write_errors counter recorded + re-persisted

Batch history (Phase 3 of the history-progress-cache plan):
F13 list_user_batches: summaries, newest-first, counts, interrupted state, limit
F14 resume_batch guards (404 unknown / terminal ↔ nothing-to-resume / live) + relaunch

Step-results caching (Phase 5):
F16 step_cache: TTL band (122–300), /status + /output + first_not_done from cache,
    put-merge + step/project/user invalidation map
"""
import asyncio
import json
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "api"))

from gdrive_import import (GoogleDriveImportError, extract_drive_file_id,  # noqa: E402
                           extract_drive_folder_id, scan_drive_folder,
                           download_drive_pdf, download_drive_file_by_id,
                           _build_folder_view_url)
import autorun_batch as ab  # noqa: E402

PDF_BYTES = b"%PDF-1.4\n%" + b"A" * (1024 * 256)
FOLDER_ID = "Fldr1234567890abcdefghijklmnop"
FILE_LINK_ID = "abcdef1234567890123456789012345"
UID = "tester@example.com"


# ---------------------------------------------------------------------------
# Fake httpx plumbing (same standalone pattern as the gdrive import tests)
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status=200, headers=None, content=b"", chunks=None,
                 next_url=None, text=""):
        self.status_code = status
        self.headers = headers or {}
        self.content = content
        self._chunks = chunks
        if next_url:
            self.headers = dict(self.headers)
            self.headers["location"] = next_url
        self.text = text

    def iter_bytes(self, chunk_size=1024 * 1024):
        if self._chunks is not None:
            for c in self._chunks:
                yield c
        else:
            yield self.content


class _RespCtx:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self._resp

    def __exit__(self, *a):
        return False


class _FakeClient:
    def __init__(self, script):
        self._script = script
        self.urls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, method, url, headers=None):
        self.urls.append(url)
        if not self._script:
            raise AssertionError("unexpected extra request: " + url)
        action = self._script.pop(0)
        result = action(self, url)
        if isinstance(result, Exception):
            raise result
        return _RespCtx(result)


def _fake_dns_public():
    return patch("gdrive_import.socket.getaddrinfo",
                 return_value=[(None, None, None, "", ("142.250.72.46", 443))])


def _expect_error(fn, code, msg_fragment=None):
    try:
        fn()
    except GoogleDriveImportError as e:
        assert e.code == code, f"expected {code}, got {e.code}: {e.message}"
        if msg_fragment is not None:
            assert msg_fragment in e.message, (msg_fragment, e.message)
        return e
    raise AssertionError(f"expected GoogleDriveImportError({code})")


def _html_anchor(fid: str, name: str) -> str:
    return ('<a href="https://drive.google.com/file/d/' + fid + '/view" target="_blank">'
            '<div class="flip-entry"><div class="flip-entry-title">' + name + '</div>'
            '</div></a>')


def _folder_html(entries_html: str, title="My PDFs - Google Drive") -> str:
    return ("<html><head><title>" + title + "</title></head><body>"
            '<div class="flip-entries">' + entries_html + "</div></body></html>")


def _scan(folder_link: str, script, max_files=None):
    if isinstance(script, str):
        script = [lambda c, u, _t=script: _FakeResp(headers={"content-type": "text/html"}, text=_t)]
    elif not isinstance(script, list):
        script = [script]
    def factory():
        return _FakeClient(script)
    with _fake_dns_public():
        return scan_drive_folder(folder_link, max_files=max_files, client_factory=factory)


# ---------------------------------------------------------------------------
# Phase 2 tests
# ---------------------------------------------------------------------------

def _test_f1_folder_parsing():
    print("\n--- F1: folder link parsing (strict) ---")
    accepted = [
        f"https://drive.google.com/drive/folders/{FOLDER_ID}",
        f"https://drive.google.com/drive/folders/{FOLDER_ID}?usp=sharing",
        f"https://drive.google.com/drive/folders/{FOLDER_ID}/",
        f"  https://drive.google.com/drive/folders/{FOLDER_ID}  ",
    ]
    for link in accepted:
        assert extract_drive_folder_id(link) == FOLDER_ID, link

    rejects = [
        (f"https://drive.google.com/file/d/{FILE_LINK_ID}/view", "single-file"),
        (f"https://docs.google.com/document/d/{FILE_LINK_ID}/edit", "single-file"),
        ("https://evil.com/drive/folders/" + FOLDER_ID, "FOLDER link"),
        ("https://drive.google.com/drive/folders/short_id", "FOLDER link"),
        ("not a link at all", "FOLDER link"),
        ("", "FOLDER link"),
    ]
    for link, frag in rejects:
        try:
            extract_drive_folder_id(link)
            raise AssertionError(f"should reject: {link}")
        except GoogleDriveImportError as e:
            assert frag in e.message, (link, e.message)
    print("OK F1 â€” folder parsing strict, near-miss hints friendly.")


def _test_f2_scan():
    print("\n--- F2: scan_drive_folder (fake explorer listing) ---")
    folder_link = f"https://drive.google.com/drive/folders/{FOLDER_ID}"
    pdfs = [
        ("aaaaaaaaaaaaaaaaaaaaPDFFILE1", "Exam_2024.pdf"),
        ("bbbbbbbbbbbbbbbbbbbbPDFFILE2", "Anatomie session.pdf"),
        ("ccccccccccccccccccccPDFFILE3", "Biochimie.PDF"),
    ]
    subfolder = ('<a href="https://drive.google.com/drive/folders/' + ("f" * 25) + '">'
                 '<div class="flip-entry"><div class="flip-entry-title">Subfolder</div>'
                 '</div></a>')
    docs = ('<a href="https://docs.google.com/document/d/' + ("d" * 25) + '/edit">'
            '<div class="flip-entry"><div class="flip-entry-title">Notes.doc</div>'
            '</div></a>')
    html = _folder_html("".join(_html_anchor(fid, n) for fid, n in pdfs) + subfolder + docs)

    result = _scan(folder_link, html)
    assert result["folder_name"] == "My PDFs", result
    assert result["total_in_folder"] == 3, result
    assert result["non_pdf_skipped"] == 0, result
    got = [(f["name"], f["file_id"]) for f in result["files"]]
    assert got == [(n, fid) for fid, n in pdfs], got

    from gdrive_import import _build_folder_view_url
    assert _build_folder_view_url(FOLDER_ID) == \
        f"https://drive.google.com/embeddedfolderview?id={FOLDER_ID}"

    capped = _scan(folder_link, html, max_files=2)
    assert len(capped["files"]) == 2 and capped["total_in_folder"] == 3, capped

    mixed = _folder_html("".join(_html_anchor(fid, n) for fid, n in pdfs)
                         + _html_anchor("zzzzzzzzzzzzzzzzzzDOC1", "Notes.doc"))
    mixed_res = _scan(folder_link, mixed)
    assert len(mixed_res["files"]) == 3, mixed_res
    assert mixed_res["total_in_folder"] == 4 and mixed_res["non_pdf_skipped"] == 1, mixed_res

    ent = _folder_html(_html_anchor(pdfs[0][0], "Exam &lt;2024&gt;.pdf"))
    got_ent = _scan(folder_link, ent)
    assert got_ent["files"][0]["name"] == "Exam <2024>.pdf", got_ent

    empty = _scan(folder_link, _folder_html("", title="Empty folder"))
    assert empty["files"] == [] and empty["total_in_folder"] == 0, empty

    _expect_error(lambda: _scan(folder_link, [lambda c, u: _FakeResp(status=403)]),
                  "NOT_PUBLIC", "Anyone with the link")
    _expect_error(lambda: _scan(folder_link, [lambda c, u: _FakeResp(status=404)]),
                  "NOT_FOUND")
    _expect_error(lambda: _scan(folder_link, [lambda c, u: _FakeResp(status=500)]),
                  "DRIVE_ERROR")
    _expect_error(lambda: _scan(folder_link, [
        lambda c, u: _FakeResp(status=302, next_url="http://accounts.google.com/ServiceLogin"),
    ]), "NOT_PUBLIC")
    _expect_error(lambda: _scan(folder_link, [
        lambda c, u: _FakeResp(status=302, next_url="https://evil.com/listing"),
    ]), "BLOCKED_HOST")
    _expect_error(lambda: _scan(folder_link, [
        lambda c, u: _FakeResp(headers={"content-type": "text/html"}, text="<html>?</html>"),
    ]), "PARSE_ERROR")
    _expect_error(lambda: _scan(folder_link, [
        lambda c, u: _FakeResp(headers={"content-type": "text/html"},
                               text="<html>Sign in â€” accounts.google.com</html>"),
    ]), "NOT_PUBLIC")
    _expect_error(lambda: _scan(folder_link, [
        lambda c, u: _FakeResp(headers={"content-type": "text/html"}, text=""),
    ]), "NOT_PUBLIC")
    print("OK F2 â€” filter, cap, entities, empty folder, full error map.")


def _test_f3_download_by_id():
    print("\n--- F3: download_drive_file_by_id ---")
    fid = "aaaaaaaaaaaaaaaaaaaaPDFFILE1"
    holder = []

    def factory():
        c = _FakeClient([
            lambda c, u: _FakeResp(content=PDF_BYTES,
                                   headers={"content-disposition": 'attachment; filename="exam.pdf"'}),
        ])
        holder.append(c)
        return c

    with _fake_dns_public():
        data, name = download_drive_file_by_id(fid, client_factory=factory)
    assert data == PDF_BYTES and name == "exam.pdf", (len(data), name)
    assert holder[-1].urls == [f"https://drive.google.com/uc?export=download&id={fid}"], \
        holder[-1].urls

    for bad in ["", "short", "../../etc/passwd", None]:
        _expect_error(lambda: download_drive_file_by_id(bad, client_factory=factory),
                      "INVALID_LINK")
        assert len(holder) == 1, "no request must leave for a bad ID"

    _expect_error(lambda: download_drive_file_by_id(
        fid, client_factory=lambda: _FakeClient([lambda c, u: _FakeResp(status=404)])),
        "NOT_FOUND")

    with _fake_dns_public():
        data2, name2 = download_drive_pdf(
            f"https://drive.google.com/file/d/{fid}/view",
            client_factory=lambda: _FakeClient([
                lambda c, u: _FakeResp(content=PDF_BYTES,
                                       headers={"content-disposition": 'attachment; filename="exam.pdf"'}),
            ]))
    assert data2 == PDF_BYTES and name2 == "exam.pdf"
    print("OK F3 â€” by-id download verified through the shared streaming path.")


def _test_f4_single_file_regressions():
    print("\n--- F4: single-file import regressions ---")
    try:
        extract_drive_file_id(f"https://drive.google.com/drive/folders/{FOLDER_ID}")
        raise AssertionError("folder link must stay rejected for single-file import")
    except GoogleDriveImportError as e:
        assert "folder link" in e.message, e.message
    assert extract_drive_file_id(
        f"https://drive.google.com/file/d/{FILE_LINK_ID}/view") == FILE_LINK_ID
    print("OK F4 â€” single-file import behavior untouched.")


# ---------------------------------------------------------------------------
# Phase 3 tests
# ---------------------------------------------------------------------------

def _import_real_api():
    """Import real_api with stubbed heavy deps (same pattern as persistence PR tests)."""
    for mod_name in ["google_auth_oauthlib", "google.oauth2", "google.auth",
                     "googleapiclient", "yaml"]:
        if mod_name not in sys.modules:
            try:
                __import__(mod_name)
            except Exception:
                sys.modules[mod_name] = types.ModuleType(mod_name)
    os.environ.setdefault("SUPABASE_URL", "http://localhost")
    os.environ.setdefault("SUPABASE_KEY", "test-service-key")
    import real_api
    return real_api


def _tmp_engine(tmp=None):
    """Fresh engine root; returns (tmp_path, uid)."""
    tmp = tmp or tempfile.mkdtemp()
    return Path(tmp), UID


UID = "tester@example.com"


def _make_manifest(tmp: Path, projects: list, batch_id="batch-test-001", config=None):
    m = {"batch_id": batch_id,
         "created_at": "2026-09-19T00:00:00+00:00",
         "source": "drive",
         "state": "pending",
         "config_snapshot": config or {},
         "projects": projects}
    with patch.object(ab, "OUTPUT_ROOT", tmp):
        ab.write_manifest(UID, m)
    return m


def _test_f5_naming():
    print("\n--- F5: AR_ naming + collisions ---")
    files = [{"file_id": "f1", "name": "exam.pdf"},
             {"file_id": "f2", "name": "exam.pdf"},                 # duplicate filename
             {"file_id": "f3", "name": "My Exam (2024).pdf"},
             {"file_id": "f4", "name": "   "}
    ]
    mapping = ab.assign_ar_names(files, existing_names=set())
    assert mapping["f1"] == "AR_exam", mapping
    assert mapping["f2"] == "AR_exam_2", mapping                     # in-batch duplicate
    assert mapping["f3"] == "AR_My_Exam_2024", mapping
    assert mapping["f4"] == "AR_pdf", mapping

    mapping2 = ab.assign_ar_names([{"file_id": "g1", "name": "exam.pdf"},
                                   {"file_id": "g2", "name": "exam.pdf"}],
                                  existing_names={"AR_exam"})
    assert mapping2["g1"] == "AR_exam_2" and mapping2["g2"] == "AR_exam_3", mapping2

    # Batch cap helper
    with patch.dict(os.environ, {"MAX_AUTORUN_BATCH_FILES": "10"}):
        assert ab.max_batch_files() == 10
    with patch.dict(os.environ, {"AUTORUN_BATCH_CONCURRENCY": "5"}):
        assert ab.batch_concurrency() == 5
    with patch.dict(os.environ, {"AUTORUN_BATCH_CONCURRENCY": "2"}):
        assert ab.batch_concurrency() == 2
    print("OK F5 â€” AR_ prefix, numeric suffix on remaining collisions, env knobs.")


def _test_f6_config_resolution():
    print("\n--- F6: Step 6 mapping + step injection + first_not_done_step ---")
    tmp, uid = _make_tmp()
    with patch.object(ab, "OUTPUT_ROOT", tmp), patch.object(ab, "_page_count", lambda p: 9):
        last = ab.resolve_step6_config(
            {"correction_source": "last_page", "text_model": "m/text",
             "text_fallback": "", "include_neighbors": True}, uid, "AR_pdf")
        assert last["pages"] == "9", last                        # per-PDF last page (Q6)
        assert last["source"] == "page_text"
        assert last["correction_search_mode"] == "specific_pages"
        assert last["force_overwrite"] is False, last            # always off (Q6 part two)
        assert last["text_model"] == "m/text" and "text_fallback" not in last
        assert str(last["pdf_path"]).replace("\\", "/").endswith(
            "tester@example.com/AR_pdf/source.pdf"), last

        first = ab.resolve_step6_config({"correction_source": "first_page"}, uid, "AR_pdf")
        assert first["pages"] == "1" and first["source"] == "page_text", first

        auto = ab.resolve_step6_config(
            {"correction_source": "auto_search", "all_pages_model": "m/scan"}, uid, "AR_pdf")
        assert auto["source"] == "auto_detect" and auto["correction_search_mode"] == "all_pages", auto
        assert auto["force_overwrite"] is False

    tmp2, _ = _make_tmp()
    with patch.object(ab, "OUTPUT_ROOT", tmp2):
        s1 = ab.resolve_step_config("1", {"step1": {"method": "vision_ocr",
                                                    "ocr_guidance": "g", "model": "m/v"}}, uid, "AR_p")
        assert str(s1["pdf_path"]).replace("\\", "/").endswith("AR_p/source.pdf") \
            and s1["force_overwrite"] is False, s1
        s2 = ab.resolve_step_config("2", {"step2": {"model_primary": "a", "step3": {"config": {}}}},
                                    uid, "AR_p")
        assert s2["page_range"] == "1-1-1" and s2["step3"] == {"config": {}}, s2
        s15 = ab.resolve_step_config("1.5", {"step1.5": {"x": 1}}, uid, "AR_p")
        assert s15 == {"x": 1}, s15

    problems = ab.validate_batch_config({"step1": {"method": "ocr_bad"},
                                         "step6": {"correction_source": "nope"}})
    assert len(problems) == 2, problems
    assert ab.validate_batch_config({"step1": {"method": "vision_ocr"},
                                     "step6": {"correction_source": "first_page"}}) == []

    # first_not_done_step — SQL-authoritative; local FS fallback; none when all done
    # (Phase 5: the step cache is wiped between mutations — in production the
    # run-start/run-finally hooks invalidate the same way.)
    real_api = _import_real_api()
    import step_cache as sc
    tmp3, _ = _make_tmp()
    rows = {"1": None, "1.5": None, "1.6": None, "2": None, "6": None}
    def fake_row(uid2, project, step_id, _rows=rows):
        r = _rows[step_id]
        return r if r else None
    with patch.object(ab, "OUTPUT_ROOT", tmp3), \
         patch.object(real_api, "_latest_step_result_row", side_effect=fake_row):
        sc.clear()
        assert ab.first_not_done_step(uid, "p") == "1", "no progress → step 1"
        rows["1"] = {"badge": "success"}
        sc.clear()
        assert ab.first_not_done_step(uid, "p") == "1.5", rows
        rows["1.5"] = rows["1.6"] = rows["2"] = {"badge": "success"}
        sc.clear()
        assert ab.first_not_done_step(uid, "p") == "6", rows
        rows["6"] = {"badge": "success"}
        sc.clear()
        assert ab.first_not_done_step(uid, "p") is None, "all done → None"
    print("OK F6 — mapping, force_off, models passthrough, entry-point resolution.")


def _make_tmp():
    return Path(tempfile.mkdtemp()), UID


def _test_f7_manifest_roundtrip():
    print("\n--- F7: manifest dual-write + read ---")
    tmp, uid = _make_tmp()
    m = _make_manifest(tmp, [{"name": "AR_a", "state": "pending"}])
    with patch.object(ab, "OUTPUT_ROOT", tmp):
        back = ab.read_manifest(uid, "batch-test-001")
        assert back == m, (back, m)
        assert back["projects"][0]["name"] == "AR_a"
        missing = ab.read_manifest(uid, "nope")
        assert missing is None
        # mutate â†’ persisted (local file authoritative)
        ab._set_batch_state(uid, "batch-test-001", "running")
        assert ab.read_manifest(uid, "batch-test-001")["state"] == "running"
    print("OK F7 â€” manifest round-trip verified on local FS (Storage dual-write best-effort).")


class _Runner:
    """Scripted step runner for the engine: records calls, tracks concurrency."""

    def __init__(self, fail_projects=None, fail_step="2"):
        self.calls = []            # list of (project, step)
        self.active = set()
        self.max_active = 0
        self.fail_projects = set(fail_projects or ())
        self.fail_step = fail_step

    async def run(self, project, uid, step_id, cfg):
        self.active.add(project)
        if len(self.active) > self.max_active:
            self.max_active = len(self.active)
        try:
            self.calls.append((project, step_id))
            await asyncio.sleep(0.01)
            if project in self.fail_projects and step_id == self.fail_step:
                ab.job_manager.set_error(project, step_id)
            else:
                ab.job_manager.set_done(project, step_id)
        finally:
            self.active.discard(project)


def _run_batch(tmp, batch_id, start_fn=None):
    """Run a batch (or start_fn, e.g. retry/resume) on a fresh event loop to completion."""
    async def _engine():
        if start_fn is not None:
            start_fn()
        else:
            ok = ab.run_batch_task(UID, batch_id)
            assert ok, "batch must start"
        task = ab._BATCH_TASKS.get(batch_id)
        if task:
            await task
        retry_tasks = [t for t in list(ab._RETRY_TASKS.values())]
        if retry_tasks:
            await asyncio.gather(*retry_tasks)

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_engine())
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _test_f8_engine():
    print("\n--- F8: engine queue / per-PDF sequencing / failure isolation ---")
    tmp = Path(tempfile.mkdtemp())
    _make_manifest(tmp, [
        {"name": "AR_okA", "state": "pending"},
        {"name": "AR_bad", "state": "pending"},
        {"name": "AR_okB", "state": "pending"},
    ], batch_id="batch-e8")
    runner = _Runner(fail_projects={"AR_bad"})
    with patch.object(ab, "OUTPUT_ROOT", tmp), \
         patch.object(ab, "_spawn_runtime_task",
                      new=lambda p, u, s, c: runner.run(p, u, s, c)), \
         patch.dict(os.environ, {"AUTORUN_BATCH_CONCURRENCY": "2"}):
        _run_batch(tmp, "batch-e8")

    order = [(p, s) for (p, s) in runner.calls if p == "AR_okA"]
    assert order == [("AR_okA", s) for s in ab.BATCH_SEQUENCE], order
    bad_steps = [s for (p, s) in runner.calls if p == "AR_bad"]
    assert bad_steps == ["1", "1.5", "1.6", "2"], bad_steps   # stopped at failure
    assert runner.max_active <= 2, runner.max_active          # semaphore respected

    with patch.object(ab, "OUTPUT_ROOT", tmp):
        m = ab.read_manifest(UID, "batch-e8")
    states = {p["name"]: p["state"] for p in m["projects"]}
    assert states["AR_okA"] == "done" and states["AR_okB"] == "done", states
    bad_row = next(p for p in m["projects"] if p["name"] == "AR_bad")
    assert bad_row.get("error_step") == "2", bad_row
    assert m["state"] == "done_with_errors", m
    print("OK F8 â€” sequencing, queue bound and failure isolation verified.")


def _test_f9_retry():
    print("\n--- F9: retry guards (resolved Q9) ---")
    tmp = Path(tempfile.mkdtemp())
    _make_manifest(tmp, [
        {"name": "AR_done", "state": "done"},
        {"name": "AR_err", "state": "error", "error_step": "6"},
    ], batch_id="batch-e9")

    # Batch/project guards (inside the patched engine root)
    with patch.object(ab, "OUTPUT_ROOT", tmp):
        allowed, reason = ab.retry_project(UID, "missing-batch", "AR_err")
        assert not allowed and reason == "batch-not-found", (allowed, reason)
        allowed, reason = ab.retry_project(UID, "batch-e9", "AR_ghost")
        assert not allowed and reason == "project-not-in-batch", (allowed, reason)
        allowed, reason = ab.retry_project(UID, "batch-e9", "AR_done")
        assert not allowed and reason == "already-done", (allowed, reason)

    real_api = _import_real_api()
    runner = _Runner()
    with patch.object(ab, "OUTPUT_ROOT", tmp), \
         patch.object(ab, "_spawn_runtime_task", new=lambda p, u, s, c: runner.run(p, u, s, c)), \
         patch.object(real_api, "_latest_step_result_row", return_value=None, create=True):
        _run_batch(tmp, "batch-e9", start_fn=lambda: ab.retry_project(UID, "batch-e9", "AR_err"))

    err_steps = [s for (p, s) in runner.calls if p == "AR_err"]
    assert err_steps == list(ab.BATCH_SEQUENCE), err_steps            # failed step re-ran, later followed
    with patch.object(ab, "OUTPUT_ROOT", tmp):
        m = ab.read_manifest(UID, "batch-e9")
    err_row = next(p for p in m["projects"] if p["name"] == "AR_err")
    assert err_row["state"] == "done" and "error_step" not in err_row, err_row
    assert m["state"] == "done", m                                     # done+retried-done â†’ clean
    print("OK F9 â€” retry re-enters at the failed step and finishes the PDF.")


def _test_f10_resume():
    print("\n--- F10: startup auto-resume (resolved Q12) ---")
    tmp = Path(tempfile.mkdtemp())
    _make_manifest(tmp, [
        {"name": "AR_none", "state": "done"},
        {"name": "AR_pending", "state": "pending"},
        {"name": "AR_midrun", "state": "running"},        # interrupted mid-run
    ], batch_id="batch-e10")

    real_api = _import_real_api()
    runner = _Runner()
    with patch.object(ab, "OUTPUT_ROOT", tmp), \
         patch.object(ab, "_spawn_runtime_task", new=lambda p, u, s, c: runner.run(p, u, s, c)), \
         patch.object(real_api, "_latest_step_result_row", return_value=None, create=True):
        _run_batch(tmp, "batch-e10", start_fn=ab.resume_interrupted_batches)

    with patch.object(ab, "OUTPUT_ROOT", tmp):
        m = ab.read_manifest(UID, "batch-e10")
    states = {p["name"]: p["state"] for p in m["projects"]}
    assert states == {"AR_none": "done", "AR_pending": "done",
                      "AR_midrun": "done"}, states
    ran = [p for (p, s) in runner.calls if s == "1"]
    assert set(ran) == {"AR_pending", "AR_midrun"}, ran    # done PDF untouched

    # Fully finished batches are NOT re-launched
    with patch.object(ab, "OUTPUT_ROOT", tmp):
        assert ab.resume_interrupted_batches() == 0
    print("OK F10 â€” interrupted batches resume; clean batches stay untouched.")


def _test_f11_step_progress():
    print("\n--- F11: durable per-step progress in the manifest ---")
    real_api = _import_real_api()
    tmp = Path(tempfile.mkdtemp())
    _make_manifest(tmp, [
        {"name": "AR_fresh", "state": "pending"},
        {"name": "AR_skip", "state": "pending"},
        {"name": "AR_bad", "state": "pending"},
    ], batch_id="batch-e11")
    runner = _Runner(fail_projects={"AR_bad"})
    with patch.object(ab, "OUTPUT_ROOT", tmp), \
         patch.object(ab, "_spawn_runtime_task", new=lambda p, u, s, c: runner.run(p, u, s, c)), \
         patch.object(real_api, "_latest_step_result_row", return_value=None, create=True):
        # AR_skip already ran steps 1/1.5/1.6 in an earlier pass — their local
        # outputs (shared step1_extraction folder) force entry at step "2".
        step1_dir = tmp / UID / "AR_skip" / "step1_extraction"
        step1_dir.mkdir(parents=True, exist_ok=True)
        (step1_dir / "page_1.txt").write_text("already extracted")
        _run_batch(tmp, "batch-e11")

    with patch.object(ab, "OUTPUT_ROOT", tmp):
        m = ab.read_manifest(UID, "batch-e11")
    proj = {p["name"]: p for p in m["projects"]}

    fresh = proj["AR_fresh"]["steps"]
    assert [fresh[s]["state"] for s in ab.BATCH_SEQUENCE] == ["done"] * 5, fresh
    assert all("updated_at" in e for e in fresh.values()), fresh

    skip = proj["AR_skip"]["steps"]                       # cache-hit flags (plan Phase-1)
    assert [skip[s]["state"] for s in ("1", "1.5", "1.6")] == ["skipped"] * 3, skip
    assert skip["2"]["state"] == "done" and skip["6"]["state"] == "done", skip

    bad = proj["AR_bad"]
    assert bad["steps"]["1"]["state"] == "done" and bad["steps"]["2"]["state"] == "error", bad
    assert "6" not in bad["steps"], bad                   # never reached
    assert bad["error_step"] == "2" and bad["state"] == "error", bad
    print("OK F11 — done / skipped / error / not-reached recorded with timestamps.")


def _test_f12_merge_live():
    print("\n--- F12: merge_live_status — live over manifest steps ---")
    tmp = Path(tempfile.mkdtemp())
    _make_manifest(tmp, [{
        "name": "AR_m", "state": "running", "current_step": "2",
        "steps": {"1": {"state": "done", "updated_at": "t0"},
                  "2": {"state": "running", "updated_at": "t0"}},
    }], batch_id="batch-e12")
    with patch.object(ab, "OUTPUT_ROOT", tmp):
        m = ab.read_manifest(UID, "batch-e12")

    # Empty job_manager (fresh process) → recorded manifest steps stand
    merged = ab.merge_live_status(m, status_lookup=lambda name, sid: "idle")
    steps = merged["projects"][0]["steps"]
    assert steps["1"]["state"] == "done" and steps["2"]["state"] == "running", steps

    # Live process knows better → fresh statuses overlay ("6" stays idle — but
    # present, uniform shape for the chip rendering)
    statuses = {"1": "done", "1.5": "done", "1.6": "done", "2": "running", "6": "idle"}
    merged2 = ab.merge_live_status(m, status_lookup=lambda name, sid: statuses[sid])
    steps2 = merged2["projects"][0]["steps"]
    assert steps2["1.5"]["state"] == "done" and "updated_at" in steps2["1.5"], steps2
    assert steps2["6"]["state"] == "idle", steps2
    assert steps2["1"]["updated_at"] == "t0", steps2["1"]    # same state → timestamp kept
    assert merged2["projects"][0]["state"] == "running"      # project fields untouched

    # Response-only: disk manifest sees no merge side-effects
    with patch.object(ab, "OUTPUT_ROOT", tmp):
        disk = ab.read_manifest(UID, "batch-e12")
    assert "1.5" not in disk["projects"][0]["steps"], disk["projects"][0]
    print("OK F12 — live wins in-process, manifest survives restarts, no write-back.")


def _test_f15_write_errors():
    print("\n--- F15: manifest write failures recorded in the manifest ---")
    real_api = _import_real_api()
    tmp = Path(tempfile.mkdtemp())
    import storage_client as _sc
    # Storage failure only → local write succeeds; the error record itself is
    # re-persisted by write_manifest (B3 — a degrading feed must be visible).
    with patch.object(ab, "OUTPUT_ROOT", tmp), \
         patch.object(_sc, "write_file", side_effect=RuntimeError("storage down")):
        m = {"batch_id": "batch-e15", "created_at": "2026-09-20T00:00:00+00:00",
             "source": "drive", "state": "pending", "config_snapshot": {},
             "projects": [{"name": "AR_w", "state": "pending"}]}
        ab.write_manifest(UID, m)
        assert m["write_errors"] == 1, m.get("write_errors")
        assert "last_write_error" in m, m
        back = ab.read_manifest(UID, "batch-e15")
        assert back["write_errors"] == 1, back.get("write_errors")   # persisted

        ab.write_manifest(UID, m)                                    # still failing → grows
        assert m["write_errors"] == 2, m.get("write_errors")
        back = ab.read_manifest(UID, "batch-e15")
        assert back["write_errors"] == 2, back.get("write_errors")

        # Healthy write → no increments, counter preserved as history
        with patch.object(_sc, "write_file", return_value=None):
            ab.write_manifest(UID, m)
        assert m["write_errors"] == 2, m.get("write_errors")
        back = ab.read_manifest(UID, "batch-e15")
        assert back["write_errors"] == 2, back.get("write_errors")
    print("OK F15 — write_errors counter increments on failure, persists, stays stable.")


def _test_f13_batch_history():
    print("\n--- F13: list_user_batches — summaries, order, interrupted state ---")
    tmp = Path(tempfile.mkdtemp())

    def _mf(bid, created, projects, state="pending"):
        m = {"batch_id": bid, "created_at": created, "source": "drive",
             "state": state, "config_snapshot": {}, "projects": projects}
        with patch.object(ab, "OUTPUT_ROOT", tmp):
            ab.write_manifest(UID, m)

    _mf("batch-old", "2026-09-19T00:00:00+00:00", [
        {"name": "AR_a", "state": "done"},
        {"name": "AR_b", "state": "error", "error_step": "2"},
    ], state="done_with_errors")
    _mf("batch-live", "2026-09-18T00:00:00+00:00", [
        {"name": "AR_z", "state": "running"},
    ], state="running")
    _mf("batch-new", "2026-09-20T00:00:00+00:00", [
        {"name": f"AR_n{k}", "state": "done"} for k in range(1, 5)
    ], state="done")

    with patch.object(ab, "OUTPUT_ROOT", tmp):
        rows = ab.list_user_batches(UID, 20)
    assert [r["batch_id"] for r in rows] == ["batch-new", "batch-old", "batch-live"], rows

    old = rows[1]
    assert old["counts"] == {"total": 2, "done": 1, "error": 1, "pending": 0}, old
    assert old["state"] == "done_with_errors", old

    # interrupted = manifest says running but no engine knows about it
    assert rows[2]["state"] == "interrupted", rows[2]
    # preview names, capped at 3 + "+N more"
    assert rows[0]["preview_names"] == ["AR_n1", "AR_n2", "AR_n3", "+1 more"], rows[0]
    # summary must not leak the config snapshot
    assert "config_snapshot" not in rows[0], rows[0]

    # limit
    with patch.object(ab, "OUTPUT_ROOT", tmp):
        assert len(ab.list_user_batches(UID, 2)) == 2, "limit applied"

    # A batch a live engine knows about stays "running"
    class _FakeTask:
        def done(self): return False
    ab._BATCH_TASKS["batch-live"] = _FakeTask()
    try:
        with patch.object(ab, "OUTPUT_ROOT", tmp):
            rows2 = ab.list_user_batches(UID, 20)
        assert rows2[2]["state"] == "running", rows2[2]
    finally:
        ab._BATCH_TASKS.pop("batch-live", None)
    print("OK F13 — ordering, counts, interrupted reconciliation, limit, preview caps.")


def _test_f14_resume():
    print("\n--- F14: resume_batch — guards + relaunch of an interrupted batch ---")
    real_api = _import_real_api()
    tmp = Path(tempfile.mkdtemp())
    with patch.object(ab, "OUTPUT_ROOT", tmp):
        _make_manifest(tmp, [{"name": "AR_p", "state": "pending"}], batch_id="batch-e14")
        allowed, reason = ab.resume_batch(UID, "missing")
        assert not allowed and reason == "batch-not-found", (allowed, reason)

        _make_manifest(tmp, [{"name": "AR_d", "state": "done"}], batch_id="batch-e14t")
        allowed, reason = ab.resume_batch(UID, "batch-e14t")
        assert not allowed and reason == "nothing-to-resume", (allowed, reason)

        class _FakeTask:
            def done(self): return False
        ab._BATCH_TASKS["batch-e14"] = _FakeTask()
        try:
            allowed, reason = ab.resume_batch(UID, "batch-e14")
            assert not allowed and reason == "already-running", (allowed, reason)
        finally:
            ab._BATCH_TASKS.pop("batch-e14", None)
        assert reason == "already-running"

    # Real relaunch of batch-e14 (pending AR_p) through the engine
    runner = _Runner()
    with patch.object(ab, "OUTPUT_ROOT", tmp), \
         patch.object(ab, "_spawn_runtime_task", new=lambda p, u, s, c: runner.run(p, u, s, c)), \
         patch.object(real_api, "_latest_step_result_row", return_value=None, create=True):
        _run_batch(tmp, "batch-e14", start_fn=lambda: ab.resume_batch(UID, "batch-e14"))
    assert [(p, s) for (p, s) in runner.calls] == \
        [("AR_p", s) for s in ab.BATCH_SEQUENCE], runner.calls
    with patch.object(ab, "OUTPUT_ROOT", tmp):
        m = ab.read_manifest(UID, "batch-e14")
    assert m["projects"][0]["state"] == "done", m
    assert all(v["state"] == "done" for v in m["projects"][0]["steps"].values()), m
    print("OK F14 — unknown/terminal/live guards; interrupted batch resumes to completion.")


def _test_f16_step_cache():
    print("\n--- F16: step_cache — hits, TTL band, invalidation, first_not_done ---")
    real_api = _import_real_api()
    import step_cache as sc
    sc.clear()

    # Single TTL knob, clamped to the 120–300 band (Q-C1)
    assert sc.ttl_seconds() == 180
    with patch.dict(os.environ, {"STEP_CACHE_TTL": "10"}):
        assert sc.ttl_seconds() == 120
    with patch.dict(os.environ, {"STEP_CACHE_TTL": "999"}):
        assert sc.ttl_seconds() == 300

    # GET /status: SQL consulted once per TTL window, then served from cache
    calls = {"sql": 0}
    def fake_row(u2, p2, sid):
        calls["sql"] += 1
        return {"badge": "success"}
    with patch.object(real_api, "_latest_step_result_row", side_effect=fake_row):
        r1 = real_api.get_step_status("AR_c", "1", {"id": UID})
        r1b = real_api.get_step_status("AR_c", "1", {"id": UID})
        assert r1 == r1b == {"status": "done", "output_exists": True}, (r1, r1b)
        assert calls["sql"] == 1, calls                 # second call = cache hit
        sc.clear()
        real_api.get_step_status("AR_c", "1", {"id": UID})
        assert calls["sql"] == 2, calls                 # cleared → recompute

    # put() merges fields; invalidate modes: step / project / user
    sc.put(UID, "p", "6", status="done", output_exists=True)
    sc.put(UID, "p", "6", files=[{"name": "file1.txt"}])
    entry = sc.get(UID, "p", "6")
    assert entry["status"] == "done" and entry["files"], entry
    sc.invalidate(UID, "p", "6")
    assert sc.get(UID, "p", "6") is None, "step-level invalidate"
    sc.put(UID, "p", "6", status="done"); sc.put(UID, "p", "2", status="done")
    sc.invalidate(UID, "p")
    assert sc.get(UID, "p", "6") is None and sc.get(UID, "p", "2") is None, "project wipe"
    sc.put(UID, "p", "6", status="done"); sc.put(UID, "q", "6", status="done")
    sc.invalidate(UID)
    assert sc.get(UID, "p", "6") is None and sc.get(UID, "q", "6") is None, "user wipe"

    # /output served from its cached manifest — the Storage walk runs ONCE
    tmp = Path(tempfile.mkdtemp())
    storage_calls = {"n": 0}
    def fake_list_recursive(prefix):
        storage_calls["n"] += 1
        return [{"name": f"{prefix}/accepted/page_1.txt", "metadata": {"size": 12}}]
    with patch.object(ab, "OUTPUT_ROOT", tmp), \
         patch.object(real_api, "_latest_step_result_row", return_value=None), \
         patch.object(real_api, "list_files_recursive", side_effect=fake_list_recursive):
        f1 = real_api.get_step_output_files("AR_c", "2", {"id": UID})
        f2 = real_api.get_step_output_files("AR_c", "2", {"id": UID})
        assert f1["files"] and f1["files"] == f2["files"], (f1, f2)
        assert storage_calls["n"] == 1, storage_calls   # second call = cache hit

    # first_not_done_step: second call fully cached (zero extra SQL)
    n_sql = {"n": 0}
    def fake_row2(u2, p2, sid):
        n_sql["n"] += 1
        return {"badge": "success"} if sid in ("1", "1.5", "1.6") else None
    sc.clear()
    with patch.object(ab, "OUTPUT_ROOT", tmp), \
         patch.object(real_api, "_latest_step_result_row", side_effect=fake_row2):
        assert ab.first_not_done_step(UID, "AR_fn") == "2", "SQL success on 1/1.5/1.6"
        first_pass = n_sql["n"]
        assert first_pass == 4, n_sql                    # steps 1/1.5/1.6 done + entry 2 probed
        assert ab.first_not_done_step(UID, "AR_fn") == "2"
        assert n_sql["n"] == first_pass, "second entry = pure cache hits"
    sc.clear()
    print("OK F16 — TTL knob, /status + /output + first_not_done cache hits, invalidation map.")


def _test_f4_single_file_regressions():
    print("\n--- F4: single-file import regressions ---")
    try:
        extract_drive_file_id(f"https://drive.google.com/drive/folders/{FOLDER_ID}")
        raise AssertionError("folder link must stay rejected for single-file import")
    except GoogleDriveImportError as e:
        assert "folder link" in e.message, e.message
    assert extract_drive_file_id(
        f"https://drive.google.com/file/d/{FILE_LINK_ID}/view") == FILE_LINK_ID
    print("OK F4 â€” single-file import behavior untouched.")


def _run_all():
    _test_f1_folder_parsing()
    _test_f2_scan()
    _test_f3_download_by_id()
    _test_f4_single_file_regressions()
    _test_f5_naming()
    _test_f6_config_resolution()
    _test_f7_manifest_roundtrip()
    _test_f8_engine()
    _test_f9_retry()
    _test_f10_resume()
    _test_f11_step_progress()
    _test_f12_merge_live()
    _test_f13_batch_history()
    _test_f14_resume()
    _test_f15_write_errors()
    _test_f16_step_cache()
    print("\n" + "=" * 60)
    print("ALL AUTORUN-BATCH TESTS PASSED (Phases 0-5 coverage)")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()

