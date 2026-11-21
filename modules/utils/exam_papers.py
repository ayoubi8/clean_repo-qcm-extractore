"""Exam papers, numbering scopes and clinical-case chains (deterministic).

Plan: docs/plans/exam-papers-sections-numbering-plan.md (§3-§5, §11).

The LLM proposes (Step 2 returns `origin_raw` / `section_header` per QCM);
these helpers parse and validate. Nothing here calls a model.

Vocabulary
- number      : the number printed IN THIS DOCUMENT in front of the question
                ("29-"). Unchanged meaning; Step 3/6/8 keep using it.
- paper       : one exam the question was printed in:
                {source, period, year, number, section, from, confidence}.
                `number` here is the ORIGINAL paper number ("N° 32").
- scope       : a stretch of the document where printed numbers are unique
                (a part such as "Pratique", a session such as "Rattrapage",
                a compilation chapter, or an inferred "part-2").
- session     : the label written in Tag (decision D2/D3): period + " Pratique"
                for the practical part, e.g. "Sec 01 Pratique", "Rattrapage".
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_SCOPE = "main"
EXAM_NUMBER_MAX = 150
COMPILATION_PAGE_RATIO = 0.30
COMPILATION_MIN_LINES = 3

MODE_AUTO = "auto"
MODE_SINGLE = "single_paper"
MODE_COMPILATION = "compilation"


# ── text helpers ────────────────────────────────────────────────────────────

def strip_accents(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", str(s))
                   if unicodedata.category(c) != "Mn")


def _fold(s: str) -> str:
    """Accent-free, lower-case, single-spaced."""
    return re.sub(r"\s+", " ", strip_accents(s or "").lower()).strip()


def extract_int(value) -> Optional[int]:
    """First integer inside a label: 7 -> 7, "QuestionN010" -> 10, "N° 7" -> 7.

    Returns None when the value holds no digit at all."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == value else None
    m = re.search(r"\d+", str(value))
    return int(m.group(0)) if m else None


# ── year rule (D1: START year) ─────────────────────────────────────────────

_YEAR_PAIR = re.compile(
    r"(?<!\d)((?:19|20)[\s.]?\d{2})\s*(?:[-/–—]|\.{1,3})\s*((?:19|20)[\s.]?\d{2})(?!\d)")
_YEAR_ONE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def _year_ok(y: int) -> bool:
    return 1990 <= y <= datetime.now().year + 1


def parse_year(value) -> Optional[int]:
    """'2020-2021' / '2020/2021' / '20.17-2018' / '2017 - 2018' / '2024' -> start year.

    Out-of-range or unreadable -> None (caller flags `missing_year`)."""
    if value is None or value == "":
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value if _year_ok(value) else None
    s = str(value)
    m = _YEAR_PAIR.search(s)
    if m:
        y = int(re.sub(r"\D", "", m.group(1)))
        return y if _year_ok(y) else None
    m = _YEAR_ONE.search(s)
    if m:
        y = int(m.group(1))
        return y if _year_ok(y) else None
    return None


# ── period / section vocabularies (D3: keep the PDF wording) ────────────────

def normalize_period(raw: Optional[str]) -> Optional[str]:
    """'sec 01' / 'Sec1' -> 'Sec 01', 'rattrap age' -> 'Rattrapage', 'emd 1' -> 'EMD1'."""
    if not raw:
        return None
    f = _fold(raw)
    m = re.search(r"\bsec(?:tion)?\s*0?(\d{1,2})\b", f)
    if m:
        return f"Sec {int(m.group(1)):02d}"
    # OCR: 'Sec Oi', 'Soc 01', 'See 01', 's~ 01' (O/o for 0, i/l for 1)
    m = re.search(r"\bs[a-z~^'\"]{0,2}\s*[0o]\s*([1-9il])\b", f)
    if m:
        d = m.group(1)
        return f"Sec 0{1 if d in 'il' else int(d)}"
    if re.search(r"rattrap\s*age|ratrapage|rattrapage", f.replace(" ", "")) or "rattrap" in f:
        return "Rattrapage"
    m = re.search(r"\bemd\s*(\d)\b", f)
    if m:
        return f"EMD{m.group(1)}"
    if re.search(r"session\s*normale", f):
        return "Session normale"
    if "synthese" in f:
        return "Synthèse"
    return None


