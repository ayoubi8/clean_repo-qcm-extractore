"""Clinical Case Checker — Phase 1: per-QCM cascading verification.

Runs inside the Step 2 auto-enrich cascade (see modules/post_step2_metadata.py),
AFTER Step 3 (metadata) and BEFORE the Step 4/5 build. The Step 3 "per_group"
strategy already cascades the detected "cas clinique" text forward over
consecutive QCMs (deterministic propagation in step3_metadata.py
_propagate_cas_clinique). This module adds the Phase 1 verification pass:

    a cheap/fast model double-checks every QCM in every cascaded chain —
    one simple verification question per QCM, chains in PARALLEL
    (asyncio, max CC_CHECKER_MAX_PARALLEL concurrent, default 5),
    QCMs strictly sequential WITHIN each chain.

Decision policy (spec clinical_case_checker.md §6-§7):
    - Verified (applies=true)  -> the QCM keeps its cascaded `cas` text.
    - Single NO (applies=false) -> PROVISIONAL: the link is kept until the
      next verdict confirms (second NO) or refutes (YES + §7 re-check) it.
    - Two consecutive NOs      -> the case CLOSES at the QCM before the
      first NO (CC_CHECKER_EARLY_STOP=1, default on); every QCM from the
      first NO onward is unlinked with ZERO further LLM calls for that
      chain, and that chain's task ends.
    - §7 re-check              -> a lone NO followed by YES marks the NO
      suspicious; it is re-verified once (case context + the YES question).
      A confirmed NO unlinks that QCM only; a re-check YES keeps the link;
      a re-check failure keeps the link (never a rejection).
    - LLM failure              -> the decision stays "unresolved"; the linkage
      is KEPT (a technical failure is never silently converted into a
      rejection). Unresolved verdicts neither confirm nor reset the
      consecutive-NO counter. If every verification call fails, the run is
      flagged "error" (data left unverified) but never modifies the QCM data.

Model configuration is external to the business logic (spec §30):
    CC_CHECKER_MODEL           primary model  (cheap/fast, e.g. mercury)
    CC_CHECKER_FALLBACK_MODEL  fallback model
    CC_CHECKER_MAX_TOKENS      tiny JSON response budget (default 500)
    CC_CHECKER_MAX_PARALLEL    max chains verified concurrently (default 5)
    CC_CHECKER_EARLY_STOP      1 (default) = two-consecutive-NO boundary rule;
                               0 = legacy per-QCM unlink, still parallel
                               across chains

Audit / idempotency: results are written to
    step3_metadata/clinical_case_verification.json
(folder root — NOT accepted/, which Step 5 glob-reads as QCM lists). A re-run
of the cascade skips verification when the previous audit covers the exact
same uid set (mirrors the Q8 fast-path in post_step2_metadata).
"""
import asyncio
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.openrouter_client import OpenRouterClient

VERIFICATION_FILENAME = "clinical_case_verification.json"
DEFAULT_CC_MODEL = "inception/mercury-2.5-preview"
DEFAULT_CC_FALLBACK = "google/gemini-2.0-flash-lite-001"
DEFAULT_CC_MAX_PARALLEL = 5


# ─────────────────────────────────────────────────────────────────────────────
# Loading + chain building
# ─────────────────────────────────────────────────────────────────────────────

def _qcm_uid(qcm: Dict, fallback: str) -> str:
    uid = qcm.get("uid")
    return uid if uid is not None else fallback


def _load_step3_qcms(accepted_dir: Path) -> Tuple[List[Tuple[Path, Dict]], Dict[Path, List[Dict]]]:
    """Load every accepted Step 3 QCM file in document order.

    Files are visited sorted by name (the same order Step 3 processed them);
    within a file the stored list order is preserved — that IS the order the
    Step 3 propagation walked, so chain boundaries stay exact.

    Returns:
        (entries, file_data)
        entries    : [(file_path, qcm_dict)] in document order
        file_data  : {file_path: qcm_list} for writing corrections back
    """
    entries: List[Tuple[Path, Dict]] = []
    file_data: Dict[Path, List[Dict]] = {}

    q_files = sorted([p for p in accepted_dir.glob("*.json")
                      if not p.name.startswith("merged_")])
    for q_file in q_files:
        try:
            with open(q_file, "r", encoding="utf-8") as f:
                qcms = json.load(f)
        except Exception as e:
            print(f"[CC-CHECK] ⚠️ Could not read {q_file.name}: {e}")
            continue
        if not isinstance(qcms, list):
            continue
        file_data[q_file] = qcms
        for i, qcm in enumerate(qcms):
            qcm.setdefault("uid", f"noidx_{q_file.stem}_{i}")
            entries.append((q_file, qcm))
    return entries, file_data


