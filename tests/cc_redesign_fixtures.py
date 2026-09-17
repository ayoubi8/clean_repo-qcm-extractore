"""Phase 0 fixtures — frozen corpus for the Clinical Case Redesign v2 (phased).

Shared across all cc_redesign phase tests (0..7). Test-only; imported by
tests/test_cc_redesign_phase*.py files. No production code in here.

Corpus covers every Part-B mind-map situation the phases build against:
page texts (Step 1 raw format), QCM dicts (Step 2 output shape), and
mocked LLM response builders for both CURRENT prompt/answer shapes and the
future 5-status shape (used from Phase 1 on).
"""
import json
from unittest.mock import MagicMock, AsyncMock

P1_TEXT = """CAS CLINIQUE 1 :
3/ Salma, âgée de 56 ans, traitée depuis 3 ans par Amiodarone, consulte pour
un ictère fébrile. La biologie objective une cytolyse à 12N et une
cholestase à 6N.
Q4. Parmi les propositions suivantes, quelle la plus probable ?
A. Hepatite medicamenteuse
B. Hepatite virale
"""

P1_QCMS = [
    {"uid": "3_3_0", "page": 3, "number": 3},
    {"uid": "3_4_1", "page": 3, "number": 4,
     "text": "Parmi les propositions suivantes, quelle la plus probable ?"},
]

# Narrative WITHOUT any 'CAS CLINIQUE' header (most common situation, part B 1.2)
P5_TEXT_UNMARKED = """5/ Rachid, 34 ans, dialyse depuis 5 ans sur nephropathie
diabetique, presente uneFi plus haut une pression. Un bilan retrouve des
crises hypertensif fi viele !
Q12. Conduite face a richter un faibles
A. Augmenter le NA destinee
"""

P5_QCMS_UNMARKED = [
    {"uid": "12_5_0", "page": 12, "number": 5},
    {"uid": "12_12_1", "page": 12, "number": 12,
     "text": "Conduite face a richter un faibles"},
]

# FUSED-NARRATIVE case (the confirmed prod failure: patient content inside
# the QCM's own text block, no separator — Mind map 1.3 / plan 5.3)
FUSED_PAGE_TEXT = """Q22. Madame Benali, 62 ans, diabetique type 2 despuis 12 ans,
traitere par metformine, presente depuis 5 jours des erythemateux
marginés avec fever 38deg et antigens positive.
Parmi les propositions suivantes, la quel est vraie ?
A. Desir Enoch papuleuse
B. Eruption maculopapuleuse"""

FUSED_QCM = {"uid": "30_22_0", "page": 30, "number": 22,
             "text": "Madame Benali, 62 ans... Parmi les propositions suivantes, la quel est vraie ?"}

# Page with NO case at all (mind map 2.1)
NO_CASE_PAGE_TEXT = """Q7. Le-ipa neurons defendant!
A. C's a group of corticoïdes
B. Matellites développés"""

NO_CASE_QCMS = [
    {"uid": "44_7_0", "page": 44, "number": 7, "text": "Le-ipa neurons defendant!"},
]

# QCM numbers repeating across sections (mind map 3.2) — two pages each with Q1
SEC_A_TEXT = """Q1. Symptomes de la gravite
A. Prop 1
B. Prop 2
"""
SEC_B_TEXT = """CAS CLINIQUE 1 :
1/ Fatima, 29 ans, première grossesse 8 SA...
Q1. Complication la plus probable
A. Pre-eclampsie
"""

SEC_A_QCM = [{"uid": "77_1_0", "page": 77, "number": 1, "text": "Symptomes de la gravite"}]
SEC_B_QCM = [{"uid": "78_1_0", "page": 78, "number": 1, "text": "Complication la plus probable"}]