def normalize_section(raw: Optional[str]) -> Optional[str]:
    """'Partie pratique' / 'Participratique' -> 'Pratique'; théorique -> 'Théorique'."""
    if not raw:
        return None
    f = _fold(raw).replace(" ", "")
    if "pratique" in f or "pratiq" in f:
        return "Pratique"
    if "theorique" in f or "theoriq" in f:
        return "Théorique"
    return None


def session_label(period: Optional[str], section: Optional[str]) -> Optional[str]:
    """D2/D3: 'Sec 01' + Pratique -> 'Sec 01 Pratique'; theory keeps the bare period."""
    parts = [p for p in (period, "Pratique" if section == "Pratique" else None) if p]
    return " ".join(parts) or None


# ── origin-line parser (§5.1) ───────────────────────────────────────────────

_ORIGIN_HEAD = re.compile(
    r"qu\S?stion\s*n\s*(?:[°ºo0>.:*~\"'`^]{1,2}\s*)?(\d{1,3})(?!\d)", re.IGNORECASE)


def parse_origin_line(text: Optional[str]) -> Optional[Dict]:
    """Parse '• Question N° 32, Partie pratique, Sec 01 de l'année 2021-2022'.

    Returns {number, period, section, year, year_raw, suspect, raw} or None when
    the text holds no 'Question N…<digits>' head. Tolerates the OCR variants seen
    in real compilations (N>, NO, N0, Participratique, 20.17-2018, ann6e…)."""
    if not text:
        return None
    raw = str(text).strip()
    # Accent stripping keeps the character count of the folded text aligned
    # only approximately, so work on the folded copy throughout.
    folded = strip_accents(raw).replace("º", "°")
    m = _ORIGIN_HEAD.search(folded)
    if not m:
        return None
    digits = m.group(1)
    number = int(digits)
    rest = folded[m.end():]
    # The line ends at the first newline: anything after is the question.
    rest_line = rest.split("\n", 1)[0]

    section = normalize_section(rest_line)
    period = normalize_period(rest_line)
    ym = _YEAR_PAIR.search(rest_line) or _YEAR_ONE.search(rest_line)
    year_raw = ym.group(0) if ym else None
    year = parse_year(year_raw) if year_raw else None

    suspect = False
    # '401 Rattrapage' — a missing comma read as '1': 3 digits glued to the
    # next word with no comma, and the 2-digit prefix is a plausible number.
    after = rest_line.lstrip()
    if len(digits.lstrip("0")) == 3 and not after.startswith(","):
        suspect = True
    # '2s.-se 02' — a digit glued to a letter: the number itself is misread.
    if rest_line[:1].isalpha():
        suspect = True
    if number > EXAM_NUMBER_MAX:
        suspect = True
    if number == 0:
        suspect = True

    return {
        "number": number,
        "period": period,
        "section": section,
        "year": year,
        "year_raw": year_raw,
        "suspect": suspect,
        "raw": raw.split("\n", 1)[0].strip(),
    }


def parse_real_origin(text: Optional[str]) -> Optional[Dict]:
    """parse_origin_line, but only for a genuine origin line: it must name a
    session, a year or a part. A bare question stem such as 'Question N° 3 :'
    of a normal exam is NOT an origin line."""
    parsed = parse_origin_line(text)
    if parsed and (parsed["period"] or parsed["year"] or parsed["section"]):
        return parsed
    return None


def find_origin_lines(page_text: Optional[str]) -> List[Dict]:
    """All genuine origin lines of one page, in reading order."""
    out = []
    for line in (page_text or "").splitlines():
        if not re.search(r"question", line, re.IGNORECASE):
            continue
        parsed = parse_real_origin(line)
        if parsed:
            out.append(parsed)
    return out


