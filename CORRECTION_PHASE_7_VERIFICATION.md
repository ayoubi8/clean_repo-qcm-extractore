# Correction Phase 7 Verification

## Local verification

The deterministic correction path was executed against every Phase 1 fixture.
It verifies:

- Conventional X-mark correction tables.
- Multiple visual blocks on one line.
- `T:` precedence over conflicting grid and `R:` evidence.
- OCR variants `T8:` and `R8:`.
- Mixed and page-break correction content.
- Normal question pages producing no correction map.
- The flat string-to-string public correction-map contract.

Commands used:

```text
python -m py_compile modules/model_policy.py modules/step1_extraction.py modules/step6_corrections.py tests/test_model_policy.py tests/test_correction_page_corpus.py tests/test_correction_phase7_e2e.py
python -c "...targeted phase 0-6 checks..."
python -c "...targeted phase 7 checks..."
```

Result: targeted phases 0-7 checks passed.

## Not performed in this phase

- No external OpenRouter calls were made.
- No Hugging Face deployment was pushed.
- No Vercel deployment was triggered.
- Full pytest execution was unavailable because `pytest` is not installed in
  the current environment.

Before production deployment, run the same fixtures through the deployed API,
then test one real normal PDF and one real correction-page PDF on Hugging Face.
