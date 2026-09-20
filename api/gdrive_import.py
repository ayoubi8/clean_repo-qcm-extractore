"""gdrive_import.py — anonymous Google Drive PDF import service.

Downloads a PUBLIC Drive PDF ("Anyone with the link → Viewer") server-side,
with no OAuth, and hands validated bytes to the same ingest tail used by
file uploads (real_api._store_pdf_bytes).

Design contract (docs/plans/gdrive-link-import-plan.md):
  - Only Drive file IDs are accepted. The user-supplied URL is parsed, never
    fetched; download URLs are constructed server-side from the ID.
  - SSRF guards: https-only, strict host allowlist, DNS resolved and every
    IP checked against private/loopback/link-local/reserved ranges,
    re-validated on every redirect hop (max 3).
  - Streaming download with a hard byte cap (never trusts Content-Length),
    connect/read timeouts, magic-byte (%PDF-) validation.
  - Handles Drive's "can't scan for viruses" confirm page for large files.
  - Raw links are never logged (they may carry resourcekey params).
"""
import ipaddress
import re
import socket
import tempfile
from typing import Callable, Optional, Tuple
from urllib.parse import urljoin

import httpx


# ---------------------------------------------------------------------------
# Error contract
# ---------------------------------------------------------------------------

class GoogleDriveImportError(Exception):
    """Import failure with a user-facing message. `code` maps to HTTP status."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# Link parsing (strict — anything not matched is rejected)
# ---------------------------------------------------------------------------

# Drive file IDs are ~28-33 chars of [A-Za-z0-9_-]; {20,} is a safe floor.
_FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")
_FILE_URL_RE = re.compile(
    r"^https://drive\.google\.com/file/d/([A-Za-z0-9_-]{20,})(?:/.*)?$"
)
_ID_QUERY_RE = re.compile(
    r"^https://drive\.google\.com/(?:open|uc)\?(?:[^&]*&)?id=([A-Za-z0-9_-]{20,})(?:&.*)?$"
)

# Auto Run batch (Phase 2): FOLDER links are accepted by extract_drive_folder_id —
# extract_drive_file_id keeps rejecting them (single-file import unchanged).
_FOLDER_URL_RE = re.compile(
    r"^https://drive\.google\.com/drive/folders/([A-Za-z0-9_-]{20,})(?:[/?].*)?$"
)

# Google-native docs that are NOT PDFs — rejected explicitly.
_NON_PDF_PATTERNS = [
    (re.compile(r"docs\.google\.com/document/d/"), "That link is a Google Doc, not a PDF. "
     "Use File → Download → PDF in Google Docs, then upload the PDF."),
    (re.compile(r"docs\.google\.com/spreadsheets/d/"), "That link is a Google Sheet, not a PDF. "
     "Use File → Download → PDF in Google Sheets, then upload the PDF."),
    (re.compile(r"docs\.google\.com/presentation/d/"), "That link is a Google Slide, not a PDF. "
     "Use File → Download → PDF in Google Slides, then upload the PDF."),
    (re.compile(r"drive\.google\.com/drive/folders/"), "That's a folder link — share a single "
     "PDF file, not a folder."),
]

# Hosts we are ever allowed to talk to. Nothing else, ever.
ALLOWED_HOSTS = {
    "drive.google.com",
    "docs.google.com",
    "drive.usercontent.google.com",
}

MSG_NOT_PUBLIC = ("This file is not public. Set sharing to "
                  "'Anyone with the link' → Viewer, then try again.")
MSG_NOT_FOUND = "Drive file not found — check the link and that the file still exists."
MSG_QUOTA = "Drive is rate-limiting this file. Try again in a few minutes."
MSG_NOT_PDF = "The Drive file is not a PDF."
MSG_TOO_MANY_HOPS = "Too many redirects while downloading from Drive."
MSG_INVALID_LINK = ("Paste a valid Drive link, e.g. "
                    "https://drive.google.com/file/d/…/view")

MSG_FOLDER_INVALID = ("Paste a valid Drive FOLDER link, e.g. "
                      "https://drive.google.com/drive/folders/…")
MSG_FOLDER_FILE_LINK = ("That is a single-file link — Auto Run needs a Drive FOLDER "
                        "link (https://drive.google.com/drive/folders/…).")
MSG_FOLDER_NOT_PUBLIC = ("Couldn't read the Drive folder — make sure it is shared "
                         "as 'Anyone with the link' → Viewer, then try again.")


def extract_drive_file_id(link: str) -> str:
    """Extract the Drive file ID from a pasted link. Raises on anything else."""
    link = (link or "").strip()
    if not link:
        raise GoogleDriveImportError("INVALID_LINK", MSG_INVALID_LINK)

    m = _FILE_URL_RE.match(link)
    if m:
        return m.group(1)

    m = _ID_QUERY_RE.match(link)
    if m:
        return m.group(1)

    # Friendly rejections for obviously-not-PDF Drive links.
    for pattern, message in _NON_PDF_PATTERNS:
        if pattern.search(link):
            raise GoogleDriveImportError("NOT_A_PDF_LINK", message)

    if "drive.google.com" in link or "docs.google.com" in link:
        # Looks like Drive but the shape is unknown — never fetch it.
        raise GoogleDriveImportError("INVALID_LINK", MSG_INVALID_LINK)

    raise GoogleDriveImportError("INVALID_LINK", MSG_INVALID_LINK)


def build_download_url(file_id: str) -> str:
    """Construct (never accept) the download URL from a validated ID."""
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def build_confirm_url(file_id: str, confirm_token: Optional[str],
                      confirm_uuid: Optional[str]) -> str:
    """Variant of the download URL that skips the virus-scan confirm page."""
    base = f"https://drive.usercontent.google.com/download?id={file_id}&export=download"
    params = []
    if confirm_token:
        params.append(f"confirm={confirm_token}")
    else:
        params.append("confirm=t")
    if confirm_uuid:
        params.append(f"uuid={confirm_uuid}")
    return base + ("&" + "&".join(params) if params else "")


# ---------------------------------------------------------------------------
# SSRF guards
# ---------------------------------------------------------------------------

_EXTRA_BLOCKED_NETS = [  # CGNAT + benchmark + docs ranges not always flagged
    ipaddress.ip_network("100.64.0.0/10"),   # CGNAT shared address space
    ipaddress.ip_network("0.0.0.0/8"),        # "this network" legacy
    ipaddress.ip_network("198.18.0.0/15"),    # benchmarking
    ipaddress.ip_network("192.0.2.0/24"),     # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),   # TEST-NET-3
]


def _is_blocked_ip(ip_str: str) -> bool:
    """True for private / loopback / link-local / reserved / multicast ranges."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable → block
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:10.0.0.1 etc. — check the embedded IPv4
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True
    return any(ip in net for net in _EXTRA_BLOCKED_NETS)