# ── document mode (§4.1) ───────────────────────────────────────────────────

def detect_document_mode(page_texts: Dict[int, str]) -> str:
    """'compilation' when >= 30 % of non-empty pages carry origin lines."""
    pages = [t for t in (page_texts or {}).values() if t and t.strip()]
    if not pages:
        return MODE_SINGLE
    with_lines = 0
    total_lines = 0
    for t in pages:
        n = len([o for o in find_origin_lines(t) if o["year"] or o["period"]])
        total_lines += n
        if n:
            with_lines += 1
    if total_lines >= COMPILATION_MIN_LINES and with_lines / len(pages) >= COMPILATION_PAGE_RATIO:
        return MODE_COMPILATION
    return MODE_SINGLE


def resolve_mode(requested: Optional[str], page_texts: Dict[int, str]) -> str:
    r = (requested or MODE_AUTO).strip().lower()
    if r in (MODE_SINGLE, MODE_COMPILATION):
        return r
    return detect_document_mode(page_texts)


# ── numbering scopes (§4.2) ────────────────────────────────────────────────

def normalize_scope_header(header: Optional[str], mode: str) -> Optional[str]:
    """A section header that starts a new numbering scope, or None.

    Single-paper exams: only part/session headers count (pratique, théorique,
    rattrapage, session normale) — module sub-titles where numbering continues
    are ignored. Compilations: any non-empty chapter title starts a scope."""
    if not header or not str(header).strip():
        return None
    h = str(header).strip()
    if h.startswith("<") or _fold(h) in ("null", "none", "n/a"):
        return None          # prompt placeholder echoed back by the model
    if parse_real_origin(h):
        return None          # an origin line is never a section header
    sec = normalize_section(h)
    if sec:
        return sec
    f = _fold(h)
    if "rattrap" in f:
        return "Rattrapage"
    if re.search(r"session\s*normale", f):
        return "Session normale"
    if mode == MODE_COMPILATION:
        return re.sub(r"\s+", " ", h)[:80]
    return None


def _uid_position(q: Dict) -> Optional[int]:
    uid = str(q.get("uid") or "")
    m = re.fullmatch(r"-?\d+_-?\d+_(\d+)", uid)
    return int(m.group(1)) if m else None


def reading_order_key(q: Dict) -> Tuple:
    """(page, position-in-response) — the order the QCMs were read in.

    Falls back to the printed number for legacy uids. Sorting by bare number
    would put a pratique Q1 before the theory Q40 printed above it."""
    page = extract_int(q.get("page")) or 0
    pos = _uid_position(q)
    num = extract_int(q.get("number") if q.get("number") is not None else q.get("Num")) or 0
    return (page, 0 if pos is not None else 1, pos if pos is not None else num)


def add_flag(q: Dict, flag: str) -> None:
    flags = q.get("review_flags")
    if not isinstance(flags, list):
        flags = [] if not flags else [str(flags)]
    if flag not in flags:
        flags.append(flag)
    q["review_flags"] = flags


def assign_scopes(qcms: List[Dict], mode: str, restart_gap: int = 5) -> None:
    """Write `scope` on every QCM (input must be in reading order)."""
    current: Optional[str] = None
    part = 1
    prev: Optional[int] = None
    seen: set = set()
    for q in qcms:
        header = normalize_scope_header(q.get("section_header"), mode)
        if header and header != current:
            current, prev, seen = header, None, set()
        n = extract_int(q.get("number"))
        if n and prev is not None and (n == 1 and prev > 1 or n < prev - restart_gap):
            part += 1
            base = current if current and not current.startswith("part-") else None
            current = f"{base} part-{part}" if base else f"part-{part}"
            prev, seen = None, set()
            add_flag(q, "scope_inferred")
        q["scope"] = current or DEFAULT_SCOPE
        if n:
            if n in seen:
                add_flag(q, "duplicate_in_scope")
            seen.add(n)
            prev = n


