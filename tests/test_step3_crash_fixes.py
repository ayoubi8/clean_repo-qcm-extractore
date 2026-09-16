"""Fix tests for the ratrapage_gyneco_2024-2025 crash report.

FIX-1  _process_qcms sidecar immunity: correction_pages.json (and other
       sidecar/audit files sharing step2_qcm/accepted/) never enter the
       batch loop; a dict-root payload can no longer crash the cascade
       ('str' object has no attribute 'get').
FIX-2  _detect_cc_sequential_page treats BLANK/null model responses as
       failures -> the fallback model gets its try before the page forfeits;
       no 'NoneType' object has no attribute 'strip'.
FIX-3  Parser failure (no JSON array) retries ONCE with the fallback model;
       at most 2 calls per page; both-fail -> {} (legacy degradation).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from modules.utils.cost_tracker import CostTracker
from modules.step3_metadata import Step3Metadata

CASE = "CAS CLINIQUE 1\r\nSalma, 56 ans, sous Amiodarone."
PAGE_TXT = "Q4. Question de test?\nA. prop\n"


def _make():
    return Step3Metadata(CostTracker())


def _q(uid, number, text="Q ?", page=1):
    return {"uid": uid, "page": page, "number": number, "text": text,
            "propositions": {"a": "P1", "b": "P2"}}


def _status_response(entries):
    return {"content": json.dumps([{"number": e.get("number"),
                                    "status": e.get("status"),
                                    "cas_label": e.get("cas_label"),
                                    "cas_text": e.get("cas_text")}
                                   for e in entries], ensure_ascii=False),
            "usage": {"prompt_tokens": 5, "completion_tokens": 2}, "cost": 0.0}


# â”€â”€ FIX-1 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _test_sidecar_files_never_crash():
    print("\n--- FIX-1: sidecar + malformed payloads skipped, cascade completes ---")
    sm = _make()
    merged = [_q("1_1_0", 1), _q("1_2_1", 2)]
    calls = []

    def side_effect(prompt, model=None, max_tokens=None, **kw):
        calls.append(prompt)
        if "Fatima" in prompt:
            return {"content": json.dumps([
                {"number": 1, "status": "new_case", "cas_label": "CAS CLINIQUE 1",
                 "cas_text": "Fatima, 29 ans..."},
                {"number": 2, "status": "continues"}]), "usage": {}, "cost": 0.0}
        return {"content": json.dumps([{"number": 1, "status": "unrelated"}]),
                "usage": {}, "cost": 0.0}

    tmp = Path(tempfile.mkdtemp())
    try:
        s1 = tmp / "step1_extraction" / "accepted"; s1.mkdir(parents=True)
        (s1 / "page_1.txt").write_text("Fatima: cas de test.\nQ1...\n", encoding="utf-8")
        s2 = tmp / "step2_qcm" / "accepted"; s2.mkdir(parents=True)
        (s2 / "all_qcms.json").write_text(json.dumps(merged, ensure_ascii=False),
                                          encoding="utf-8")
        # the Step-2 sidecar that crashed the live run
        sidecar = s2 / "correction_pages.json"
        sidecar_before = {"correction_pages": [12]}
        sidecar.write_text(json.dumps(sidecar_before), encoding="utf-8")
        # plus a corrupted/non-list payload for defense-in-depth
        (s2 / "broken_payload.json").write_text('{"oops": 1}', encoding="utf-8")

        with patch.object(sm, "client") as mc:
            mc.generate_completion.side_effect = side_effect
            sm.run(step2_dir=str(s2), step1_dir=str(s1), auto_mode=True,
                   config={"year": {"strategy": "skip"},
                           "clinical_case": {"strategy": "per_group"}})
        # exactly one page-callable file (nothing for correction_pages/broken)
        assert len(calls) == 1, f"sidecars must not be scanned: {len(calls)} calls"
        saved = json.loads((Path(ROOT) / "output" / "step3_metadata" / "accepted" / "all_qcms.json")
                           .read_text(encoding="utf-8"))
        assert saved[1]["cas"].startswith("CAS CLINIQUE 1\r\nFatima"), saved[1]
        # sidecar byte-identical (Step 6 seed untouched)
        assert json.loads(sidecar.read_text(encoding="utf-8")) == sidecar_before
        print("OK sidecar skipped, payload guard skips broken file, no crash.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(os.path.join(ROOT, "output", "step3_metadata"), ignore_errors=True)


# â”€â”€ FIX-2: blank/None content falls back â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

PAGE_TEXT = "Q4. Test?\n"


def _ok_map(entries=None):
    entries = entries or [{"number": 4, "status": "new_case", "cas_label": "CAS CLINIQUE 1",
                           "cas_text": "Salma..."}]
    return {"content": json.dumps(entries), "usage": {}, "cost": 0.0}


class _ScriptedHolder:
    """Scripted OpenRouterClient stand-in: records every generate_completion
    call (models list) and consumes a scripted plan of responses/Exceptions.
    proxy() returns a MagicMock whose generate_completion routes to it."""
    def __init__(self, plan):
        self.plan = list(plan)
        self.calls = []
        proxy = MagicMock()
        proxy.generate_completion.side_effect = self
        self._proxy = proxy
    def proxy(self):
        return self._proxy
    def __call__(self, prompt, model=None, max_tokens=None, **kw):
        self.calls.append(model)
        r = self.plan.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _scripted(plan):
    return _ScriptedHolder(plan)


def _test_blank_primary_falls_back():
    print("\n--- FIX-2: content=None primary -> fallback used, no strip crash ---")
    sm = _make()
    cli = _scripted([
        {"content": None, "usage": {}, "cost": 0.0},
        _ok_map(),
    ])
    with patch.object(sm, "client", cli.proxy()):
        out = sm._detect_cc_sequential_page(PAGE_TEXT, [4])
    assert out[4]["status"] == "new_case", out
    assert len(cli.calls) == 2, cli.calls
    print("OK null-content primary never crashes; fallback supplies verdict.")


def _test_blank_both_models_returns_legacy():
    print("\n--- FIX-2: both blank -> {} (legacy), exactly 2 calls ---")
    sm = _make()
    cli = _scripted([
        {"content": None, "usage": {}, "cost": 0.0},
        {"content": "   \n  ", "usage": {}, "cost": 0.0},
    ])
    with patch.object(sm, "client", cli.proxy()):
        out = sm._detect_cc_sequential_page("some page", [7])
    assert out == {}, out
    assert len(cli.calls) == 2, cli.calls
    print("OK blank primary + blank fallback -> {} without any strip crash.")


# â”€â”€ FIX-3: parse failure retries once via fallback â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _test_parse_failure_retries_once():
    print("\n--- FIX-3: prose primary -> fallback parse success (2 calls max) ---")
    sm = _make()
    cli = _scripted([
        {"content": "des mots sans json du tout", "usage": {}, "cost": 0.0},
        _ok_map(),
    ])
    with patch.object(sm, "client", cli.proxy()):
        out = sm._detect_cc_sequential_page(PAGE_TEXT, [4])
    assert out[4]["status"] == "new_case", out
    assert len(cli.calls) == 2, cli.calls
    print("OK unparsable primary retried once with fallback; verdict applied.")

    # and after BOTH attempts unparsable -> {} and STOP (no 3rd call)
    cli2 = _scripted([
        {"content": "pas de json", "usage": {}, "cost": 0.0},
        {"content": "toujours rien", "usage": {}, "cost": 0.0},
    ])
    with patch.object(sm, "client", cli2.proxy()):
        out2 = sm._detect_cc_sequential_page(PAGE_TEXT, [4])
    assert out2 == {} and len(cli2.calls) == 2, (out2, len(cli2.calls))
    print("OK 2-call ceiling enforced on parse failures.")


def _test_healthy_page_single_call():
    print("\n--- FIX-2/3 guardrail: healthy page still costs exactly 1 call ---")
    sm = _make()
    cli = _scripted([_ok_map()])
    with patch.object(sm, "client", cli.proxy()):
        out = sm._detect_cc_sequential_page(PAGE_TEXT, [4])
    assert out[4]["status"] == "new_case" and len(cli.calls) == 1
    print("OK healthy page: 1 call, unchanged behavior.")


def _run_all():
    _test_sidecar_files_never_crash()
    _test_blank_primary_falls_back()
    _test_blank_both_models_returns_legacy()
    _test_parse_failure_retries_once()
    _test_healthy_page_single_call()
    print("\n" + "=" * 60)
    print("ALL STEP-3 CRASH-FIX TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()


