"""Clinical Case Checker — Phase 1: per-QCM cascading verification.

Runs inside the Step 2 auto-enrich cascade (see modules/post_step2_metadata.py),
AFTER Step 3 (metadata) and BEFORE the Step 4/5 build. The Step 3 "per_group"
strategy already cascades the detected "cas clinique" text forward over
consecutive QCMs (deterministic propagation in step3_metadata.py
_propagate_cas_clinique). This module adds the Phase 1 verification pass:

    a cheap/fast model double-checks every QCM in every cascaded chain —
    one simple verification question per QCM, chain by chain, starting from
    the first QCM that has an attached clinical case text.

Decision policy (Phase 1):
    - Verified (applies=true)  -> the QCM keeps its cascaded `cas` text.
    - Rejected (applies=false) -> the `cas` field is removed from that QCM
      ONLY (unlinked); the rest of the chain is untouched.
    - LLM failure              -> the decision stays "unresolved"; the linkage
      is KEPT (a technical failure is never silently converted into a
      rejection). If every verification call fails, the run is flagged
      "error" (data left unverified) but never modifies the QCM data.

Model configuration is external to the business logic (spec §30):
    CC_CHECKER_MODEL           primary model  (cheap/fast, e.g. mercury)
    CC_CHECKER_FALLBACK_MODEL  fallback model
    CC_CHECKER_MAX_TOKENS      tiny JSON response budget (default 500)

Audit / idempotency: results are written to
    step3_metadata/clinical_case_verification.json
(folder root — NOT accepted/, which Step 5 glob-reads as QCM lists). A re-run
of the cascade skips verification when the previous audit covers the exact
same uid set (mirrors the Q8 fast-path in post_step2_metadata).
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.openrouter_client import OpenRouterClient

VERIFICATION_FILENAME = "clinical_case_verification.json"
DEFAULT_CC_MODEL = "inception/mercury-2.5-preview"
DEFAULT_CC_FALLBACK = "google/gemini-2.0-flash-lite-001"


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


def _verify_one(client: OpenRouterClient, tracker, qcm: Dict, cas: str,
                primary_model: str, fallback_model: str, max_tokens: int) -> Dict:
    """One simple verification request for one QCM. Primary then fallback.
    Returns {"status": "ok", ...verdict, "model"} or {"status": "unresolved"}."""
    prompt = _verification_prompt(cas, qcm)
    for model in [primary_model, fallback_model]:
        try:
            resp = client.generate_completion(
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
# Orchestration entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_clinical_case_checker(tracker, context) -> Dict:
    """Verify every cascaded clinical-case link with a cheap/fast model.

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
    print(f"[CC-CHECK] {len(chains)} clinical case chain(s) over "
          f"{sum(len(c['items']) for c in chains)} QCMs — verifying QCM by QCM...")

    client = OpenRouterClient()

    decisions: List[Dict] = []
    stats = {"chains": len(chains), "verified": 0, "kept": 0,
             "unlinked": 0, "unresolved": 0, "corrections": 0}

    for ci, chain in enumerate(chains, 1):
        label, narrative = _split_cas(chain["cas"])
        first_q = entries[chain["first_index"]][1]
        last_q = entries[chain["last_index"]][1]
        preview = narrative[:70].replace("\n", " ") + ("..." if len(narrative) > 70 else "")
        print(f"\n  [CC-CHECK] [CAS {ci}] {label} — {len(chain['items'])} QCM(s) "
              f"(Q{first_q.get('number', '?')} p.{first_q.get('page', '?')} → "
              f"Q{last_q.get('number', '?')} p.{last_q.get('page', '?')})")
        print(f"  [CC-CHECK]   Case: \"{preview}\"")

        for qi, entry_idx in enumerate(chain["items"], 1):
            q_file, qcm = entries[entry_idx]
            print(f"[CC-CHECK] Verifying chain {ci}/{len(chains)} — "
                  f"QCM {qi}/{len(chain['items'])} (Q{qcm.get('number', '?')} "
                  f"p.{qcm.get('page', '?')}) ...")

            verdict = _verify_one(client, tracker, qcm, chain["cas"],
                                  primary_model, fallback_model, max_tokens)
            decision = {
                "uid": qcm.get("uid"),
                "page": qcm.get("page"),
                "number": qcm.get("number"),
                "chain": ci,
                "case_label": label,
                "status": verdict["status"],
                "corrected": False,
            }

            if verdict["status"] == "ok":
                stats["verified"] += 1
                decision["applies"] = verdict["applies"]
                decision["confidence"] = verdict.get("confidence")
                decision["model"] = verdict.get("model")
                if verdict["applies"]:
                    stats["kept"] += 1
                    conf = f" ({verdict.get('confidence'):.2f})" if verdict.get("confidence") is not None else ""
                    print(f"     ✅ belongs{conf} — keeps the clinical case")
                else:
                    stats["unlinked"] += 1
                    stats["corrections"] += 1
                    decision["corrected"] = True
                    qcm.pop("cas", None)  # unlink: this QCM only
                    print(f"     ❌ does NOT belong — clinical case link removed (unlinked)")
            else:
                stats["unresolved"] += 1
                print(f"     ⚠️ unresolved — link kept (technical failure, not a rejection)")

            decisions.append(decision)

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
    print(f"  Model:            {primary_model}")
    print("═" * 60)

    # Audit trail (step3_metadata folder root — NOT accepted/, which Step 5
    # glob-reads as QCM lists; the folder-wide Storage upload still persists it).
    audit = {
        "run_ts": datetime.now().isoformat(),
        "strategy": "per_qcm_cascade",
        "model": primary_model,
        "fallback_model": fallback_model,
        "uid_set": sorted(u for u in current_uids if u is not None),
        "stats": stats,
        "chains": [
            {
                "index": i,
                "label": _split_cas(c["cas"])[0],
                "size": len(c["items"]),
                "first_uid": entries[c["first_index"]][1].get("uid"),
                "last_uid": entries[c["last_index"]][1].get("uid"),
            }
            for i, c in enumerate(chains, 1)
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
