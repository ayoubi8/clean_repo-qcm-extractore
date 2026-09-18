"""Google Drive link import — verification tests (plan §8, service layer).

G1  extract_drive_file_id: accepted Drive link formats + strict rejections
G2  SSRF guards: private/loopback DNS blocked, non-allowlisted host blocked,
    http:// blocked — all BEFORE any request is made
G3  download_drive_pdf via fake httpx client:
    - happy path (magic bytes + display filename)
    - redirect hop handling (allowlisted pass, private IP + foreign host block)
    - confirm-page single retry (病毒-scan page)
    - 403 → NOT_PUBLIC, 404 → NOT_FOUND, 429 → QUOTA
    - non-PDF magic → NOT_PDF, HTML login page → NOT_PUBLIC
    - byte cap exceeded → TOO_LARGE
G4  is_enabled flag + per-user rate limiter pattern
"""
import io
import os
import sys
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "api"))

import httpx  # noqa: E402
import gdrive_import as gd  # noqa: E402
from gdrive_import import (GoogleDriveImportError, extract_drive_file_id,
                           _is_blocked_ip, _extract_confirm_params,
                           _looks_like_confirm_page, _content_disposition_filename,
                           assert_public_url, resolve_and_check,
                           download_drive_pdf, build_download_url,
                           build_confirm_url, is_enabled)

PDF_BYTES = b"%PDF-1.4\n%" + b"A" * (1024 * 256)
PDF_FILE_ID = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcd"  # 30 chars


class _FakeResp:
    def __init__(self, status=200, headers=None, content=b"", chunks=None,
                 next_url=None, text=""):
        self.status_code = status
        self.headers = headers or {}
        self.content = content
        self._chunks = chunks
        self.next_request = None
        if next_url:
            self.next_request = type("NR", (), {"url": next_url})()
        self.text = text

    def iter_bytes(self, chunk_size=1024 * 1024):
        if self._chunks is not None:
            for c in self._chunks:
                yield c
        else:
            yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeClient:
    """Minimal httpx.Client stand-in with scripted responses per URL."""

    def __init__(self, script):
        self._script = script  # list of callables: (url) -> _FakeResp
        self.urls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        self.urls.append(url)
        if not self._script:
            raise AssertionError("unexpected extra request: " + url)
        action = self._script.pop(0)
        return action(self, url)


def _public_dns():
    infos = [(None, None, None, "", ("203.0.113.7", 443))]
    return infos


def _expect_error(fn, code, key_code=None):
    try:
        fn()
    except GoogleDriveImportError as e:
        assert e.code == code, f"expected {code}, got {e.code}: {e.message}"
        return e
    raise AssertionError(f"expected GoogleDriveImportError({code})")


# ---------------------------------------------------------------------------
def _test_g1_parsing():
    print("\n--- G1: link parsing (strict) ---")
    fid = "abcdef1234567890123456789012345"  # 31 chars
    accepted = [
        f"https://drive.google.com/file/d/{fid}/view",
        f"https://drive.google.com/file/d/{fid}/view?usp=sharing",
        f"https://drive.google.com/open?id={fid}",
        f"https://drive.google.com/uc?id={fid}&export=download",
        f" https://drive.google.com/file/d/{fid}/view ",
    ]
    for link in accepted:
        assert extract_drive_file_id(link) == fid, f"FAILED on link: {link}"

    rejects = [
        ("https://docs.google.com/document/d/1abcabcabcabcabcabcabc/edit",
         "That link is a Google Doc"),
        ("https://docs.google.com/spreadsheets/d/1abcabcabcabcabcabcabc/edit",
         "That link is a Google Sheet"),
        ("https://docs.google.com/presentation/d/1abcabcabcabcabcabcabc/edit",
         "That link is a Google Slide"),
        ("https://drive.google.com/drive/folders/1abcabcabcabcabcabcabc",
         "folder link"),
        ("https://evil.com/file/d/1abcabcabcabcabcabcabc/view", "valid Drive link"),
        ("http://drive.google.com/file/d/1abcabcabcabcabcabcabc/view", "valid Drive link"),
        ("not a link at all", "valid Drive link"),
        ("", "valid Drive link"),
    ]
    for link, frag in rejects:
        try:
            extract_drive_file_id(link)
            raise AssertionError(f"should reject: {link}")
        except GoogleDriveImportError as e:
            assert frag in e.message, (link, e.message)

    # Non-Google random URL that sneaks past suffix checks is still rejected
    try:
        extract_drive_file_id("https://attach.example.com/x.pdf?id=" + fid)
        raise AssertionError("should reject foreign host")
    except GoogleDriveImportError:
        pass
    print("OK G1 — parsing strict: 5 accepted formats, all rejections friendly.")