def _build_chains(entries: List[Tuple[Path, Dict]]) -> List[Dict]:
    """Group entries into maximal consecutive runs sharing the same non-null
    `cas` text. Two runs with identical case text separated by anything else
    (a different case or case-less QCMs) are two separate chains."""
    chains: List[Dict] = []
    for idx, (_f, qcm) in enumerate(entries):
        cas = qcm.get("cas")
        if not cas:
            continue
        if chains and chains[-1]["cas"] == cas and chains[-1]["last_index"] == idx - 1:
            chains[-1]["last_index"] = idx
            chains[-1]["items"].append(idx)
        else:
            chains.append({"cas": cas, "first_index": idx, "last_index": idx, "items": [idx]})
    return chains


def _split_cas(cas: str) -> Tuple[str, str]:
    if "\r\n" in cas:
        label, narrative = cas.split("\r\n", 1)
        return (label or "CAS CLINIQUE"), narrative
    if "\n" in cas:
        label, narrative = cas.split("\n", 1)
        return (label or "CAS CLINIQUE"), narrative
    return "CAS CLINIQUE", cas


# ─────────────────────────────────────────────────────────────────────────────
# LLM verification
# ─────────────────────────────────────────────────────────────────────────────

def _render_propositions(qcm: Dict) -> str:
    props = qcm.get("propositions") or {}
    lines = []
    for letter in ["A", "B", "C", "D", "E"]:
        val = props.get(letter) or props.get(letter.lower())
        if val:
            lines.append(f"{letter}. {val}")
    return "\n".join(lines) if lines else "(no propositions)"


def _verification_prompt(cas: str, qcm: Dict) -> str:
    label, narrative = _split_cas(cas)
    question = qcm.get("text") or qcm.get("Text") or "(no question text)"
    propositions = _render_propositions(qcm)
    return f"""You verify whether a multiple-choice question (QCM) really belongs to a clinical case.

DEFINITION — apply it exactly:
A QCM belongs to the clinical case only when the information contained in that
case is necessary or materially useful to answer the QCM correctly. If the QCM
can be answered correctly without using the case-specific information, it does
NOT belong — even if it deals with the same medical subject.

CLINICAL CASE — {label}:
{narrative}

QUESTION:
{question}

PROPOSITIONS:
{propositions}

Reply with ONE line of JSON only — no markdown, no explanation:
{{"applies": true, "confidence": 0.9}}"""


def _parse_verdict(content: str) -> Optional[Dict]:
    """Parse + validate the one-line JSON verdict. Returns None on any
    invalid response (treated as unresolved, never as a rejection)."""
    try:
        cleaned = re.sub(r'```(?:json)?\s*', '', content or '')
        cleaned = re.sub(r'```\s*', '', cleaned).strip()
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(0))
        applies = data.get("applies")
        if isinstance(applies, str):
            lowered = applies.strip().lower()
            if lowered == "true":
                applies = True
            elif lowered == "false":
                applies = False
            else:
                return None  # ambiguous string is NOT a valid verdict
        if not isinstance(applies, bool):
            return None
        confidence = data.get("confidence")
        if isinstance(confidence, (int, float)):
            confidence = max(0.0, min(1.0, float(confidence)))
        else:
            confidence = None
        return {"applies": applies, "confidence": confidence}
    except Exception:
        return None


def _recheck_prompt(cas: str, suspicious_qcm: Dict, next_qcm: Dict) -> str:
    """Spec §7 re-check prompt: one provisional NO followed by a YES.

    Decides ONLY for QCM A (the provisional NO). QCM B (the confirmed YES
    right after it) is shown as context evidence.
    """
    label, narrative = _split_cas(cas)
    a_text = suspicious_qcm.get("text") or suspicious_qcm.get("Text") or "(no question text)"
    b_text = next_qcm.get("text") or next_qcm.get("Text") or "(no question text)"
    return f"""You are re-checking one judgment about a multiple-choice question (QCM) and a clinical case.

QCM A below was provisionally judged NOT to belong to the clinical case, but the
QCM immediately after it (QCM B) WAS judged to belong. One of the two judgments
may be wrong. Decide ONLY for QCM A, using the definition exactly.

DEFINITION — apply it exactly:
A QCM belongs to the clinical case only when the information contained in that
case is necessary or materially useful to answer the QCM correctly. If the QCM
can be answered correctly without using the case-specific information, it does
NOT belong — even if it deals with the same medical subject.

CLINICAL CASE — {label}:
{narrative}

QCM A (provisional NO — judge this one):
{a_text}

PROPOSITIONS A:
{_render_propositions(suspicious_qcm)}

QCM B (confirmed YES — context only, do NOT judge it):
{b_text}

Reply with ONE line of JSON only — no markdown, no explanation:
{{"applies": true, "confidence": 0.9}}"""


