# CC Checker — legacy sequential method (archived reference)

> Snapshot of `modules/clinical_case_checker.py` **before** the parallel rewrite
> (PR: parallel chain verification, max 5 concurrent, two-consecutive-NO
> early-stop). Kept per user decision Q3 so the old behavior is recoverable.
> Rollback = `git revert` to this version. Shared helpers
> (`_load_step3_qcms`, `_build_chains`, `_verification_prompt`, `_parse_verdict`,
> `_verification_covers`, audit file layout) are unchanged by the rewrite and
> are NOT duplicated here — only the two replaced blocks below.

## Behavior of the old method

- Chains verified **one chain at a time, one QCM at a time** — purely serial.
- Every `applies=false` unlinked **that QCM only** (`qcm.pop("cas")`), the rest
  of the chain was still fully verified (no early stop, no boundary rule).
- LLM failures → `unresolved`, link kept; all-failed → `status=error`.
- Sync `OpenRouterClient.generate_completion` (httpx, 60s ×3 retries + backoff).

## `_verify_one` (old, sync)

```python
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
```

## `run_clinical_case_checker` (old, sequential orchestration)

```python
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
```