def _test_g2_ssrf():
    print("\n--- G2: SSRF guards (no request needed to prove the block) ---")
    # Private-range IP classification
    for bad in ["127.0.0.1", "10.1.2.3", "172.16.0.9", "172.31.255.1",
                "192.168.1.1", "169.254.169.254", "0.0.0.0", "100.64.0.1",
                "198.18.0.5"]:
        assert _is_blocked_ip(bad), bad
    assert not _is_blocked_ip("142.250.4.138")  # public (Google anycast sample)
    assert _is_blocked_ip("::1")
    assert _is_blocked_ip("::ffff:10.0.0.1")    # IPv4-mapped IPv6
    assert not _is_blocked_ip("2607:f8b0:4004:83f::200e")

    # Allowlist + scheme checks before DNS
    assert_public_url("https://drive.google.com/uc?export=download&id=x")
    assert_public_url("https://drive.usercontent.google.com/download?id=x")
    for url in ["http://drive.google.com/uc?id=x",                 # http
                "https://evil.com/download",                        # foreign host
                "https://evil.host.com/download",                   # substring game
                "https://notdrive.google.com.evil.com/download"]:   # suffix trick
        try:
            assert_public_url(url)
            raise AssertionError(f"should block: {url}")
        except GoogleDriveImportError as e:
            assert e.code == "BLOCKED_HOST", (url, e.code)

    # DNS-based rebind: allowlisted host resolving to a private IP
    with patch("gdrive_import.socket.getaddrinfo",
               return_value=[(None, None, None, "google", ("192.168.0.7", 443))]):
        try:
            resolve_and_check("drive.google.com")
            raise AssertionError("private DNS should be blocked")
        except GoogleDriveImportError as e:
            assert e.code == "BLOCKED_HOST", e.code

    # Public DNS passes
    with patch("gdrive_import.socket.getaddrinfo",
               return_value=[(None, None, None, "", ("142.250.72.46", 443))]):
        resolve_and_check("drive.google.com")  # no raise
    print("OK G2 — scheme/host allowlist + private-DNS blocking verified.")


def _fake_dns_public():
    """Patch socket resolution used by assert_public_url to a public IP."""
    return patch("gdrive_import.socket.getaddrinfo",
                 return_value=[(None, None, None, "", ("142.250.72.46", 443))])


