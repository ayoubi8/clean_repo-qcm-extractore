# Correction Fix Baseline: Phases 0-1

Date: 2026-09-07

## Scope

This checkpoint covers deployment/source identification and the correction-page
test corpus only. It does not change Step 1, Step 6, the frontend, prompts, or
the public API contract.

## Active source identified

- Backend implementation: `modules/step1_extraction.py` and `modules/step6_corrections.py`
- Backend deployment target: Hugging Face Space remote (`space`)
- Backend GitHub mirror: `origin`
- Frontend repository: `frontend-repo`
- Frontend source directory in this workspace: `frontend/`
- Frontend API base: `VITE_API_BASE_URL`
- Parallel copy requiring explicit confirmation before editing: `new-version/`

## Safety notes

- The worktree was already dirty before this phase. Existing changes were not
  reverted or modified.
- No deployment push or git commit is part of this phase.
- The configured Hugging Face remote previously contained an access token.
  Rotate that token and replace the remote with a credential-free URL before
  the next deployment push.
- Previously reported API keys in repository history must also be revoked and
  regenerated.

## Baseline revision

The source revision at the beginning of this phase is recorded by the local
Git history. Use `git rev-parse HEAD` to inspect it without relying on this
document for a mutable hash.

## Phase 1 acceptance criteria

The corpus under `tests/fixtures/correction_pages/` must cover:

1. Conventional X-mark correction tables.
2. Multiple visual QCM blocks on one physical line.
3. Separate `R:` and `T:` fields with scores.
4. Mixed normal-page and correction-page content.
5. Correction information split across pages.
6. OCR corruption and low-quality/rotated-page representations.
7. Conflicting evidence requiring deterministic handling.
