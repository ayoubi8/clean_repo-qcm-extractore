"""PHASE 3 — `case_belonging_check` detection-side surface tests.

Acceptance from the phased plan, Phase 3:
- Population rules (Fix 2 contract): populated ONLY for real linkage decisions
  (new_case, continues, ends_here, uncertain); explicit unrelated gets NO entry.
- `cas` format/content byte-stable — audit note never leaks into `cas`.
- Build passthrough: `step5_builder._map_to_template` auto-propagates the note
  even when the template lacks the key (never silently lost), leaves Cas
  untouched, and does not invent an empty note.
- XLSX export: the note surfaces as its own column (order-after preference).
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from modules.step5_builder import Step5Builder
from modules.utils.xlsx_exporter import _build_columns
from modules.utils.cost_tracker import CostTracker
from modules.step3_metadata import Step3Metadata

NARR = "Salma, 56 ans, sous Amiodarone."
CAS = "CAS CLINIQUE 1\r\n" + NARR

def _info(st, label=None, text=None):
    return {"status": st, "label": label, "text": text}

def _make():
    return Step3Metadata(CostTracker())


def _test_population_rules():
    print("\n--- P3.1: audit-note population rules ---")
    sm = _make()
    upd, _c, _n, _b = sm._propagate_cas_clinique(
        [{"number": n} for n in (1, 2, 3, 4, 5, 6)],
        {1: {"status": "new_case", "label": "CAS CLINIQUE 1", "text": NARR},
         2: {"status": "continues", "label": None, "text": None},
         3: {"status": "ends_here", "label": None, "text": None},
         4: {"status": "uncertain", "label": None, "text": None},
         5: {"status": "unrelated", "label": None, "text": None},
         6: {"status": "new_case", "label": "CAS CLINIQUE 2", "text": NARR}},
        None)
    assert upd[0].get("case_belonging_check", "").startswith("new_case")
    assert upd[1].get("case_belonging_check", "").startswith("continues")
    assert upd[2].get("case_belonging_check", "").startswith("ends_here")
    assert upd[3].get("case_belonging_check", "").startswith("uncertain")
    assert "case_belonging_check" not in upd[4], "unrelated -> NO entry (Fix 2)"
    assert upd[5].get("case_belonging_check", "").startswith("new_case")
    print("OK populated for new_case/continues/ends_here/uncertain; unrelated clean.")


def _test_cas_format_byte_stable():
    print("\n--- P3.2: cas format byte-stable (label\\r\\nnarrative) ---")
    sm = _make()
    upd, _c, _n, _b = sm._propagate_cas_clinique(
        [{"number": 1}, {"number": 2}, {"number": 3}],
        {1: _info("new_case", "CAS CLINIQUE 1", NARR),
         2: _info("continues"), 3: _info("ends_here")}, None)
    assert upd[0]["cas"] == CAS, repr(upd[0]["cas"])
    assert upd[1]["cas"] == CAS, "audit note must NOT alter the cas content"
    assert "case_belonging_check" not in upd[0]["cas"]
    # cross-format robustness (legacy string input) — same byte result
    upd2, _c2, _n2, _b2 = sm._propagate_cas_clinique(
        [{"number": 9}], {9: CAS}, None)
    assert upd2[0]["cas"] == CAS and upd2[0]["cas"] == upd[0]["cas"]
    print("OK 'LABEL\\r\\nnarrative' invariant holds with audit notes present.")


def _test_build_passthrough():
    print("\n--- P3.3: build passthrough (step5 _map_to_template) ---")
    builder = Step5Builder(CostTracker())
    template = {"Num": None, "Text": None, "Cas": None}
    qcm = {"uid": "1", "number": 3, "cas": CAS,
           "case_belonging_check": "ends_here: case does not inform this question"}
    out1 = builder._map_to_template(dict(qcm), dict(template))
    assert out1["case_belonging_check"] == "ends_here: case does not inform this question", \
        "note must surface even without a template key (never silently lost)"
    assert out1["Cas"] == CAS, "Cas unchanged"

    # template that defines the key explicitly -> filled by the standard path
    template2 = {"Num": None, "case_belonging_check": None}
    out2 = builder._map_to_template(dict(qcm), dict(template2))
    assert out2["case_belonging_check"].startswith("ends_here:")

    # no note in data -> no invented key
    qcm_clean = {"uid": "2", "number": 4, "cas": CAS}
    out3 = builder._map_to_template(dict(qcm_clean), dict(template))
    assert "case_belonging_check" not in out3
    print("OK note passes through; Cas untouched; empty notes never invented.")


def _test_xlsx_column():
    print("\n--- P3.4: XLSX export column placement ---")
    qcms = [
        {"Num": 1, "Text": "t", "Cas": CAS,
         "case_belonging_check": "checker YES (0.9): uses reported diagnosis"},
        {"Num": 2, "Text": "t2"},
    ]
    cols = _build_columns(qcms)
    assert "case_belonging_check" in cols
    assert cols.index("case_belonging_check") == cols.index("Cas") + 1, cols
    # absent data -> no column
    assert "case_belonging_check" not in _build_columns([{"Num": 1}])
    print("OK column exists, ordered right after Cas, omitted when unused.")


def _run_all():
    _test_population_rules()
    _test_cas_format_byte_stable()
    _test_xlsx_column()
    _test_build_passthrough()
    print("\n" + "=" * 60)
    print("ALL PHASE 3 AUDIT SURFACE TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()
