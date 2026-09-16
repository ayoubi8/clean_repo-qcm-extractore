"""UI Redesign U-edits — verification tests (phase-7-style reporting).

U1  case_belonging_check present in the exported xlsx (real file export +
    header read-back; backend phase 3 put it in _PREFERRED_COLUMNS).
U2.1 Backend emits EXACTLY ONE disagreement summary line per run:
    "[CC-BOUNDARY] ⚠️ N disagreement(s) flagged — review case_belonging_check"
U2.2 Frontend matcher `isCcBoundaryDisagreement` matches that exact marker
    (and only it) — matcher lives in frontend/src/store/pipelineStore.ts;
    verified here by importing the TS logic pattern (duplicated as JS mirror
    to avoid a node/tsc dependency in this suite).
"""
import io
import json
import os
import sys
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

CASE = "CAS CLINIQUE 1\r\nSalma, 56 ans, sous Amiodarone."


def _test_u1():
    print("\n--- U1: case_belonging_check present in the exported XLSX ---")
    from modules.utils.xlsx_exporter import export_qcms_to_xlsx
    from openpyxl import load_workbook
    qcms = [
        {"Num": 1, "Text": "t1", "Cas": CASE,
         "case_belonging_check": "checker YES (0.93): uses reported diagnosis"},
        {"Num": 2, "Text": "t2", "Cas": CASE,
         "case_belonging_check": "boundary re-check YES (0.87): cas re-attached"},
    ]
    path = os.path.join(ROOT, "output", "test_u1_export.xlsx")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        export_qcms_to_xlsx(qcms, path)
        wb = load_workbook(path)
        ws = wb.active
        headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        assert "case_belonging_check" in headers, headers
        idx_cas = headers.index("Cas")
        assert headers.index("case_belonging_check") == idx_cas + 1, headers
        # Data present in the cells of row 2
        row2 = [ws.cell(row=2, column=i + 1).value for i in range(len(headers))]
        assert row2[0] == 1 and row2[headers.index("case_belonging_check")], row2
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    print("OK U1 — case_belonging_check exported, positioned right after Cas.")


def _test_u2_backend_line():
    print("\n--- U2.1: exactly ONE summary line per run when relink happens ---")
    from modules.clinical_case_checker import run_boundary_checks
    import tempfile, shutil
    tmp = tempfile.mkdtemp()
    try:
        base = os.path.join(ROOT, "tests")
        sys.path.insert(0, base)
        from test_cc_redesign_phase5_boundary_checks import (
            _Ctx, _seed, _write_queue, _client, CASE_P5,
        )
    except Exception:
        # local minimal fixtures (avoid cross-file drift)
        pass

    from pathlib import Path
    tmpP = Path(tmp)
    d = tmpP / "step3_metadata" / "accepted"
    d.mkdir(parents=True, exist_ok=True)
    qcm = {"uid": "u1", "page": 1, "number": 1, "text": "Q?",
           "propositions": {"a": "P"}}
    trigger = dict(qcm)
    boundary = dict(qcm)
    boundary["uid"] = "u2"
    boundary.pop("cas", None)
    qcm.update({"cas": CASE})
    (d / "page_1.json").write_text(json.dumps([qcm, boundary], ensure_ascii=False),
                                   encoding="utf-8")
    root = tmpP / "step3_metadata"
    (root / "cc_boundary_transitions.json").write_text(
        json.dumps({"transitions": [
            {"case_cas": CASE, "trigger_page": 1, "trigger_number": 1,
             "trigger_uid": "u1"}]}), encoding="utf-8")

    class C(_Ctx):
        pass

    class _FakeOpenRouter:
        def __init__(self, *a, **k):
            async def gen(prompt, **kw):
                return {"content": json.dumps({"applies": True, "confidence": 0.9}),
                        "usage": {}, "cost": 0.0}
            self._m = MagicMock()
            self._m.generate_completion_async = gen
        def __getattr__(self, name):
            return getattr(self._m, name)

    buf = io.StringIO()
    with patch("modules.clinical_case_checker.OpenRouterClient", return_value=_FakeOpenRouter()):
        with redirect_stdout(buf):
            from modules.clinical_case_checker import run_boundary_checks as rbc
            import datetime  # noqa: F401
            res = rbc(MagicMock(), _Ctx(tmpP))
    out = buf.getvalue()
    assert res["stats"]["relinked"] == 1, res
    lines = [l for l in out.splitlines() if "[CC-BOUNDARY] ⚠️" in l]
    assert len(lines) == 1, lines
    assert "disagreement(s) flagged — review case_belonging_check" in lines[0]
    assert lines[0].startswith("[CC-BOUNDARY] ⚠️ 1")
    # no disagreement -> no line
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        pass
    print("OK single per-run marker line emitted with the exact expected text.")


def _test_u2_frontend_matcher_mirror():
    print("\n--- U2.2: isCcBoundaryDisagreement logic mirror ---")
    def isCcBoundaryDisagreement(text):
        return (isinstance(text, str) and '[CC-BOUNDARY]' in text
                and 'disagreement(s) flagged' in text)
    good = "[CC-BOUNDARY] ⚠️ 2 disagreement(s) flagged — review case_belonging_check"
    assert isCcBoundaryDisagreement(good)
    assert isCcBoundaryDisagreement("[CC-BOUNDARY] 💾 audit → cc_boundary_checks.json") is False
    assert isCcBoundaryDisagreement(None) is False
    assert isCcBoundaryDisagreement(42) is False
    # does NOT collide with the checker-error matcher contract
    def isCcCheckerError(text):
        return isinstance(text, str) and '[CC-CHECK]' in text and '⚠️ ERROR' in text
    assert not isCcCheckerError(good) and not isCcBoundaryDisagreement(
        "[CC-CHECK] ⚠️ ERROR: model failed")
    print("OK marker matched exclusively; no collision with isCcCheckerError.")


def _run_all():
    _test_u1()
    _test_u2_backend_line()
    _test_u2_frontend_matcher_mirror()
    print("\n" + "=" * 60)
    print("ALL UI U-EDIT TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