async def _ask_verdict_async(client: OpenRouterClient, tracker, prompt: str,
                             primary_model: str, fallback_model: str,
                             max_tokens: int) -> Dict:
    """One verdict request (any prompt shape). Primary then fallback.
    Returns {"status": "ok", ...verdict, "model"} or {"status": "unresolved"}."""
    for model in [primary_model, fallback_model]:
        try:
            resp = await client.generate_completion_async(
                prompt, model=model, max_tokens=max_tokens, temperature=0.0
            )
            verdict = _parse_verdict(resp.get("content", ""))
            if verdict is None:
                raise ValueError("invalid JSON verdict")
            cost = resp.get("cost", 0.0) or OpenRouterClient.estimate_cost(
                model, resp.get("usage", {}))
            tracker.log_api_call("cc_checker", model, resp.get("usage", {}), cost)
            return {"status": "ok", "model": model, **verdict}
        except Exception as e:
            print(f"[CC-CHECK] ⚠️ Verification call failed ({model}): {e}")
            continue
    return {"status": "unresolved"}


async def _verify_one_async(client: OpenRouterClient, tracker, qcm: Dict, cas: str,
                            primary_model: str, fallback_model: str,
                            max_tokens: int) -> Dict:
    """One simple verification request for one QCM. Primary then fallback."""
    return await _ask_verdict_async(
        client, tracker, _verification_prompt(cas, qcm),
        primary_model, fallback_model, max_tokens)


# ─────────────────────────────────────────────────────────────────────────────
# Idempotency
# ─────────────────────────────────────────────────────────────────────────────

def _verification_covers(step3_dir: Path, current_uids: set) -> bool:
    """True when a previous verification run covered the exact same uid set."""
    audit_file = step3_dir / VERIFICATION_FILENAME
    if not audit_file.exists():
        return False
    try:
        with open(audit_file, "r", encoding="utf-8") as f:
            audit = json.load(f)
        previous = set(audit.get("uid_set", []))
        return bool(previous) and previous == current_uids
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Parallel chain verification (async)
# ─────────────────────────────────────────────────────────────────────────────

