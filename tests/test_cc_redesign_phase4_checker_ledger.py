"""PHASE 4 â€” Checker patient-fact ledger + Â§7 consistency + audit write-back.

Acceptance from the phased plan, Phase 4:
- `_verification_prompt` embeds the ledger block IFF provided, with the
  patient-facts-only guard text; no block otherwise.
- `_recheck_prompt` receives the SAME ledger (consistency rule: a QCM must
  never see different case evidence depending on prompt shape).
- `_parse_verdict` tolerates missing case_facts_used (None, no error) and
  captures it when present (backward-compatible exact dict otherwise).
- Ledger semantics (chain test): YES -> note appended, passed into the NEXT
  prompt; NO/unresolved/failed never write it; ledger resets per chain.
- Edit 7 audit write-back: every decision entry (kept/NO/provisional/Â§7/
  unresolved/boundary) carries a human-readable case_belonging_check, applied
  to the QCM dicts and persisted even without unlinks/scrubs.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from modules.utils.cost_tracker import CostTracker
from modules.clinical_case_checker import (
    run_clinical_case_checker,
    _verification_prompt,
    _recheck_prompt,
    _parse_verdict,
    _build_chains,
    _verify_chain_async,
)

CARRY = "CAS CLINIQUE 1\r\nSalma, 56 ans, sous Amiodarone, ictÃ¨re fÃ©brile."


def _q(uid, number, text="Question ?", cas=CARRY, page=1):
    d = {"uid": uid, "page": page, "number": number, "text": text,
         "propositions": {"a": "P1", "b": "P2"}}
    if cas:
        d["cas"] = cas
    return d


# â”€â”€ P4.1: ledger block in prompts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _test_ledger_blocks():
    print("\n--- P4.1: ledger block present IFF provided, guarded text ---")
    p0 = _verification_prompt(CARRY, _q("x", 1))
    assert "ACCUMULATED CASE FACTS" not in p0, "no ledger -> no block"
    p1 = _verification_prompt(CARRY, _q("x", 1), ledger=["Ã¢gÃ© de 56 ans", "cytolyse Ã  12N"])
    assert "- Salma" not in p1 and "- cytolyse Ã  12N" in p1
    assert "slam" not in p1.lower()
    assert "ONLY patient-specific facts" in p1
    assert "judge with the definition exactly" in p1.lower()

    # Â§7 re-check: SAME ledger text and guard
    r0 = _recheck_prompt(CARRY, _q("a", 2), _q("b", 3))
    assert "ACCUMULATED CASE FACTS" not in r0
    r1 = _recheck_prompt(CARRY, _q("a", 2), _q("b", 3),
                         ledger=["cytolyse Ã  12N"])
    assert "- cytolyse Ã  12N" in r1 and "ONLY patient-specific facts" in r1

    # consistency: the exact same rendered ledger block in both prompt shapes
    # (single-fact prompt = byte-identical block)
    from modules.clinical_case_checker import _render_case_facts
    block = _render_case_facts(["cytolyse Ã  12N"])
    p2 = _verification_prompt(CARRY, _q("x", 1), ledger=["cytolyse Ã  12N"])
    r2 = _recheck_prompt(CARRY, _q("a", 2), _q("b", 3), ledger=["cytolyse Ã  12N"])
    assert block in p2 and block in r2
    print("OK both prompt shapes embed identical, patient-scoped ledger text.")


def _test_parse_facts_field():
    print("\n--- P4.2: _parse_verdict captures/tolerates case_facts_used ---")
    v = _parse_verdict('{"applies": true, "confidence": 0.9, "case_facts_used": "56yo + labs"}')
    assert v["case_facts_used"] == "56yo + labs"
    assert _parse_verdict('{"applies": true, "confidence": 0.9}') == \
           {"applies": True, "confidence": 0.9}, "absent -> unchanged exact dict"
    assert _parse_verdict('{"applies": false, "case_facts_used": "   "}') == \
           {"applies": False, "confidence": None}, "blank -> omitted"
    assert _parse_verdict("no json") is None
    print("OK facts field captured when present, omitted when absent.")


# â”€â”€ mock helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _res(applies, facts=None, confidence=0.9):
    payload = {"applies": applies, "confidence": confidence}
    if facts:
        payload["case_facts_used"] = facts
    return {"content": json.dumps(payload),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "cost": 0.0}


def _ledger_recorder(client):
    """Wrap generate_completion_async capturing every prompt."""
    prompts = []
    async def gen(prompt, **kw):
        prompts.append(prompt)
        if "re-checking one judgment" in prompt:
            return _res(False, "answerable without case info")   # Â§7 confirms NO
        for text in ("Q1", "Q2", "Q3", "Q4", "Q5"):
            if text in prompt:
                return _res({"Q1": True, "Q2": True, "Q3": True,
                             "Q4": False, "Q5": True}[text])
        return _res(True)
    client.generate_completion_async = AsyncMock(side_effect=gen)
    return prompts


class _ChainClient:
    """MagicMock with a scripted per-call verdict queue + prompt capture."""
    def __init__(self, plan):
        self.plan = list(plan)          # [(applies, facts)] consumed in order
        self.prompts = []
        plan, prompts = self.plan, self.prompts
        async def gen(prompt, **kw):
            prompts.append(prompt)
            if plan:
                applies, facts = plan.pop(0)
                return _res(applies, facts)
            return _res(True)
        self.generate_completion_async = AsyncMock(side_effect=gen)
        self._proxy = MagicMock()
        return
    def __getattr__(self, name):
        return getattr(self._proxy, name)


def _seed(tmp: Path, qcms):
    d = tmp / "step3_metadata" / "accepted"
    d.mkdir(parents=True, exist_ok=True)
    (d / "page_1.json").write_text(
        json.dumps(qcms, ensure_ascii=False), encoding="utf-8")
    return d


class _Ctx:
    def __init__(self, base: Path):
        self.base_path = base
        self.name = "p4"
    def get_path(self, step, sub=""):
        p = self.base_path / step
        if sub:
            p = p / sub
        p.mkdir(parents=True, exist_ok=True)
        return p


def _test_chain_ledger_accumulation():
    print("\n--- P4.3: ledger accumulates on YES, is passed to the NEXT QCM ---")
    client = _ChainClient([
        (True, "56 ans"),          # Q1 confirmed, fact written
        (True, "cytolyse Ã  12N"),  # Q2 prompt must contain BOTH facts
        (False, None),             # Q3 NO -> ledger unchanged
        (False, None),             # Q4 NO -> two consecutive -> close (tail)
    ])
    entries = [(Path("f"), q) for q in [
        _q("u1", 1, "Q1"), _q("u2", 2, "Q2"), _q("u3", 3, "Q3"),
        _q("u4", 4, "Q4"), _q("u5", 5, "Q5"),
    ]]
    chains = _build_chains(entries)
    assert len(chains) == 1 and chains[0]["items"] == [0, 1, 2, 3, 4], chains

    coro = _verify_chain_async(0, chains[0], entries, client, MagicMock(),
                               "primary", "fallback", 500, True)
    res = asyncio.run(coro)
    prompts = client.prompts

    # ledger flowed into later prompts
    assert "- 56 ans" not in prompts[0], "first prompt has empty ledger"
    assert "- 56 ans" in prompts[1], "ledger written by Q1 visible in Q2 prompt"
    assert "- cytolyse Ã  12N" in prompts[2], "Q2 fact visible in Q3 prompt"

    # NOs never wrote to the ledger: after two consecutive NOs the tail
    # unlinks with zero further LLM calls
    assert res["stats"]["unlinked"] == 3, res["stats"]           # Q3, Q4, Q5(tail)
    assert res["llm_calls_made"] == 4, res                       # Q1..Q4, no Q5
    assert len(prompts) == 4, "Q1..Q4 verified, Q5 saved"
    print("OK ledger written on YES; visible downstream; closed tail unlinked w/o calls.")


def _test_ledger_never_written_on_no():
    print("\n--- P4.4: NO/unresolved never contribute to the ledger ---")
    # resolve followed by NO followed by YES: the NO's absence in ledger
    entries = [(Path("f"), q) for q in [
        _q("u1", 1, "Q1"), _q("u2", 2, "Q2"), _q("u3", 3, "Q3"),
    ]]
    chains = _build_chains(entries)
    client = _ChainClient([
        (True, "56 ans"),
        (False, None),
        (True, "lab values X"),
    ])
    coro = _verify_chain_async(0, chains[0], entries, client, MagicMock(),
                               "primary", "fallback", 500, True)
    res = asyncio.run(coro)
    prompts = client.prompts
    # [Q1 verify][Q2 verify][re-check of Q2][Q3 verify]
    assert len(prompts) == 4, prompts
    assert "56 ans" in prompts[1]                     # YES before
    assert "- 56 ans" in prompts[3], "ledger survives to the post-NO QCM"
    # §7 re-check prompt must embed the SAME ledger evidence
    assert "ACCUMULATED CASE FACTS" in prompts[2]
    assert "- 56 ans" in prompts[2]
    assert res["decisions"][1]["note"], res["decisions"][1]
    print("OK NO never reinforces; §7 re-check sees identical ledger.")


def _test_audit_writeback_and_persistence():
    print("\n--- P4.5: Edit 7 write-back + persistence without unlinks ---")
    tmp = Path(tempfile.mkdtemp())
    try:
        d = _seed(tmp, [_q("u1", 1, "Q1"), _q("u2", 2, "Q2")])
        client = _ChainClient([(True, "56 ans"), (True, "icterus febrile — fact note")])
        with patch("modules.clinical_case_checker.OpenRouterClient", return_value=client):
            res = run_clinical_case_checker(MagicMock(), _Ctx(tmp))
        assert res["status"] == "ok", res
        data = json.loads((d / "page_1.json").read_text(encoding="utf-8"))
        assert data[0].get("case_belonging_check", "").startswith("checker YES")
        assert "56 ans" in data[0]["case_belonging_check"], "facts folded into note"
        assert data[1].get("case_belonging_check", "").startswith("checker YES")
        # no unlink happened but note DID persist (file rewritten)
        assert data[0]["cas"] == CARRY, "cas intact on kept links"
        print("OK notes persisted on kept links (pure audit, cas untouched).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_all():
    _test_ledger_blocks()
    _test_parse_facts_field()
    _test_chain_ledger_accumulation()
    _test_ledger_never_written_on_no()
    _test_audit_writeback_and_persistence()
    print("\n" + "=" * 60)
    print("ALL PHASE 4 CHECKER LEDGER TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    _run_all()

