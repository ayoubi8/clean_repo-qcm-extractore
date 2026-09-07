# Correction Phase 6: Model Policy

The active backend keeps separate primary/fallback pairs. Environment variables
override these defaults in deployment.

| Slot | Primary default | Fallback default |
|---|---|---|
| Step 1 OCR | `qwen/qwen3-vl-30b-a3b-instruct` | `qwen/qwen-2.5-vl-7b-instruct:free` |
| Step 6 text | `nvidia/nemotron-3-nano-30b-a3b:free` | `google/gemini-2.0-flash-lite-001` |
| Step 6 all-pages | `google/gemini-2.5-flash-lite-preview-09-2025` | `google/gemini-2.0-flash-001` |
| Step 6 auto-detect | `deepseek/deepseek-v4-flash` | `google/gemini-2.0-flash-001` |
| Step 6 reasoning | `deepseek/deepseek-r1-distill-llama-70b` | `deepseek/deepseek-r1` |

The implementation does not force a stronger or more expensive model. It only
centralizes defaults and keeps the existing environment-variable overrides.
Model and cost calls continue to be recorded by `CostTracker`; retries use the
configured fallback rather than silently selecting a different model.

Before production rollout, benchmark the pairs against the Phase 1 corpus and
compare coverage, conflicts, latency, and cost per page. Do not promote a
stronger default based only on a single PDF.