async def _verify_chain_async(chain_index: int, chain: Dict,
                              entries: List[Tuple[Path, Dict]],
                              client: OpenRouterClient, tracker,
                              primary_model: str, fallback_model: str,
                              max_tokens: int, early_stop: bool) -> Dict:
    """Verify ONE chain, QCM by QCM in document order.

    Early-stop state machine (spec §6-§7, active when early_stop=True):
      - YES                    -> keep link, reset consecutive_no. A pending
                                  provisional NO triggers one §7 re-check.
      - first NO               -> PROVISIONAL: link kept, counter = 1.
      - second NO (no YES in between; unresolved verdicts neither confirm
        nor reset)             -> CLOSE: unlink from the first NO onward with
                                  ZERO further LLM calls, end this chain.
      - unresolved             -> link kept, counter untouched.
      - chain ends on a pending NO -> the decisive verdict is confirmed
                                  (unlink that QCM only, legacy parity).
    With early_stop=False the legacy per-QCM behavior applies (every
    applies=false unlinks that QCM immediately, all QCMs verified).

    File writes are NOT done here — corrections are applied to the in-memory
    QCM dicts and the caller persists files after gather (single-threaded).
    """
    label, narrative = _split_cas(chain["cas"])
    items = chain["items"]
    first_q = entries[chain["first_index"]][1]
    last_q = entries[chain["last_index"]][1]
    preview = narrative[:70].replace("\n", " ") + ("..." if len(narrative) > 70 else "")
    print(f"\n  [CC-CHECK] [CAS {chain_index}] {label} — {len(items)} QCM(s) "
          f"(Q{first_q.get('number', '?')} p.{first_q.get('page', '?')} → "
          f"Q{last_q.get('number', '?')} p.{last_q.get('page', '?')})")
    print(f"  [CC-CHECK]   Case: \"{preview}\"")

    decisions: List[Dict] = []
    cstats = {"verified": 0, "kept": 0, "unlinked": 0, "unresolved": 0,
              "corrections": 0, "rechecked": 0}
    consecutive_no = 0
    suspicious = None  # {"pos", "entry_idx", "decision"} — provisional NO
    closed_early = False
    early_stop_reason = None
    closed_at_entry_idx = None
    last_member_entry_idx = None
    llm_calls_made = 0
    llm_calls_saved = 0

    def _base_decision(pos: int, entry_idx: int) -> Dict:
        _f, _q = entries[entry_idx]
        return {
            "uid": _q.get("uid"), "page": _q.get("page"), "number": _q.get("number"),
            "chain": chain_index, "case_label": label,
            "entry_idx": entry_idx, "pos": pos,
            "status": "pending", "corrected": False,
            "provisional": False, "rechecked": False, "after_close": False,
        }

    def _unlink(decision: Dict) -> None:
        decision["corrected"] = True
        cstats["unlinked"] += 1
        cstats["corrections"] += 1

    for pos, entry_idx in enumerate(items):
        _f, qcm = entries[entry_idx]
        print(f"[CC-CHECK] Verifying chain {chain_index} — "
              f"QCM {pos + 1}/{len(items)} (Q{qcm.get('number', '?')} "
              f"p.{qcm.get('page', '?')}) ...")

        verdict = await _verify_one_async(client, tracker, qcm, chain["cas"],
                                          primary_model, fallback_model, max_tokens)
        llm_calls_made += 1
        decision = _base_decision(pos, entry_idx)
        decision["status"] = verdict["status"]

        if verdict["status"] != "ok":
            # Technical failure is never a rejection — and it neither
            # confirms a pending NO nor resets the consecutive counter.
            cstats["unresolved"] += 1
            print("     ⚠️ unresolved — link kept (technical failure, not a rejection)")
            decisions.append(decision)
            continue

        cstats["verified"] += 1
        decision["applies"] = verdict["applies"]
        decision["confidence"] = verdict.get("confidence")
        decision["model"] = verdict.get("model")

        if verdict["applies"]:
            cstats["kept"] += 1
            conf = f" ({verdict.get('confidence'):.2f})" if verdict.get("confidence") is not None else ""
            print(f"     ✅ belongs{conf} — keeps the clinical case")
            consecutive_no = 0
            if suspicious is not None and early_stop:
                # Spec §7: lone NO followed by YES → re-check the suspicious QCM.
                s_entry_idx = suspicious["entry_idx"]
                _sf, s_qcm = entries[s_entry_idx]
                s_decision = suspicious["decision"]
                print(f"     ↩️ §7 re-check: Q{s_qcm.get('number', '?')} "
                      f"(provisional NO followed by YES) ...")
                recheck = await _ask_verdict_async(
                    client, tracker,
                    _recheck_prompt(chain["cas"], s_qcm, qcm),
                    primary_model, fallback_model, max_tokens)
                llm_calls_made += 1
                cstats["rechecked"] += 1
                s_decision["rechecked"] = True
                if recheck["status"] == "ok" and recheck["applies"] is False:
                    # Provisional NO confirmed — unlink that QCM only.
                    _unlink(s_decision)
                    print(f"     ❌ §7 re-check confirms Q{s_qcm.get('number', '?')} "
                          f"does NOT belong — link removed (that QCM only)")
                elif recheck["status"] == "ok":
                    print(f"     ✅ §7 re-check: Q{s_qcm.get('number', '?')} actually "
                          f"belongs — provisional NO was a model error, link kept")
                else:
                    # Re-check failed technically → keep the link and downgrade
                    # to unresolved (a failure is never a rejection).
                    s_decision["status"] = "unresolved"
                    s_decision.pop("applies", None)
                    s_decision.pop("confidence", None)
                    s_decision.pop("model", None)
                    cstats["verified"] -= 1
                    cstats["unresolved"] += 1
                    print("     ⚠️ §7 re-check failed technically — link kept (needs attention)")
                suspicious = None
            decisions.append(decision)
            continue

        # applies == false
        if not early_stop:
            # Flag off: legacy per-QCM behavior — unlink immediately.
            _unlink(decision)
            print("     ❌ does NOT belong — clinical case link removed (unlinked)")
            decisions.append(decision)
            continue

        if consecutive_no >= 1 and suspicious is not None:
            # Two consecutive NOs (no YES between) → CLOSE the case at the
            # QCM *before* the first NO. Unlink from the first NO onward.
            closed_early = True
            early_stop_reason = "two_consecutive_no"
            first_no_pos = suspicious["pos"]
            closed_at_entry_idx = suspicious["entry_idx"]
            last_member_entry_idx = items[first_no_pos - 1] if first_no_pos > 0 else None
            s_decision = suspicious["decision"]
            s_decision["provisional"] = True
            _unlink(s_decision)
            decision["provisional"] = True
            _unlink(decision)
            decisions.append(decision)
            tail = items[pos + 1:]
            llm_calls_saved = len(tail)
            for t_pos, t_entry_idx in enumerate(tail, start=pos + 1):
                t_dec = _base_decision(t_pos, t_entry_idx)
                t_dec["status"] = "unlinked_by_boundary"
                t_dec["after_close"] = True
                _unlink(t_dec)
                decisions.append(t_dec)
            print(f"     ⛔ Two consecutive NOs — case closed before "
                  f"Q{entries[suspicious['entry_idx']][1].get('number', '?')}; "
                  f"{len(tail)} remaining QCM(s) unlinked without LLM calls")
            suspicious = None
            break

        # First NO of a potential pair → PROVISIONAL (spec §6.2), link kept.
        consecutive_no = 1
        decision["provisional"] = True
        suspicious = {"pos": pos, "entry_idx": entry_idx, "decision": decision}
        print("     ❓ provisional NO — link kept pending next verdict (§6.2)")
        decisions.append(decision)

    # Chain ended on a pending provisional NO with nothing after it: the
    # verdict was decisive, so confirm it (unlink that QCM only — legacy parity).
    if suspicious is not None and not closed_early:
        _unlink(suspicious["decision"])
        _sf, _sq = entries[suspicious["entry_idx"]]
        print(f"     ❌ End of chain: pending NO confirmed — "
              f"Q{_sq.get('number', '?')} link removed (that QCM only)")

    # Apply corrections to the in-memory QCM dicts (shared references with
    # file_data — the caller writes the files back after gather).
    for d in decisions:
        if d.get("corrected"):
            _ef, _eq = entries[d["entry_idx"]]
            _eq.pop("cas", None)

    return {
        "chain_index": chain_index, "label": label, "items": items,
        "decisions": decisions, "stats": cstats,
        "closed_early": closed_early, "early_stop_reason": early_stop_reason,
        "last_member_entry_idx": last_member_entry_idx,
        "closed_at_entry_idx": closed_at_entry_idx,
        "llm_calls_made": llm_calls_made, "llm_calls_saved": llm_calls_saved,
        "elapsed_ms": None,  # filled by the gather wrapper
    }