def resolve_and_check(hostname: str) -> None:
    """Resolve hostname and block any resolved private/loopback IP.

    Raises GoogleDriveImportError("BLOCKED_HOST") on violation.
    """
    try:
        infos = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise GoogleDriveImportError("BLOCKED_HOST", MSG_INVALID_LINK) from e
    for info in infos:
        ip_str = info[4][0]
        if _is_blocked_ip(ip_str):
            # Never echo the user link; hostname is allowlisted/trusted only
            # after this check passes.
            raise GoogleDriveImportError(
                "BLOCKED_HOST",
                "Blocked by security policy (internal network address).")


def assert_public_url(url: str) -> None:
    """https + allowlisted host + no weird port. Applied to EVERY redirect hop."""
    if not url.startswith("https://"):
        raise GoogleDriveImportError("BLOCKED_HOST", MSG_INVALID_LINK)
    # Extract hostname without a full URL parse of user data (url comes from
    # our own construction or a hop's Location header on an allowlisted host).
    m = re.match(r"^https://([^/:?#]+)(?::\d+)?(?:[/?#].*)?$", url)
    if not m:
        raise GoogleDriveImportError("BLOCKED_HOST", MSG_INVALID_LINK)
    hostname = m.group(1).lower()
    if ":" in hostname or hostname not in ALLOWED_HOSTS:
        raise GoogleDriveImportError("BLOCKED_HOST", MSG_INVALID_LINK)
    resolve_and_check(hostname)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

CONFIRM_MARKERS = ("confirm=", "uc-name-size", "Virus scan warning")