def scope_period_section(scope: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Paper period / section implied by a single-paper scope label."""
    if not scope or scope == DEFAULT_SCOPE:
        return None, None
    return normalize_period(scope), normalize_section(scope)


# ── origin-line leak into proposition E (P4) ───────────────────────────────

_LEAK = re.compile(r"[•·.\s]*qu\S?stion\s*n\s*(?:[°ºo0>.:*~\"'`^]{1,2}\s*)?\d{1,3}.*$",
                   re.IGNORECASE | re.DOTALL)


def strip_origin_leak(q: Dict) -> Optional[str]:
    """Remove an origin line glued to the end of the last proposition.

    Returns the removed origin line (it belongs to the NEXT question)."""
    props = q.get("propositions")
    if not isinstance(props, dict) or not props:
        return None
    last_key = sorted(props.keys())[-1]
    val = props.get(last_key)
    if not isinstance(val, str):
        return None
    folded = strip_accents(val)
    m = _LEAK.search(folded)
    if not m or not parse_real_origin(folded[m.start():]):
        return None
    # Accent stripping can change length only for decomposed input; cut on the
    # same index of the original when lengths agree, else on the folded copy.
    cut = m.start() if len(folded) == len(val) else None
    kept = (val[:cut] if cut is not None else folded[:m.start()]).rstrip(" •·\n\t")
    leaked = (val[cut:] if cut is not None else folded[m.start():]).strip(" •·\n\t")
    props[last_key] = kept
    return leaked


# ── Step 2 post-pass (§4, §5.4) ────────────────────────────────────────────

def _paper_from_origin(parsed: Dict, origin: str = "origin_line") -> Dict:
    return {
        "source": None,
        "period": parsed.get("period"),
        "year": parsed.get("year"),
        "number": parsed.get("number"),
        "section": parsed.get("section"),
        "from": origin,
        "confidence": "suspect" if parsed.get("suspect") else "ok",
    }


def _same_origin(a: Dict, b: Dict) -> bool:
    return (a.get("number") == b.get("number") and a.get("year") == b.get("year")
            and a.get("period") == b.get("period"))


def annotate_qcms(qcms: List[Dict], page_texts: Dict[int, str], mode: str) -> Dict:
    """Write scope / papers / review_flags / exam_mode on every QCM (in place).

    Idempotent: re-running recomputes everything from origin_raw + page text.
    Returns small stats for the log."""
    ordered = sorted(qcms, key=reading_order_key)

    # P4 — an origin line glued to proposition E belongs to the next question.
    for i, q in enumerate(ordered):
        leaked = strip_origin_leak(q)
        if leaked and i + 1 < len(ordered) and not ordered[i + 1].get("origin_raw"):
            ordered[i + 1]["origin_raw"] = leaked

    for q in ordered:
        q["review_flags"] = [f for f in (q.get("review_flags") or [])
                             if f in ("cas_chain_broken", "cas_chain_uncertain",
                                      "cas_chain_extended", "correction_ambiguous")]
        q["exam_mode"] = mode
        q.pop("origin_line", None)

    assign_scopes(ordered, mode)

    # Per-page alignment of the LLM's origin_raw with the page's own lines.
    by_page: Dict[int, List[Dict]] = {}
    for q in ordered:
        by_page.setdefault(extract_int(q.get("page")) or 0, []).append(q)

    stats = {"origin_line": 0, "aligned": 0, "mismatch": 0, "missing": 0, "suspect": 0}
    for page, page_qcms in by_page.items():
        lines = [o for o in find_origin_lines(page_texts.get(page, "")) if o]
        llm = [parse_real_origin(q.get("origin_raw")) for q in page_qcms]
        aligned = len(lines) == len(page_qcms) and len(lines) > 0
        for idx, q in enumerate(page_qcms):
            parsed = llm[idx]
            source = "origin_line"
            if aligned:
                line = lines[idx]
                if parsed is None:
                    parsed, source = line, "origin_line_aligned"
                    stats["aligned"] += 1
                elif not _same_origin(parsed, line):
                    add_flag(q, "origin_mismatch")
                    parsed = line
                    stats["mismatch"] += 1
            if parsed:
                paper = _paper_from_origin(parsed, source)
                if not paper["section"]:
                    paper["section"] = scope_period_section(q.get("scope"))[1] \
                        if mode == MODE_SINGLE else None
                q["papers"] = [paper]
                # origin_raw stays what the LLM returned (input of a re-run);
                # origin_line is the line actually used (review column).
                q["origin_line"] = parsed.get("raw")
                stats["origin_line"] += 1
                if paper["confidence"] == "suspect":
                    add_flag(q, "exam_number_suspect")
                    stats["suspect"] += 1
                if paper["year"] is None:
                    add_flag(q, "missing_year")
            elif mode == MODE_COMPILATION:
                q["papers"] = [{"source": None, "period": None, "year": None,
                                "number": None, "section": None,
                                "from": "missing", "confidence": "missing"}]
                add_flag(q, "exam_number_missing")
                stats["missing"] += 1
            else:
                period, section = scope_period_section(q.get("scope"))
                n = extract_int(q.get("number"))
                q["papers"] = [{"source": None, "period": period, "year": None,
                                "number": n if n else None, "section": section,
                                "from": "document", "confidence": "ok"}]

    # §5.3 — the same paper number on two different questions of this document.
    seen: Dict[Tuple, Dict] = {}
    for q in ordered:
        p = (q.get("papers") or [{}])[0]
        if p.get("from", "").startswith("origin_line") and p.get("number"):
            key = (p.get("period"), p.get("year"), p.get("section"), p.get("number"))
            if key in seen:
                add_flag(q, "exam_number_duplicate")
                add_flag(seen[key], "exam_number_duplicate")
            else:
                seen[key] = q
    for q in ordered:
        if not q.get("review_flags"):
            q["review_flags"] = []
    return stats


# ── Step 3: final paper fields, Tag, Exams (§4.4, D2-D6) ───────────────────

def find_period_in_text(text: Optional[str]) -> Optional[str]:
    """Session named in a single-paper document header (first lines only)."""
    head = _fold((text or "")[:1500])
    m = re.search(r"\bemd\s*(\d)\b", head)
    if m:
        return f"EMD{m.group(1)}"
    if "rattrapage" in head:
        return "Rattrapage"
    if re.search(r"session\s*normale", head):
        return "Session normale"
    if "synthese" in head:
        return "Synthèse"
    return None


def format_exams(papers: Iterable[Dict]) -> str:
    """MBset `Exams` cell: 'Source · Period Year · N°n | …' (review file only)."""
    parts = []
    for p in papers or []:
        if not p or not p.get("year"):
            continue          # MBset refuses a part without a year
        bits = []
        if p.get("source"):
            bits.append(str(p["source"]))
        label = session_label(p.get("period"), p.get("section"))
        bits.append(f"{label} {p['year']}" if label else str(p["year"]))
        if p.get("number"):
            bits.append(f"N°{int(p['number'])}")
        parts.append(" · ".join(bits))
    return " | ".join(parts)


def finalize_papers(q: Dict, *, doc_period: Optional[str] = None,
                    default_period: Optional[str] = None,
                    default_source: Optional[str] = None,
                    default_year=None) -> None:
    """Fill paper source/year/period by precedence and derive the export fields.

    Origin line > section header > document header > config. Writes:
    `papers`, `year` (start year, str), `Number`, `session`, `tag`, `Exams`.
    Never invents a year: missing -> flag `missing_year`."""
    papers = q.get("papers")
    if not isinstance(papers, list) or not papers:
        n = extract_int(q.get("number") if q.get("number") is not None else q.get("Num"))
        papers = [{"source": None, "period": None, "year": None,
                   "number": n if n else None, "section": None,
                   "from": "document", "confidence": "ok"}]
    qcm_year = parse_year(q.get("year")) or parse_year(default_year)
    source = q.get("source") or default_source
    if source and not q.get("source"):
        q["source"] = str(source)
    for p in papers:
        if not p.get("source") and source:
            p["source"] = str(source)
        if not p.get("year"):
            p["year"] = qcm_year
        if not p.get("period") and not str(p.get("from", "")).startswith("origin_line"):
            p["period"] = doc_period or default_period
    q["papers"] = papers
    first = papers[0]

    if first.get("year"):
        q["year"] = str(first["year"])        # origin-line year wins (compilations)
    elif qcm_year:
        q["year"] = str(qcm_year)
    else:
        q["year"] = None
        add_flag(q, "missing_year")

    q["Number"] = first.get("number")
    label = session_label(first.get("period"), first.get("section"))
    q["session"] = label

    tag: List[str] = []
    for part in (q.get("source"), q.get("year"), label):
        if part and str(part) not in tag:
            tag.append(str(part))
    q["tag"] = tag
    q["Exams"] = format_exams(papers)


# ── Step 3: clinical-case chain rule (D7, §11.2) ───────────────────────────

def _paper(q: Dict) -> Dict:
    p = (q.get("papers") or [{}])[0] or {}
    return p


def _chain(a: Dict, b: Dict) -> Optional[bool]:
    """True: b continues a's case. False: it does not. None: cannot tell."""
    pa, pb = _paper(a), _paper(b)
    if not str(pa.get("from", "")).startswith("origin_line") or \
       not str(pb.get("from", "")).startswith("origin_line"):
        return None
    same_paper = (pa.get("year") == pb.get("year")
                  and session_label(pa.get("period"), pa.get("section"))
                  == session_label(pb.get("period"), pb.get("section")))
    if not same_paper:
        return False
    na, nb = pa.get("number"), pb.get("number")
    unsure = (not na or not nb or pa.get("confidence") != "ok"
              or pb.get("confidence") != "ok")
    if not unsure:
        return nb == na + 1
    da, db = extract_int(a.get("number")), extract_int(b.get("number"))
    return None if (da and db and db == da + 1) else False


def enforce_cas_chain(qcms: List[Dict]) -> Dict:
    """Apply D7 to a compilation (input in reading order, modified in place).

    - A question keeps the active case text only while it continues the chain:
      same paper (session + year) and original number = previous + 1.
    - The first breaking question closes the case and loses the text.
    - A following question the LLM left without a case, but that continues the
      chain, receives the identical case text (flag `cas_chain_extended`).
    - Unreadable numbers in the middle: kept only when the document positions
      are consecutive (flag `cas_chain_uncertain`).
    Only questions whose papers come from origin lines take part."""
    stats = {"kept": 0, "removed": 0, "extended": 0, "uncertain": 0}
    active: Optional[str] = None
    last: Optional[Dict] = None
    closed: set = set()
    for q in qcms:
        cas = q.get("cas") or None
        if cas and cas in closed and cas != active:
            q["cas"] = None
            add_flag(q, "cas_chain_broken")
            stats["removed"] += 1
            continue
        if cas and cas == active and last is not None:
            ok = _chain(last, q)
            if ok is False:
                q["cas"] = None
                add_flag(q, "cas_chain_broken")
                closed.add(active)
                active, last = None, None
                stats["removed"] += 1
                continue
            if ok is None:
                add_flag(q, "cas_chain_uncertain")
                stats["uncertain"] += 1
            last = q
            stats["kept"] += 1
            continue
        if cas:
            if active and active != cas:
                closed.add(active)
            active, last = cas, q
            continue
        # no case text on this question
        if active and last is not None and _chain(last, q) is True:
            q["cas"] = active
            add_flag(q, "cas_chain_extended")
            last = q
            stats["extended"] += 1
            continue
        if active:
            closed.add(active)
        active, last = None, None
    return stats


# ── Step 6: scoped correction matching (P6) ────────────────────────────────

def qcm_scope(q: Dict) -> str:
    return str(q.get("scope") or DEFAULT_SCOPE)


def qcm_number_str(q: Dict) -> str:
    n = q.get("Num") if q.get("Num") not in (None, "") else q.get("number")
    n = extract_int(n)
    return str(n) if n is not None else ""


def parse_correction_key(key) -> Tuple[Optional[str], Optional[str]]:
    """'12' -> (None, '12'); 'Pratique:12' / 'Rattrapage|3' -> (label, '12')."""
    s = str(key).strip()
    m = re.fullmatch(r"(.+?)\s*[:|#]\s*(\d{1,3})", s)
    if m and not m.group(1).strip().isdigit():
        return m.group(1).strip(), str(int(m.group(2)))
    if s.isdigit():
        return None, str(int(s))
    return None, None


def scope_matches(scope: str, label: str) -> bool:
    fs, fl = _fold(scope), _fold(label)
    if not fs or not fl:
        return False
    if fl in fs or fs in fl:
        return True
    for word in ("pratique", "theorique", "rattrapage", "normale"):
        if word in fs and word in fl:
            return True
    return False


def has_multiple_scopes(qcms: List[Dict]) -> bool:
    return len({qcm_scope(q) for q in qcms}) > 1


def apply_scoped_corrections(qcms: List[Dict], entries: List[Dict],
                             field: str = "Correct") -> Dict:
    """Apply correction entries [{num, label, answer, page}] without letting a
    bare number hit two numbering scopes.

    - One scope holds the number -> applied (today's behaviour).
    - A labelled entry ('Pratique:1') -> applied inside the matching scope.
    - Unlabelled, several scopes: tables are matched to scopes in document
      order when there are as many tables as scopes; otherwise the scope of
      the nearest question printed before the table's page; otherwise not
      applied and flagged `correction_ambiguous`."""
    by_num: Dict[str, List[Dict]] = {}
    for q in qcms:
        k = qcm_number_str(q)
        if k:
            by_num.setdefault(k, []).append(q)

    scope_first_page: Dict[str, int] = {}
    for q in qcms:
        s = qcm_scope(q)
        p = extract_int(q.get("page") or q.get("Page")) or 0
        scope_first_page[s] = min(scope_first_page.get(s, p), p)

    stats = {"applied": 0, "ambiguous": 0, "unmatched": 0}
    # Unlabelled entries grouped per number, in page order, for the zip rule.
    grouped: Dict[str, List[Dict]] = {}
    for e in entries:
        if not e.get("label"):
            grouped.setdefault(e["num"], []).append(e)

    def put(targets: List[Dict], answer: str) -> None:
        for t in targets:
            t[field] = answer
            stats["applied"] += 1

    for e in entries:
        cands = by_num.get(e["num"], [])
        if not cands:
            stats["unmatched"] += 1
            continue
        scopes = sorted({qcm_scope(c) for c in cands}, key=lambda s: scope_first_page.get(s, 0))
        if e.get("label"):
            m = [c for c in cands if scope_matches(qcm_scope(c), e["label"])]
            if m:
                put(m, e["answer"])
            elif len(scopes) == 1:
                put(cands, e["answer"])
            else:
                for c in cands:
                    add_flag(c, "correction_ambiguous")
                stats["ambiguous"] += 1
            continue
        if len(scopes) == 1:
            put(cands, e["answer"])
            continue
        same_num = grouped.get(e["num"], [])
        pages = [x.get("page") for x in same_num]
        if len(same_num) == len(scopes) and all(p is not None for p in pages) \
                and len(set(pages)) == len(pages):
            order = sorted(same_num, key=lambda x: x["page"])
            target_scope = scopes[order.index(e)]
            put([c for c in cands if qcm_scope(c) == target_scope], e["answer"])
            continue
        page = e.get("page")
        if page is not None:
            before = [c for c in cands if (extract_int(c.get("page") or c.get("Page")) or 0) <= page]
            if before:
                nearest = max(before, key=lambda c: extract_int(c.get("page") or c.get("Page")) or 0)
                put([c for c in cands if qcm_scope(c) == qcm_scope(nearest)], e["answer"])
                continue
        for c in cands:
            add_flag(c, "correction_ambiguous")
        stats["ambiguous"] += 1
    return stats


def entries_from_map(correction_map: Dict, page: Optional[int] = None) -> List[Dict]:
    out = []
    for k, v in (correction_map or {}).items():
        label, num = parse_correction_key(k)
        if num is None:
            continue
        out.append({"num": num, "label": label, "answer": str(v), "page": page})
    return out


# ── Sheets round-trip: Exams / Number edited in the review sheet (§9.5) ────

_EXAMS_NUM = re.compile(r"^\s*(?:N\s*[°º]|No\.?)\s*(\d{1,3})\s*$", re.IGNORECASE)


def parse_exams(cell: Optional[str]) -> List[Dict]:
    """Inverse of format_exams: 'Src · Sec 01 Pratique 2017 · N°2 | …' -> papers.

    A part without a 4-digit year is skipped (MBset refuses it too)."""
    papers: List[Dict] = []
    for part in str(cell or "").split("|"):
        bits = [b.strip() for b in part.split("·") if b.strip()]
        if not bits:
            continue
        number = None
        if _EXAMS_NUM.match(bits[-1]):
            number = int(_EXAMS_NUM.match(bits[-1]).group(1))
            bits = bits[:-1]
        if not bits:
            continue
        m = re.search(r"((?:19|20)\d{2})\s*$", bits[-1])
        if not m:
            continue
        year = int(m.group(1))
        label = bits[-1][:m.start()].strip() or None
        source = " · ".join(bits[:-1]) or None
        section = None
        period = label
        if label and re.search(r"(?i)\bpratique$", label):
            section = "Pratique"
            period = re.sub(r"(?i)\s*\bpratique$", "", label).strip() or None
        papers.append({"source": source, "period": period, "year": year,
                       "number": number, "section": section,
                       "from": "sheet", "confidence": "ok"})
    return papers


def apply_sheet_paper_edits(target: Dict, old_exams, old_number) -> bool:
    """After a sheet row was merged into `target`: when the user changed the
    `Exams` cell, rebuild `papers` from it; when only `Number` changed, update
    the first paper's number. Returns True when papers changed."""
    exams = target.get("Exams")
    if isinstance(exams, str) and exams.strip() and exams.strip() != str(old_exams or "").strip():
        papers = parse_exams(exams)
        if papers:
            target["papers"] = papers
            target["Number"] = papers[0].get("number")
            target["session"] = session_label(papers[0].get("period"), papers[0].get("section"))
            if papers[0].get("year"):
                target["year"] = str(papers[0]["year"])
            return True
    new_number = extract_int(target.get("Number"))
    if new_number is not None and str(new_number) != str(extract_int(old_number)):
        target["Number"] = new_number
        papers = target.get("papers")
        if isinstance(papers, list) and papers and isinstance(papers[0], dict):
            papers[0]["number"] = new_number
            papers[0]["from"] = "sheet"
        target["Exams"] = format_exams(target.get("papers") or [])
        return True
    return False


# ── Step 8: union of the papers of two matched questions (P10) ─────────────

def _same_paper(a: Dict, b: Dict) -> bool:
    if a.get("year") != b.get("year"):
        return False
    if session_label(a.get("period"), a.get("section")) != session_label(b.get("period"), b.get("section")):
        return False
    sa, sb = a.get("source"), b.get("source")
    return not sa or not sb or _fold(sa) == _fold(sb)


def union_papers(ref: List[Dict], src: List[Dict]) -> Tuple[List[Dict], List[str]]:
    """Reference papers + the source's papers not already there.

    Same paper with a different number -> keep the reference number, report it."""
    merged = [dict(p) for p in (ref or []) if isinstance(p, dict)]
    conflicts: List[str] = []
    for p in src or []:
        if not isinstance(p, dict) or not p.get("year"):
            continue
        hit = next((m for m in merged if _same_paper(m, p)), None)
        if hit is None:
            merged.append(dict(p))
            continue
        if not hit.get("source") and p.get("source"):
            hit["source"] = p["source"]
        if hit.get("number") and p.get("number") and hit["number"] != p["number"]:
            conflicts.append(f"{format_exams([hit])} vs N°{p['number']}")
        elif not hit.get("number") and p.get("number"):
            hit["number"] = p["number"]
    return merged, conflicts