async def _verify_all_chains_async(chains: List[Dict],
                                   entries: List[Tuple[Path, Dict]],
                                   client: OpenRouterClient, tracker,
                                   primary_model: str, fallback_model: str,
                                   max_tokens: int, max_parallel: int,
                                   early_stop: bool) -> List[Dict]:
    """Run every chain as its own task, at most max_parallel concurrently."""
    semaphore = asyncio.Semaphore(max(1, int(max_parallel)))
    print(f"[CC-CHECK] Parallel verification: {len(chains)} chain(s), "
          f"max {max_parallel} concurrent, early_stop={'on' if early_stop else 'off'}")

    async def _bounded(ci: int, chain: Dict) -> Dict:
        async with semaphore:
            t0 = time.monotonic()
            res = await _verify_chain_async(ci, chain, entries, client, tracker,
                                            primary_model, fallback_model,
                                            max_tokens, early_stop)
            res["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
            return res

    return list(await asyncio.gather(
        *(_bounded(ci, c) for ci, c in enumerate(chains, 1))))


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_clinical_case_checker(tracker, context) -> Dict:
    """Verify every cascaded clinical-case link with a cheap/fast model.

    Chains are verified in PARALLEL (asyncio, max CC_CHECKER_MAX_PARALLEL
    concurrent chains, default 5); QCMs stay sequential WITHIN each chain so
    the two-consecutive-NO boundary rule (spec §6.3, CC_CHECKER_EARLY_STOP=1
    by default) can close a chain early.

    Sync entry point — safe to call from a plain thread (the cascade's
    executor worker) or from an event-loop thread (isolated worker thread).

    Must run after Step 3 wrote step3_metadata/accepted/*.json and before the
    Step 4/5 build consumes them. Corrections (unlinks) are written back into
    the accepted files; an audit trail lands in step3_metadata/ (folder root).

    Returns:
        {"status": "ok",        "stats": {...}}
        {"status": "no_qcms"}   # no accepted metadata
        {"status": "no_cases"}  # nothing has a `cas` field
        {"status": "skipped"}   # idempotent: same uid set already verified
        {"status": "error",     "detail": str, "stats": {...}}
    """
    print("\n" + "═" * 60)
    print("CLINICAL CASE CHECKER  (Phase 1 — per-QCM cascade verification)")
    print("═" * 60)

    try:
        accepted_dir = Path(context.get_path("step3_metadata", "accepted"))
        step3_dir = Path(context.get_path("step3_metadata"))
    except Exception as e:
        return {"status": "error", "detail": f"project context error: {e}"}

    if not accepted_dir.exists():
        print("[CC-CHECK] No step3_metadata/accepted folder — nothing to verify.")
        return {"status": "no_qcms"}

    entries, file_data = _load_step3_qcms(accepted_dir)
    if not entries:
        print("[CC-CHECK] No accepted QCM JSON found — nothing to verify.")
        return {"status": "no_qcms"}

    chains = _build_chains(entries)
    if not chains:
        print("[CC-CHECK] No QCM carries a clinical case (`cas`) — nothing to verify.")
        return {"status": "no_cases"}

    current_uids = {qcm.get("uid") for _f, qcm in entries}
    if _verification_covers(step3_dir, current_uids):
        print("[CC-CHECK] Previous verification already covers this exact QCM set — skipping. "
              "Delete step3_metadata/clinical_case_verification.json to force re-verification.")
        return {"status": "skipped"}

    primary_model  = os.getenv("CC_CHECKER_MODEL", DEFAULT_CC_MODEL)
    fallback_model = os.getenv("CC_CHECKER_FALLBACK_MODEL", DEFAULT_CC_FALLBACK)
    max_tokens     = int(os.getenv("CC_CHECKER_MAX_TOKENS") or "500")
    print(f"[CC-CHECK] Model: {primary_model} (fallback: {fallback_model})")

    client = OpenRouterClient()
    try:
        max_parallel = max(1, int(os.getenv("CC_CHECKER_MAX_PARALLEL")
                                  or DEFAULT_CC_MAX_PARALLEL))
    except (TypeError, ValueError):
        max_parallel = DEFAULT_CC_MAX_PARALLEL
    early_stop = (os.getenv("CC_CHECKER_EARLY_STOP", "1") != "0")
    print(f"[CC-CHECK] {len(chains)} clinical case chain(s) over "
          f"{sum(len(c['items']) for c in chains)} QCMs — verifying chains in "
          f"parallel (max {max_parallel}), QCMs sequential within each chain...")

    _gather_kwargs = dict(
        chains=chains, entries=entries, client=client, tracker=tracker,
        primary_model=primary_model, fallback_model=fallback_model,
        max_tokens=max_tokens, max_parallel=max_parallel, early_stop=early_stop)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Normal path: the cascade runs in an executor thread with no loop.
        chain_results = asyncio.run(_verify_all_chains_async(**_gather_kwargs))
    else:
        # Already on an event-loop thread: isolate in a private thread with
        # its own loop so loops are never nested. The tracker is only
        # touched from that worker thread while this thread waits.
        _box: Dict[str, Any] = {}

        def _worker() -> None:
            _box["res"] = asyncio.run(_verify_all_chains_async(**_gather_kwargs))

        _wt = threading.Thread(target=_worker, daemon=True)
        _wt.start()
        _wt.join()
        chain_results = _box["res"]

    # Merge (single-threaded): decisions, stats, per-chain close markers.
    decisions: List[Dict] = []
    stats = {"chains": len(chains), "verified": 0, "kept": 0,
             "unlinked": 0, "unresolved": 0, "corrections": 0,
             "closed_early_chains": 0, "llm_calls_made": 0, "llm_calls_saved": 0,
             "rechecked": 0}
    for cr in chain_results:
        decisions.extend(cr["decisions"])
        for _k in ("verified", "kept", "unlinked", "unresolved",
                   "corrections", "rechecked"):
            stats[_k] += cr["stats"][_k]
        stats["llm_calls_made"] += cr["llm_calls_made"]
        stats["llm_calls_saved"] += cr["llm_calls_saved"]
        if cr["closed_early"]:
            stats["closed_early_chains"] += 1
            print(f"[CC-CHECK] ⛔ Chain {cr['chain_index']} closed early "
                  f"(two consecutive NOs) — {cr['llm_calls_saved']} LLM call(s) "
                  f"saved in {cr['elapsed_ms']} ms")

    # Write corrected files back (only the ones where a QCM was unlinked).
    corrected_uids = {d["uid"] for d in decisions if d.get("corrected")}
    if corrected_uids:
        for q_file, qcms in file_data.items():
            if any(q.get("uid") in corrected_uids for q in qcms):
                with open(q_file, "w", encoding="utf-8") as f:
                    json.dump(qcms, f, indent=2, ensure_ascii=False)
                print(f"[CC-CHECK] 💾 Corrections written → {q_file.name}")

    # Summary (streams to the UI terminal log).
    print("\n" + "═" * 60)
    print("📊 CLINICAL CASE VERIFICATION SUMMARY")
    print("═" * 60)
    print(f"  Chains verified:  {stats['chains']}")
    print(f"  QCMs verified:    {stats['verified']}")
    print(f"  Kept:             {stats['kept']}")
    print(f"  Unlinked:         {stats['unlinked']}  (wrong links corrected)")
    print(f"  Unresolved:       {stats['unresolved']}  (links kept, need attention)")
    print(f"  Closed early:     {stats['closed_early_chains']}  (two-consecutive-NO boundary)")
    print(f"  LLM calls:        {stats['llm_calls_made']} made, {stats['llm_calls_saved']} saved by early stop")
    print(f"  Re-checked (§7):  {stats['rechecked']}")
    print(f"  Model:            {primary_model}")
    print("═" * 60)

    # Audit trail (step3_metadata folder root — NOT accepted/, which Step 5
    # glob-reads as QCM lists; the folder-wide Storage upload still persists it).
    audit = {
        "run_ts": datetime.now().isoformat(),
        "strategy": "per_qcm_cascade_parallel",
        "mode": {"max_parallel": max_parallel, "early_stop": early_stop},
        "model": primary_model,
        "fallback_model": fallback_model,
        "uid_set": sorted(u for u in current_uids if u is not None),
        "stats": stats,
        "chains": [
            {
                "index": cr["chain_index"],
                "label": cr["label"],
                "size": len(cr["items"]),
                "first_uid": entries[chains[cr["chain_index"] - 1]["first_index"]][1].get("uid"),
                "last_uid": entries[chains[cr["chain_index"] - 1]["last_index"]][1].get("uid"),
                "closed_early": cr["closed_early"],
                "early_stop_reason": cr["early_stop_reason"],
                "last_member_index": cr["last_member_entry_idx"],
                "closed_at_index": cr["closed_at_entry_idx"],
                "llm_calls_made": cr["llm_calls_made"],
                "llm_calls_saved": cr["llm_calls_saved"],
                "elapsed_ms": cr["elapsed_ms"],
            }
            for cr in chain_results
        ],
        "decisions": decisions,
    }
    try:
        step3_dir.mkdir(parents=True, exist_ok=True)
        with open(step3_dir / VERIFICATION_FILENAME, "w", encoding="utf-8") as f:
            json.dump(audit, f, indent=2, ensure_ascii=False)
        print(f"[CC-CHECK] 💾 Audit saved → {VERIFICATION_FILENAME}")
    except Exception as e:
        print(f"[CC-CHECK] ⚠️ Could not write audit file: {e}")

    # Every call failed -> the cascade data is UNVERIFIED. Flag as error so the
    # wrapper surfaces the persistent alert, but never touch the QCM data.
    if stats["verified"] == 0 and stats["unresolved"] > 0:
        print("[CC-CHECK] ⚠️ ERROR: every verification call failed — clinical case "
              "links were NOT verified. The build continues with unverified data. "
              "Fix the CC Checker model (Settings) and re-run Step 2.")
        return {"status": "error",
                "detail": "all verification calls failed (model/provider issue)",
                "stats": stats}

    return {"status": "ok", "stats": stats}