# LLM response builders (current sequential shape: {number, cas_label, cas_text})
def resp(entries: list, raw: bool = False) -> dict:
    content = json.dumps(entries)
    return {"content": content, "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "cost": 0.0}

def sequential_page_response(trigger: dict = None, others: list = None) -> dict:
    """Build a page response in the CURRENT _detect_cc_sequential_page format.
    trigger: {"number": N, "cas_label": ..., "cas_text": ...} or None.
    others / all other numbers: listing under QCM NUMBERS with cas_text null.
    """
    entries = list(others or [])   # others: [{number, cas_label: None, cas_text: None}, ...]
    if trigger:
        entries.append(trigger)
    return resp_now(entries)

def resp_now(entries: list) -> dict:
    data = [{"number": e.get("number"),
             "cas_label": e.get("cas_label"),
             "cas_text": e.get("cas_text")}
            for e in entries]
    return {"content": json.dumps(data, ensure_ascii=False),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "cost": 0.0}

def empty_page_response(*nums) -> dict:
    return resp_now([{"number": n, "cas_label": None, "cas_text": None} for n in nums])

def status_response(entries: list, trailing: dict = None) -> dict:
    """5-status RESPONSE from `_detect_cc_sequential_page` (Phase 1+ contract).
    entries: [{"number": N, "status": "...", "cas_label": str|None,
               "cas_text": str|None}, ...]
    Extra keys on an entry (e.g. "claims_pending_case": True) pass through to
    the JSON verbatim. trailing: optional cross-page trailing narrative
    (H-fix): {"label": str, "text": str} — emitted as reserved `"_trailing"`."""
    data = []
    for e in entries:
        row = {"number": e.get("number"),
               "status": e.get("status"),
               "cas_label": e.get("cas_label"),
               "cas_text": e.get("cas_text")}
        for k, v in e.items():
            if k not in row:
                row[k] = v
        data.append(row)
    if trailing is not None:
        data.append({"_trailing": trailing})
    return {"content": json.dumps(data, ensure_ascii=False),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "cost": 0.0}

def mock_client(map_or_value):
    """MagicMock of OpenRouterClient with SYNC generate_completion for Step 3.
    map_or_value: str content returned on every generate_completion call."""
    c = MagicMock()
    c.generate_completion.return_value = {
        "content": map_or_value,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        "cost": 0.0,
    }
    return c

# ── CC Detection v4 anchor-schema builders ──────────────────────────
def anchor_response(entries: list) -> dict:
    """v4 anchor-schema page response: [{anchor_num, cas_label, cas_text,
    anchor_text_clean, note}] — exactly what the reasoning prompt asks for."""
    data = []
    for e in entries:
        row = {"anchor_num": e.get("anchor_num"),
               "cas_label": e.get("cas_label") or "CAS CLINIQUE",
               "cas_text": e.get("cas_text"),
               "anchor_text_clean": e.get("anchor_text_clean"),
               "note": e.get("note")}
        row = {k: v for k, v in row.items() if v is not None or
               k in ("anchor_num", "cas_text", "anchor_text_clean")}
        data.append(row)
    return {"content": json.dumps(data, ensure_ascii=False),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "cost": 0.0}

def anchor(num: int, cas_text: str, label: str = None,
           clean: str = None, note: str = "patient narrative") -> dict:
    return {"anchor_num": num, "cas_label": label, "cas_text": cas_text,
            "anchor_text_clean": clean, "note": note}

TRAILING_NARRATIVE = ("Un patient âgé de 75 ans, sans antécédents particuliers "
                      "présente des palpitations avec des sueurs, froideurs des "
                      "extrémités et tension artérielle imprenable. Voici son ECG")

def mock_client_async(respond):
    """For checker-style tests: generate_completion_async = respond(prompt)**async.
    respond: class or func. Used from Phase 4 onward."""
    c = MagicMock()
    c.generate_completion_async = AsyncMock(side_effect=respond)
    return c


def write_page_file(d, page_num: int, text: str):
    (d / f"page_{page_num}.txt").write_text(text, encoding="utf-8")