_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0)
_MAX_REDIRECTS = 3


def _looks_like_confirm_page(content_type: str, head: bytes) -> bool:
    """Drive's 'can't scan for viruses' interstitial markers.

    NOTE: the form carries the confirm value as <input name="confirm"
    value="t">, so the literal 'confirm=' does NOT appear in the HTML —
    match the form-field markers instead.
    """
    return (content_type.startswith("text/html")
            and (b'name="confirm"' in head.lower()
                 or b"uc-name-size" in head
                 or b"irus scan" in head))


def _extract_confirm_params(html: bytes) -> Tuple[Optional[str], Optional[str]]:
    token = uuid_match = None
    m = re.search(rb"name=\"confirm\" value=\"([^\"]+)\"", html)
    if m:
        token = m.group(1).decode("ascii", errors="ignore")
    m = re.search(rb"name=\"uuid\" value=\"([A-Za-z0-9-]+)\"", html)
    if m:
        uuid_match = m.group(1).decode("ascii", errors="ignore")
    return token, uuid_match


def _content_disposition_filename(headers) -> Optional[str]:
    """Sanitized display filename from Content-Disposition; never for paths."""
    cd = headers.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    raw = m.group(1) if m else None
    if not raw:
        m = re.search(r'filename="?([^";]+)"?', cd)
        raw = m.group(1) if m else None
    if not raw:
        return None
    from urllib.parse import unquote
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", re.sub(r"\.pdf$", "", unquote(raw), flags=re.I))
    return (name.strip("._ ") + ".pdf").strip() or None


def download_drive_pdf(link: str,
                       max_bytes: int = 200 * 1024 * 1024,
                       on_chunk: Optional[Callable[[int], None]] = None,
                       client_factory=None) -> Tuple[bytes, Optional[str]]:
    """Download a PUBLIC Drive PDF. Returns (pdf_bytes, display_filename).

    Security contract:
      - file ID extracted strictly; download URL always built server-side
      - https-only + host allowlist re-asserted on every redirect hop
      - DNS resolved per hop and private-range IPs blocked
      - streamed with a hard byte cap (Content-Length ignored)
      - result verified as PDF via %PDF- magic bytes
    Raises GoogleDriveImportError with a user-facing message on any failure.
    """
    file_id = extract_drive_file_id(link)
    return _download_drive_id(file_id, max_bytes=max_bytes, on_chunk=on_chunk,
                              client_factory=client_factory)


def download_drive_file_by_id(file_id: str,
                              max_bytes: int = 200 * 1024 * 1024,
                              on_chunk: Optional[Callable[[int], None]] = None,
                              client_factory=None) -> Tuple[bytes, Optional[str]]:
    """Download an already-validated Drive file ID (Auto Run batch flow).

    Same contract as download_drive_pdf — the ID comes from scan_drive_folder,
    but the download itself carries the exact same guards: server-built URL,
    https + host allowlist + DNS check on every hop, streamed byte cap,
    %PDF- magic validation. Raises GoogleDriveImportError on any failure.
    """
    if not _FILE_ID_RE.fullmatch(file_id or ""):
        raise GoogleDriveImportError("INVALID_LINK", MSG_INVALID_LINK)
    return _download_drive_id(file_id, max_bytes=max_bytes, on_chunk=on_chunk,
                              client_factory=client_factory)