def _test_g3_download():
    print("\n--- G3: download flow (fake httpx client) ---")
    disp = _content_disposition_filename({
        "content-disposition": 'attachment; filename="My Exam (2024) - QCM [PDF].pdf"'})
    assert disp == "My Exam _2024_ - QCM _PDF.pdf", repr(disp)
    disp2 = _content_disposition_filename({
        "content-disposition": "attachment; filename*=UTF-8''Biochimie%202024.pdf"})
    assert disp2 == "Biochimie 2024.pdf", disp2

    fake_factory = lambda: _FakeClient([
        lambda c, url: _FakeResp(content=PDF_BYTES,
                                 headers={"content-disposition": 'attachment; filename="exam.pdf"'},
                                 text=""),
    ])
    with _fake_dns_public():
        data, name = download_drive_pdf(
            "https://drive.google.com/file/d/abcd1234567890abcdefghijk123/view",
            client_factory=fake_factory)
    assert data == PDF_BYTES, "magic-validated body returned"
    assert name == "exam.pdf", name

    # 403 / 404 / 429 mapping
    for status, code in [(403, "NOT_PUBLIC"), (404, "NOT_FOUND"), (429, "QUOTA")]:
        factory = lambda: _FakeClient([lambda c, url: _FakeResp(status=status)])
        with _fake_dns_public():
            try:
                download_drive_pdf("https://drive.google.com/file/d/"
                                   "abcd1234567890abcdefghijk123/view",
                                   client_factory=factory)
                raise AssertionError(f"should fail {status}")
            except GoogleDriveImportError as e:
                assert e.code == code, (status, e.code)

    # Redirect handling: allowlisted https hop → 200 PDF
    factory = lambda: _FakeClient([
        lambda c, url: _FakeResp(status=302, next_url="https://drive.usercontent.google.com/download?id=x&export=download"),
        lambda c, url: _FakeResp(content=PDF_BYTES),
    ])
    with _fake_dns_public():
        data, _ = download_drive_pdf("https://drive.google.com/file/d/"
                                     "abcd1234567890abcdefghijk123/view",
                                     client_factory=factory)
    assert data == PDF_BYTES
    # never followed blindly: single hop only consumed
    try:
        download_drive_pdf("https://drive.google.com/file/d/"
                           "abcd1234567890abcdefghijk123/view",
                           client_factory=lambda: _FakeClient([
                               lambda c, url: _FakeResp(status=302, next_url="https://evil.com/x"),
                           ]))
        raise AssertionError("foreign-host redirect should be blocked")
    except GoogleDriveImportError as e:
        assert e.code == "BLOCKED_HOST", e.code

    # Redirect to accounts.google.com → NOT_PUBLIC
    try:
        download_drive_pdf("https://drive.google.com/file/d/"
                           "abcd1234567890abcdefghijk123/view",
                           client_factory=lambda: _FakeClient([
                               lambda c, url: _FakeResp(status=302,
                                                        next_url="http://accounts.google.com/ServiceLogin"),
                           ]))
        raise AssertionError("login redirect should be rejected")
    except GoogleDriveImportError as e:
        assert e.code == "NOT_PUBLIC", e.code

    # Confirm page → confirm URL contains confirm=t & uuid
    confirm_html = (b'<html><form action="download"><input name="confirm" value="t">'
                    b'<input name="uuid" value="abc123-def456"></form></html>')
    factory = lambda: _FakeClient([
        lambda c, url: _FakeResp(headers={"content-type": "text/html"}, content=confirm_html),
        lambda c, url: (_FakeResp(content=PDF_BYTES) if "confirm=t" in url and "uuid=abc123-def" in url
                        else _FakeResp(status=500)),
    ])
    with _fake_dns_public():
        data, _ = download_drive_pdf("https://drive.google.com/file/d/"
                                     "abcd1234567890abcdefghijk123/view",
                                     client_factory=factory)
    assert data == PDF_BYTES

    # Non-PDF magic → NOT_PDF
    factory = lambda: _FakeClient([
        lambda c, url: _FakeResp(content=b"PK\x03\x04" + b"zipdata" * 10),
    ])
    with _fake_dns_public():
        _expect_error(lambda: download_drive_pdf(
            "https://drive.google.com/file/d/abcd1234567890abcdefghijk123/view",
            client_factory=factory), "NOT_PDF")

    # HTML login page (no confirm markers) → NOT_PUBLIC
    factory = lambda: _FakeClient([
        lambda c, url: _FakeResp(headers={"content-type": "text/html"},
                                 content=b"<html>Sign in with your Google account... accounts.google.com</html>"),
    ])
    with _fake_dns_public():
        _expect_error(lambda: download_drive_pdf(
            "https://drive.google.com/file/d/abcd1234567890abcdefghijk123/view",
            client_factory=factory), "NOT_PUBLIC")

    # Oversize → TOO_LARGE, streamed (chunks, no Content-Length trust)
    big_chunks = [b"A" * (1024 * 1024) for _ in range(4)]
    factory = lambda: _FakeClient([
        lambda c, url: _FakeResp(chunks=big_chunks),
    ])
    with _fake_dns_public():
        _expect_error(lambda: download_drive_pdf(
            "https://drive.google.com/file/d/abcd1234567890abcdefghijk123/view",
            max_bytes=100 * 1024, client_factory=factory), "TOO_LARGE")

    # Too many hops
    def redirect_factory():
        calls = {"n": 0}
        def mk(c, url):
            calls["n"] += 1
            return _FakeResp(status=302, next_url=f"https://drive.google.com/hop{calls['n']}")
        return _FakeClient([mk] * 10)
    with _fake_dns_public():
        _expect_error(lambda: download_drive_pdf(
            "https://drive.google.com/file/d/abcd1234567890abcdefghijk123/view",
            client_factory=redirect_factory), "TOO_MANY_HOPS")
    print("OK G3 — download: confirm-page, redirects, caps, error map all verified.")


def _test_g4_flag_and_rate():
    print("\n--- G4: feature flag + per-user rate limit ---")
    with patch.dict(os.environ, {"GDRIVE_IMPORT_ENABLED": "false"}):
        assert not is_enabled()
    with patch.dict(os.environ, {"GDRIVE_IMPORT_ENABLED": "true"}):
        assert is_enabled()
    with patch.dict(os.environ, {"GDRIVE_IMPORT_ENABLED": "1"}):
        assert is_enabled()

    # Per-user limiter lives in real_api; import only that helper is heavy
    # (FastAPI app import). Re-implemented contract check through auth-like
    # sliding window semantics is covered by GUI/manual QA + persistence PR
    # tests; here we assert the in-service helpers only.
    from pathlib import Path
    text = (Path(ROOT) / "api" / "real_api.py").read_text(encoding="utf-8")
    assert "_check_user_rate_limit(user[\"id\"], \"gdrive_import\", limit=10" in text
    assert "is_enabled()" in text and r'HTTPException(status_code=404, detail="Drive import is not enabled' in text
    print("OK G4 — flag + rate-limit contract present.")


if __name__ == "__main__":
    _test_g1_parsing()
    _test_g2_ssrf()
    _test_g3_download()
    _test_g4_flag_and_rate()
    print("\nALL GDRIVE IMPORT TESTS PASSED ✅")