def _download_drive_id(file_id: str,
                       max_bytes: int,
                       on_chunk: Optional[Callable[[int], None]],
                       client_factory) -> Tuple[bytes, Optional[str]]:
    """Streaming download shared by the link and file-ID entry points."""
    url = build_download_url(file_id)
    hops = 0
    confirm_retried = False
    display_name: Optional[str] = None

    # One shared client; redirects handled manually so each hop is re-checked.
    client_builder = client_factory or (lambda: httpx.Client(
        follow_redirects=False, timeout=_TIMEOUT))

    with client_builder() as client:
        while True:
            assert_public_url(url)
            try:
                # NOTE: httpx Response supports the context-manager protocol
                # only via client.stream() — a plain .get() response raises
                # TypeError inside `with`, which surfaced as a 500.
                stream_cm = client.stream("GET", url, headers={
                    "User-Agent": "Mozilla/5.0 (QCM-Extractor importer)",
                    "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.5",
                })
            except httpx.TimeoutException:
                raise GoogleDriveImportError(
                    "TIMEOUT", "Download timed out — try again or use a smaller file.")
            except httpx.HTTPError as e:
                raise GoogleDriveImportError(
                    "NETWORK",
                    f"Could not reach Google Drive ({type(e).__name__}). Try again.")

            try:
                with stream_cm as resp:
                    hops += 1
                    if hops > _MAX_REDIRECTS:
                        raise GoogleDriveImportError("TOO_MANY_HOPS", MSG_TOO_MANY_HOPS)

                    status = resp.status_code
                    location = resp.headers.get("location") or ""

                    # Redirect hop — relative or absolute, re-checked next loop.
                    # Login redirects → file is NOT public (never fetch it).
                    if 300 <= status < 400:
                        nxt = urljoin(url, location or "").strip()
                        if not nxt.startswith("https://"):
                            raise GoogleDriveImportError("NOT_PUBLIC", MSG_NOT_PUBLIC)
                        if "accounts.google.com" in nxt.lower()[:40]:
                            raise GoogleDriveImportError("NOT_PUBLIC", MSG_NOT_PUBLIC)
                        url = nxt
                        continue

                    if status == 403:
                        raise GoogleDriveImportError("NOT_PUBLIC", MSG_NOT_PUBLIC)
                    if status == 404:
                        raise GoogleDriveImportError("NOT_FOUND", MSG_NOT_FOUND)
                    if status == 429:
                        raise GoogleDriveImportError("QUOTA", MSG_QUOTA)
                    if status >= 400:
                        raise GoogleDriveImportError(
                            "DRIVE_ERROR", f"Google Drive returned HTTP {status}.")

                    ctype = (resp.headers.get("content-type") or "").lower()
                    disp_name = _content_disposition_filename(resp.headers)
                    if disp_name:
                        display_name = disp_name

                    # Confirm page (large files) or any HTML body: probe the head.
                    if ctype.startswith("text/html"):
                        head = b""
                        for chunk in resp.iter_bytes(chunk_size=65536):
                            head += chunk
                            if len(head) >= 65536:
                                break
                        if not _looks_like_confirm_page(ctype, head):
                            head_text = head[:2000].lower()
                            if (b"accounts.google" in head_text
                                    or b"sign in" in head_text):
                                raise GoogleDriveImportError("NOT_PUBLIC", MSG_NOT_PUBLIC)
                            raise GoogleDriveImportError("NOT_PDF", MSG_NOT_PDF)
                        if confirm_retried:
                            raise GoogleDriveImportError(
                                "CONFIRM_LOOP", "Could not get past Google Drive's "
                                "virus-scan confirmation for this file. Try a smaller file.")
                        confirm_retried = True
                        token, cuuid = _extract_confirm_params(head)
                        url = build_confirm_url(file_id, token, cuuid)
                        continue  # stream closed on with-exit

                    # PDF body — stream with a hard byte cap.
                    total = 0
                    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
                    try:
                        for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                            total += len(chunk)
                            if total > max_bytes:
                                raise GoogleDriveImportError(
                                    "TOO_LARGE",
                                    f"File is over the {max_bytes // (1024 * 1024)} MB limit "
                                    "for Drive import.")
                            spool.write(chunk)
                            if on_chunk:
                                on_chunk(total)
                    except GoogleDriveImportError:
                        spool.close()
                        raise
                    except httpx.HTTPError as e:
                        spool.close()
                        raise GoogleDriveImportError(
                            "NETWORK", f"Download interrupted ({type(e).__name__}). Try again.")

                    # PDF magic validation (primary), HTML-masquerade check.
                    spool.seek(0)
                    magic = spool.read(999)
                    spool.seek(0)
                    if not magic.startswith(b"%PDF-"):
                        spool.close()
                        if b"<html" in magic.lower():
                            raise GoogleDriveImportError(
                                "NOT_PUBLIC",
                                "Drive returned a web page instead of the PDF. "
                                + MSG_NOT_PUBLIC)
                        raise GoogleDriveImportError("NOT_PDF", MSG_NOT_PDF)

                    data = spool.read()
                    spool.close()
                    return data, display_name
            except GoogleDriveImportError:
                raise
            except httpx.TimeoutException:
                raise GoogleDriveImportError(
                    "TIMEOUT", "Download timed out — try again or use a smaller file.")
            except httpx.HTTPError as e:
                raise GoogleDriveImportError(
                    "NETWORK", f"Could not reach Google Drive ({type(e).__name__}). Try again.")


# ---------------------------------------------------------------------------
# Folder scan (Auto Run batch, Phase 2)
# ---------------------------------------------------------------------------

# Drive's embedded file-explorer view — the anonymous listing endpoint for
# link-public folders (the same endpoint gdown parses). Simple anchor HTML:
#   <a href="https://drive.google.com/file/d/<ID>/view" ...>… name.pdf …</a>
# Sub-folders and native Google Docs use different href hosts → ignored, so
# the scan is naturally TOP-LEVEL-only (resolved Q4).
_FOLDER_VIEW_URL = "https://drive.google.com/embeddedfolderview?id={fid}"
_FOLDER_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_FOLDER_ANCHOR_RE = re.compile(
    r'<a[^>]+href="https://drive\.google\.com/file/d/([A-Za-z0-9_-]{20,})/view"[^>]*>(.*?)</a>',
    re.S | re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_FOLDER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def extract_drive_folder_id(link: str) -> str:
    """Extract the folder ID from a pasted Drive FOLDER link. Raises otherwise."""
    link = (link or "").strip()
    if not link:
        raise GoogleDriveImportError("INVALID_LINK", MSG_FOLDER_INVALID)

    m = _FOLDER_URL_RE.match(link)
    if m:
        return m.group(1)

    # Friendly near-miss hints before the generic rejection.
    if _FILE_URL_RE.match(link) or _ID_QUERY_RE.match(link):
        raise GoogleDriveImportError("INVALID_LINK", MSG_FOLDER_FILE_LINK)
    for pattern, message in _NON_PDF_PATTERNS:
        if pattern.search(link) and "folders" not in message:
            raise GoogleDriveImportError("INVALID_LINK",
                                         message + " " + MSG_FOLDER_FILE_LINK)
    if "drive.google.com" in link or "docs.google.com" in link:
        raise GoogleDriveImportError("INVALID_LINK", MSG_FOLDER_INVALID)

    raise GoogleDriveImportError("INVALID_LINK", MSG_FOLDER_INVALID)


def _build_folder_view_url(folder_id: str) -> str:
    """Construct (never accept) the listing URL from a validated folder ID."""
    return _FOLDER_VIEW_URL.format(fid=folder_id)


def _strip_anchor_text(inner_html: str) -> str:
    """Visible filename from an anchor's inner HTML (tags stripped, entities decoded)."""
    import html as _html
    text = _html.unescape(_TAG_RE.sub("", inner_html))
    return " ".join(text.split())


def _parse_folder_view_entries(html_text: str) -> dict:
    """Parse the embedded file-explorer page → {folder_name, files, total_files}.

    files = [{file_id, name}] for TOP-LEVEL entries whose name ends .pdf
    (case-insensitive), uncapped. total_files counts every top-level file
    entry (non-PDF names included) so callers can report the true total.
    Folder entries (sub-folders) and native Docs/Sheets/Slides hrefs are
    ignored by construction — they do not match the /file/d/ anchor shape.
    """
    title_m = _FOLDER_TITLE_RE.search(html_text)
    folder_name = ""
    if title_m:
        folder_name = re.sub(r"\s*-\s*Google Drive\s*$", "", title_m.group(1).strip(),
                             flags=re.I).strip()

    files = []
    total_files = 0
    seen_ids = set()
    for file_id, inner in _FOLDER_ANCHOR_RE.findall(html_text):
        if file_id in seen_ids:
            continue
        seen_ids.add(file_id)
        total_files += 1
        name = _strip_anchor_text(inner)
        if not name:
            name = f"drive_{file_id[:12]}.pdf"
        if name.lower().endswith(".pdf"):
            files.append({"file_id": file_id, "name": name})

    return {"folder_name": folder_name, "files": files, "total_files": total_files}


def scan_drive_folder(link: str,
                      max_files: Optional[int] = None,
                      client_factory=None) -> dict:
    """List the TOP-LEVEL PDFs of a PUBLIC Drive folder (no auth, no download).

    Returns {"folder_name": str, "files": [{file_id, name}...capped],
             "total_in_folder": int, "non_pdf_skipped": int}.

    Security contract mirrors the file downloader: the listing URL is built
    server-side from a strict folder-ID regex, https + host allowlist +
    DNS guards apply, and only drive.google.com is ever contacted.
    Raises GoogleDriveImportError with a user-facing message on failure.
    """
    folder_id = extract_drive_folder_id(link)
    url = _build_folder_view_url(folder_id)

    builder = client_factory or (lambda: httpx.Client(
        follow_redirects=False, timeout=_TIMEOUT))

    with builder() as client:
        for _ in range(_MAX_REDIRECTS + 1):
            assert_public_url(url)
            try:
                stream_cm = client.stream("GET", url, headers={
                    "User-Agent": _FOLDER_UA,
                    "Accept": "text/html",
                })
            except httpx.TimeoutException:
                raise GoogleDriveImportError(
                    "TIMEOUT", "Listing the folder timed out — try again.")
            except httpx.HTTPError as e:
                raise GoogleDriveImportError(
                    "NETWORK",
                    f"Could not reach Google Drive ({type(e).__name__}). Try again.")
            try:
                with stream_cm as resp:
                    status = resp.status_code
                    location = resp.headers.get("location") or ""

                    if 300 <= status < 400:
                        if "accounts.google.com" in (urljoin(url, location) or "").lower()[:40]:
                            raise GoogleDriveImportError("NOT_PUBLIC", MSG_FOLDER_NOT_PUBLIC)
                        url = urljoin(url, location or "").strip()
                        continue
                    if status == 404:
                        raise GoogleDriveImportError(
                            "NOT_FOUND",
                            "Drive folder not found — check the link and that the folder still exists.")
                    if status == 403:
                        raise GoogleDriveImportError("NOT_PUBLIC", MSG_FOLDER_NOT_PUBLIC)
                    if status >= 400:
                        raise GoogleDriveImportError(
                            "DRIVE_ERROR", f"Google Drive returned HTTP {status} for the folder.")

                    parsed = _parse_folder_view_stream(resp)
            except GoogleDriveImportError:
                raise
            except httpx.TimeoutException:
                raise GoogleDriveImportError(
                    "TIMEOUT", "Listing the folder timed out — try again.")
            except httpx.HTTPError as e:
                raise GoogleDriveImportError(
                    "NETWORK",
                    f"Could not reach Google Drive ({type(e).__name__}). Try again.")
            break
        else:
            raise GoogleDriveImportError("TOO_MANY_HOPS", MSG_TOO_MANY_HOPS)

    files = parsed["files"]
    total = parsed["total_files"]
    non_pdf_skipped = total - len(files)
    if max_files is not None:
        files = files[:max_files]

    return {
        "folder_name": parsed["folder_name"],
        "files": files,
        "total_in_folder": total,
        "non_pdf_skipped": non_pdf_skipped,
    }


def _parse_folder_view_stream(resp) -> dict:
    """Consume the listing response body (text/html) and parse its entries."""
    body = resp.text if hasattr(resp, "text") else resp.read().decode("utf-8", errors="replace")
    if not body:
        raise GoogleDriveImportError("NOT_PUBLIC", MSG_FOLDER_NOT_PUBLIC)
    parsed = _parse_folder_view_entries(body)
    if parsed["total_files"] == 0 and not parsed["folder_name"]:
        # 200 but no recognizable explorer structure → sign-in / unexpected page
        lowered = body.lower()
        if "accounts.google.com" in lowered or "sign in" in lowered:
            raise GoogleDriveImportError("NOT_PUBLIC", MSG_FOLDER_NOT_PUBLIC)
        raise GoogleDriveImportError(
            "PARSE_ERROR",
            "Couldn't read the folder listing — Google's page shape may have changed. "
            "Try again later or paste individual file links.")
    return parsed


def is_enabled() -> bool:
    """Feature flag — enabled by default; set GDRIVE_IMPORT_ENABLED=false to turn off."""
    import os
    return str(os.environ.get("GDRIVE_IMPORT_ENABLED", "true")).strip().lower() in (
        "1", "true", "yes", "on")
