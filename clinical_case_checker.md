# Clinical Case Checker — Implementation Specification

## 1. Purpose

Add a new processing capability called **Clinical Case Checker** to the existing QCM/XLSX analysis pipeline.

The checker determines which QCMs belong to which **clinical case context**, using the original XLSX order as an important structural signal.

A QCM **belongs to a clinical case** when the clinical-case information is needed to answer that QCM correctly. A QCM being merely related to the same medical topic is not enough.

The checker must support two user-selectable strategies:

- **Per QCM** — analyze the QCM sequence and resolve clinical-case membership at the individual QCM level.
- **Global** — analyze the whole QCM set using parallel group/chunk processing, while still preserving the same sequence/boundary rules when merging results.

The checker is configured in the website and runs when the user runs **Step 2**, immediately after **Step 3** finishes. Step 3 is already automatically triggered by Step 2, so the Clinical Case Checker should be treated as a downstream stage merged into the Step 2 workflow rather than as a separate manual pipeline step.

---

# 2. User-facing location

## 2.1 Model Configuration

Add a new model configuration section named:

**Clinical Case Checker**

Recommended fields:

| Field | Type | Description |
|---|---|---|
| Enabled | boolean | Enable/disable the checker for the current run. |
| Model | select/input | LLM model used by Clinical Case Checker. |
| Provider / OpenRouter | select/input | Provider or OpenRouter routing configuration. |
| Temperature | number | Default `0`. |
| Max output tokens | number | Small JSON response for membership checks; larger value for case-profile creation. |
| Timeout | number | Request timeout in seconds. |
| Max parallel requests | integer | Upper bound for concurrent LLM calls. |
| Retry count | integer | Retry failed/transient requests. |
| Structured output / JSON | boolean | Must be enabled when supported by provider. |

The model must be configurable independently from other pipeline models.

Do not hard-code a specific provider/model in the business logic.

---

# 3. Metadata Strategies UI

Inside the existing **Metadata Strategies** section, add:

### Clinical Case

A selectable strategy:

```text
Clinical Case:
    Disabled
    Per QCM
    Global
```

Semantics:

- **Disabled**: do not run Clinical Case Checker.
- **Per QCM**: run the sequence-aware checker using each QCM as the current decision unit.
- **Global**: discover candidate case groups/chunks in parallel, process them concurrently, then run deterministic sequence-based reconciliation to obtain the final grouping.

If the user enables Clinical Case Checker, Step 2 must automatically include it after Step 3 completes.

If Clinical Case is Disabled, Step 2/Step 3 behavior remains unchanged.

---

# 4. Pipeline placement

Current workflow conceptually:

```text
INPUT XLSX
   |
   v
STEP 2
   |
   v
STEP 3 (already auto-triggered by Step 2)
   |
   v
DETECTED QCMS / METADATA
```

New workflow:

```text
INPUT XLSX
   |
   v
STEP 2
   |
   v
STEP 3
   |
   v
DETECTED QCMS + order
   |
   v
CLINICAL CASE CHECKER
   |
   +----------------------+
   |                      |
 PER QCM                GLOBAL
   |                      |
   v                      v
final groups        parallel discovery
                        |
                        v
                  parallel group workers
                        |
                        v
                    reconciliation
                        |
                        v
                 final case groups
```

Important: the Clinical Case Checker consumes **already detected/normalized QCMs from Step 3**. It must not create a second independent QCM extraction pipeline.

---

# 5. Core concept: active clinical case

During resolution, the system maintains an active clinical case context.

Example:

```text
Q1 = clinical case text
Q2 = asks diagnosis
Q3 = asks treatment
Q4 = asks complication
Q5 = unrelated question
Q6 = unrelated question
Q7 = new clinical case
```

The system creates:

```text
CASE_001
  source_qcm = Q1
  members = [Q1]
  status = active
```

Q2, Q3 and Q4 are then checked against CASE_001.

Q5 returns NO.

Q6 returns NO.

Two consecutive NO results close CASE_001 at Q4.

Q7 can then create CASE_002.

---

# 6. Critical boundary rule

The checker uses this rule exactly:

## 6.1 YES resets the NO counter

```text
YES -> consecutive_no = 0
```

## 6.2 One NO does not close the case

```text
YES
YES
YES
NO
```

The active case remains open.

## 6.3 Two consecutive NOs close the case

```text
YES
YES
YES
NO
NO
```

The active case ends immediately before the first NO in that consecutive pair.

Therefore:

```text
CASE_001 = [Q1, Q2, Q3]
Q4 = outside CASE_001
Q5 = outside CASE_001
```

The implementation should preserve the row order and should not physically delete QCMs.

Instead, persist a boundary such as:

```json
{
  "case_id": "CASE_001",
  "last_member_index": 3,
  "closed_at_index": 4
}
```

---

# 7. Important correction rule: NO -> YES

A single NO followed by YES is evidence that the NO may have been a model error or that the boundary was incorrectly interpreted.

Example:

```text
Q1 YES
Q2 YES
Q3 YES
Q4 YES
Q5 NO
Q6 YES
```

Required behavior:

1. Keep CASE_001 active.
2. Reset the NO counter when Q6 is YES.
3. Mark Q5 as a suspicious boundary decision.
4. Re-check Q5 with a small verification request using Q5 + case context + Q6.
5. Replace the provisional Q5 decision with the verification result.
6. Continue processing from Q6 onward.

This is a local correction and must not force reprocessing of the whole XLSX.

---

# 8. Why the system needs a Case Profile

Do **not** send all previously approved QCMs on every membership request.

Instead, when a new clinical case is detected, create a compact **Case Profile** once.

The Case Profile becomes the primary context for future membership checks.

Normal request:

```text
CASE PROFILE
+
CURRENT QCM
+
CURRENT QCM PROPOSITIONS
```

Do not send:

```text
CASE PROFILE
+
ALL PREVIOUS QCMS
+
CURRENT QCM
```

unless a special verification/recovery request is triggered.

---

# 9. Case Profile creation

The Case Profile is created when the system identifies a QCM as a **clinical case starter**.

For the starter QCM, the LLM must return both:

- the original/raw case context;
- a compact structured profile.

Example input:

```text
Q1:
A 52-year-old patient presents with severe pain, facial swelling,
fever and difficulty opening the mouth. Clinical examination shows...
```

Example output:

```json
{
  "is_clinical_case": true,
  "case_profile": {
    "raw_context": "A 52-year-old patient presents with severe pain...",
    "summary": "52-year-old patient with severe pain, swelling, fever and trismus.",
    "facts": {
      "age": 52,
      "sex": "unknown",
      "symptoms": [
        "severe pain",
        "facial swelling",
        "fever"
      ],
      "signs": [
        "trismus"
      ],
      "history": [],
      "tests": [],
      "findings": [],
      "diagnostic_context": "acute odontogenic infection"
    }
  }
}
```

The exact clinical fields may remain flexible; the important requirements are:

- preserve raw evidence;
- keep a compact normalized summary;
- keep structured facts when available;
- do not invent facts not present in the source case.

---

# 10. Case Profile lifecycle

A Case Profile has three states:

```text
CANDIDATE -> ACTIVE -> CLOSED
```

### Candidate

A QCM has been detected as a possible clinical case starter, but grouping is not yet established.

### Active

The system is currently testing following QCMs against the profile.

### Closed

Two consecutive NO results confirm the sequence boundary.

Never physically delete a profile. Keep it for debugging, auditability, and later verification.

---

# 11. Normal membership request

For each current QCM, send the following conceptual payload:

```text
SYSTEM:
You determine whether a QCM belongs to the active clinical case.

Definition:
A QCM belongs only when information from the clinical case is needed
or materially useful to answer the QCM correctly.

ACTIVE CASE PROFILE:
...

CURRENT QCM:
...

PROPOSITIONS:
A. ...
B. ...
C. ...
D. ...

Return JSON only.
```

Recommended response:

```json
{
  "belongs": true,
  "confidence": 0.98
}
```

For a clear negative:

```json
{
  "belongs": false,
  "confidence": 0.97
}
```

Optional short reason can be supported for debugging, but production responses should stay small to reduce latency and output cost.

---

# 12. Do include answer propositions

Clinical Case Checker should analyze:

```text
question text
+
answer propositions
+
clinical case context/profile
```

This matters because a QCM can look related to a case at the question-text level but become clearly case-dependent or case-independent when its propositions are considered.

Therefore the membership decision must receive the question and its answer choices.

Correct-answer labels should not normally be necessary for membership detection and should not be sent unless a future strategy explicitly requires them.

---

# 13. Membership decision must be independent from correctness

The checker answers:

> Does this QCM require the clinical case context?

It does **not** answer:

> Which proposition is correct?

It does not replace the existing QCM answer-validation logic.

---

# 14. Per-QCM mode

## 14.1 Processing model

The sequence is processed in original XLSX order.

Pseudo-flow:

```python
for qcm in qcms_in_order:
    if not active_case:
        detect_or_create_case_candidate(qcm)
        continue

    result = check_membership(active_case, qcm)

    if result.belongs:
        add_to_case(active_case, qcm)
        consecutive_no = 0

    else:
        consecutive_no += 1
        mark_provisional_no(qcm)

        if consecutive_no >= 2:
            close_case_before_first_provisional_no()
            active_case = None
            consecutive_no = 0
```

The implementation must additionally handle the NO -> YES correction rule.

---

# 15. Global mode — required parallel architecture

Global mode is designed to reduce wall-clock time by exploiting the fact that many QCMs belong to independent clinical-case regions.

The system must **not** simply send the entire XLSX as one giant LLM request.

Instead, global mode uses three phases:

```text
PHASE A — PARALLEL DISCOVERY
          |
          v
candidate clinical-case anchors / likely boundaries
          |
          v
PHASE B — PARALLEL GROUP WORKERS
          |
          v
independent case-range analysis
          |
          v
PHASE C — SEQUENCE RECONCILIATION
          |
          v
final case groups
```

---

# 16. Global Phase A — parallel discovery

Partition the detected QCMs into chunks of configurable size.

Example for 200 QCMs:

```text
Worker 1: Q1-Q25
Worker 2: Q26-Q50
Worker 3: Q51-Q75
Worker 4: Q76-Q100
Worker 5: Q101-Q125
Worker 6: Q126-Q150
Worker 7: Q151-Q175
Worker 8: Q176-Q200
```

These workers run concurrently up to `max_parallel_requests`.

Their purpose is not to make final grouping decisions. They discover likely:

- clinical-case starters;
- case-context boundaries;
- likely transition areas;
- candidate ranges.

Each worker must return original QCM indexes.

Example:

```json
{
  "chunk": {
    "start_index": 26,
    "end_index": 50
  },
  "case_candidates": [
    {
      "start_index": 31,
      "confidence": 0.96,
      "evidence": "new patient/case description appears"
    }
  ],
  "boundary_candidates": [
    {
      "after_index": 38,
      "confidence": 0.91
    }
  ]
}
```

---

# 17. Global Phase B — parallel group workers

Once candidate case anchors are known, construct candidate ranges between neighboring anchors.

Example:

```text
Q1  -> CASE_001 anchor
Q31 -> CASE_002 anchor
Q64 -> CASE_003 anchor
Q92 -> CASE_004 anchor
```

Create independent work units:

```text
GROUP_WORKER_001 = Q1-Q30
GROUP_WORKER_002 = Q31-Q63
GROUP_WORKER_003 = Q64-Q91
GROUP_WORKER_004 = Q92-end
```

Run these workers concurrently.

Each worker gets:

```text
case anchor / raw case context
+
case profile
+
its assigned QCM range
```

and resolves membership inside that candidate range using the same YES/NO boundary rules.

The workers must never mutate another worker's case state.

---

# 18. Why global mode can run in parallel

The key observation is that the ordering dependency exists **inside a case-range**, not across all QCMs once candidate anchors are known.

Therefore:

```text
CASE_A range ───────────────┐
                             |
CASE_B range ───────────────┼──> parallel
                             |
CASE_C range ───────────────┘
```

After the workers finish, the system reconciles neighboring boundaries.

This preserves the original sequence logic while reducing wall-clock latency.

---

# 19. Global Phase C — deterministic reconciliation

After parallel workers complete, sort all results by original QCM index.

Then apply the same global rules:

1. Preserve XLSX order.
2. Merge compatible case ranges.
3. If a worker says NO at the end of one group and the next group says YES, re-check the boundary.
4. If two consecutive NOs are confirmed, close the previous case before the first NO.
5. Never allow a worker result to overwrite a result from an unrelated range.

The reconciler is deterministic Python/application logic, not another LLM.

---

# 20. Example — normal sequence

Input:

```text
Q1  clinical case starts
Q2  case-dependent
Q3  case-dependent
Q4  case-dependent
Q5  unrelated
Q6  unrelated
Q7  new clinical case starts
Q8  case-dependent
Q9  case-dependent
```

LLM decisions:

```text
Q1 = CASE_001 starter
Q2 = YES
Q3 = YES
Q4 = YES
Q5 = NO
Q6 = NO
Q7 = CASE_002 starter
Q8 = YES
Q9 = YES
```

Final result:

```text
CASE_001 = [Q1, Q2, Q3, Q4]
CASE_002 = [Q7, Q8, Q9]
UNASSIGNED = [Q5, Q6]
```

---

# 21. Example — NO followed by YES

Input:

```text
Q1 YES
Q2 YES
Q3 YES
Q4 YES
Q5 NO
Q6 YES
Q7 YES
```

Initial interpretation:

```text
Q5 = provisional NO
```

When Q6 = YES:

```text
recheck Q5
```

Verification request:

```text
CASE PROFILE
+
RAW CASE CONTEXT
+
Q5
+
Q6
```

Suppose verification returns:

```json
{
  "belongs": true,
  "confidence": 0.94
}
```

Final result:

```text
CASE_001 = [Q1,Q2,Q3,Q4,Q5,Q6,Q7]
```

---

# 22. Example — parallel global processing

Suppose 200 QCMs contain five clinical cases:

```text
Q1-Q28    -> Case A
Q29-Q61   -> Case B
Q62-Q90   -> Case C
Q91-Q140  -> Case D
Q141-Q200 -> Case E
```

A sequential implementation may perform all LLM checks in one long chain.

Global mode instead discovers anchors:

```text
A = Q1
B = Q29
C = Q62
D = Q91
E = Q141
```

Then creates parallel work:

```text
Worker A -> Q1-Q28
Worker B -> Q29-Q61
Worker C -> Q62-Q90
Worker D -> Q91-Q140
Worker E -> Q141-Q200
```

All workers can execute concurrently up to the configured concurrency limit.

Final reconciliation orders and merges the results.

---

# 23. Data model

Recommended logical entities:

## ClinicalCase

```json
{
  "case_id": "CASE_001",
  "source_qcm_index": 1,
  "status": "active",
  "profile": {},
  "member_qcm_indexes": [1,2,3,4],
  "first_member_index": 1,
  "last_member_index": 4,
  "confidence": 0.98
}
```

## MembershipDecision

```json
{
  "qcm_index": 5,
  "case_id": "CASE_001",
  "belongs": false,
  "confidence": 0.91,
  "decision_type": "provisional",
  "verified": false
}
```

After verification:

```json
{
  "qcm_index": 5,
  "case_id": "CASE_001",
  "belongs": true,
  "confidence": 0.94,
  "decision_type": "verified",
  "verified": true
}
```

---

# 24. LLM task types

The implementation should distinguish at least these task types:

### TASK A — Case starter detection

Purpose: determine whether a QCM introduces a new clinical case and extract its context.

### TASK B — Membership check

Purpose: determine whether the current QCM depends on the active case.

### TASK C — Boundary verification

Purpose: re-check a provisional NO when the following QCM is YES.

### TASK D — Optional global candidate discovery

Purpose: detect likely anchors and boundaries for parallel global processing.

These tasks may use the same configured model but must have separate prompts and response schemas.

---

# 25. Recommended JSON contracts

## Case starter

```json
{
  "is_clinical_case": true,
  "case_profile": {
    "raw_context": "...",
    "summary": "...",
    "facts": {}
  }
}
```

## Membership

```json
{
  "belongs": true,
  "confidence": 0.98
}
```

## Boundary verification

```json
{
  "belongs": true,
  "confidence": 0.94,
  "verified_against_next_qcm": true
}
```

## Discovery

```json
{
  "case_candidates": [],
  "boundary_candidates": []
}
```

All responses must be validated before being accepted by the application.

---

# 26. Error handling

The LLM layer must distinguish:

```text
success
invalid JSON
provider timeout
rate limit
network error
provider unavailable
```

Retry transient failures using the configured retry count.

Do not silently convert an LLM error into `belongs=false`.

For a failed decision, mark the decision as:

```text
status = unresolved
```

and let the application apply the configured fallback policy.

Recommended fallback:

- preserve the QCM in sequence;
- do not close the case solely because of a technical failure;
- optionally retry with fallback model/provider.

---

# 27. Concurrency rules

Global mode must support bounded concurrency.

Use:

```text
max_parallel_requests
```

rather than unlimited `asyncio.gather()` / task spawning.

Example:

```text
max_parallel_requests = 8
```

means at most eight active LLM requests for the Clinical Case Checker at once.

The implementation must also respect provider/API rate limits.

---

# 28. Idempotency and resume support

A Clinical Case Checker run should be resumable.

Persist:

- run ID;
- checker mode;
- model configuration ID;
- QCM index;
- case ID;
- decision;
- confidence;
- profile;
- worker/chunk ID;
- processing status.

If a run stops halfway through, completed decisions should not be re-requested unnecessarily.

---

# 29. Logging / debugging

For every decision, retain minimal debug metadata:

```json
{
  "run_id": "...",
  "qcm_index": 25,
  "case_id": "CASE_002",
  "model": "configured-model",
  "task": "membership",
  "belongs": true,
  "confidence": 0.97,
  "latency_ms": 412,
  "retry_count": 0
}
```

Do not store verbose chain-of-thought. Store concise reasons only when useful for debugging/UI.

---

# 30. Cost and latency optimization principles

The architecture is designed to reduce cost without removing LLM semantic judgment.

1. Create the Case Profile once per clinical case.
2. Send Case Profile + current QCM instead of all previous QCMs.
3. Keep normal membership output extremely small.
4. Run independent global case ranges concurrently.
5. Use verification requests only for suspicious boundaries.
6. Reuse cached decisions when the same run/input/model/configuration has already been processed.
7. Keep model configuration external to business logic so low-latency/low-cost OpenRouter models can be swapped without code changes.

The system must not depend on one specific model vendor.

---

# 31. Important distinction: per-QCM vs global

## Per QCM

Priority:

```text
maximum sequence fidelity
simple implementation
local correction
```

The checker follows the XLSX order directly.

## Global

Priority:

```text
lower wall-clock latency
parallel execution
large XLSX scalability
```

The checker discovers independent candidate ranges, processes them concurrently, then applies deterministic reconciliation.

Both modes must produce the same final data model:

```text
ClinicalCase[]
+
MembershipDecision[]
```

Only the processing strategy differs.

---

# 32. UI behavior

When Step 2 is launched:

```text
Step 2 started
   |
   v
Step 3 auto-runs
   |
   v
Detected QCMs ready
   |
   v
if Clinical Case != Disabled:
       start Clinical Case Checker
   |
   v
finish Step 2 workflow
```

The UI should display status such as:

```text
Clinical Case Checker
Mode: Global
Model: configured model
Progress: 87 / 200 QCMs
Active groups: 5
Parallel workers: 8
Status: Processing
```

At completion:

```text
Clinical Case Checker: Completed
Clinical cases detected: 5
Grouped QCMs: 162
Unassigned QCMs: 38
Verification corrections: 7
```

Exact UI styling should follow the existing application design system.

---

# 33. Output expected from the checker

The checker should produce a machine-readable result similar to:

```json
{
  "clinical_case_strategy": "global",
  "cases": [
    {
      "case_id": "CASE_001",
      "source_qcm_index": 1,
      "member_qcm_indexes": [1,2,3,4],
      "first_member_index": 1,
      "last_member_index": 4,
      "profile": {
        "summary": "...",
        "facts": {}
      }
    },
    {
      "case_id": "CASE_002",
      "source_qcm_index": 7,
      "member_qcm_indexes": [7,8,9],
      "first_member_index": 7,
      "last_member_index": 9,
      "profile": {
        "summary": "...",
        "facts": {}
      }
    }
  ],
  "unassigned_qcm_indexes": [5,6],
  "decisions": []
}
```

This output must be available to later pipeline stages.

---

# 34. Implementation constraints

Do not redesign unrelated parts of the current QCM pipeline.

Do not create a separate duplicate XLSX parser.

Do not modify the meaning of existing Step 2 or Step 3 outputs.

The Clinical Case Checker should consume their existing normalized QCM representation.

Do not couple Clinical Case Checker to a specific model/provider.

Do not put sequence logic inside the LLM prompt as the only enforcement mechanism.

The application must enforce:

```text
order
consecutive NO counting
NO -> YES correction
case closure
worker isolation
reconciliation
```

---

# 35. Recommended implementation modules

Suggested structure; adapt names to the current codebase instead of creating unnecessary duplication:

```text
clinical_case_checker/
    __init__.py
    service.py
    models.py
    prompts.py
    parser.py
    sequential.py
    global_mode.py
    workers.py
    reconciler.py
    profile.py
    llm_client.py
    schemas.py
    persistence.py
```

Responsibilities:

- `service.py` — public orchestration entry point.
- `models.py` — case, profile, decision, run models.
- `prompts.py` — task-specific prompts.
- `parser.py` — convert existing Step 3 QCM representation into checker input.
- `sequential.py` — Per QCM state machine.
- `global_mode.py` — global orchestration.
- `workers.py` — parallel discovery/group workers.
- `reconciler.py` — deterministic global merge.
- `profile.py` — profile extraction/normalization.
- `llm_client.py` — model/provider abstraction.
- `schemas.py` — strict JSON validation.
- `persistence.py` — run/decision/profile persistence.

The coding agent should reuse existing project conventions and avoid introducing these exact files if equivalent modules already exist.

---

# 36. Pseudocode — complete orchestration

```python
def run_clinical_case_checker(qcms, config):
    if config.strategy == "disabled":
        return None

    if config.strategy == "per_qcm":
        return run_per_qcm_mode(qcms, config)

    if config.strategy == "global":
        discovery = run_parallel_discovery(qcms, config)
        ranges = build_candidate_ranges(qcms, discovery)
        worker_results = run_parallel_group_workers(ranges, config)
        return reconcile_global_results(worker_results, qcms, config)
```

Per-QCM:

```python
def run_per_qcm_mode(qcms, config):
    active_case = None
    consecutive_no = 0
    provisional_nos = []
    results = []

    for qcm in qcms:
        if active_case is None:
            starter = detect_case_start(qcm, config)

            if starter.is_clinical_case:
                active_case = create_case(starter, qcm)
                results.append(assign(qcm, active_case))
            else:
                results.append(unassigned(qcm))
            continue

        decision = check_membership(active_case.profile, qcm, config)

        if decision.belongs:
            if provisional_nos:
                verify_previous_no(provisional_nos[-1], qcm, active_case, config)
                provisional_nos.clear()

            active_case.add(qcm)
            consecutive_no = 0
            results.append(assign(qcm, active_case))
        else:
            consecutive_no += 1
            provisional_nos.append(qcm)
            results.append(provisional_unassigned(qcm, active_case))

            if consecutive_no >= 2:
                close_case_at_previous_member(active_case, qcm)
                active_case = None
                consecutive_no = 0
                provisional_nos.clear()

                # qcm remains outside the closed case.

    return finalize(results)
```

The exact implementation may differ, but the observable behavior must remain the same.

---

# 37. Case starter detection details

The system must distinguish:

```text
ordinary standalone QCM
vs
clinical-case starter QCM
```

Signals may include:

- patient age/sex;
- presenting complaint;
- symptoms/signs;
- examination findings;
- history;
- imaging/laboratory findings;
- narrative patient description.

These are only signals. The final decision is model-based according to the configured strategy.

A case profile should not be created merely because a QCM mentions a disease name.

---

# 38. Definition of “belongs” for the LLM

Use this exact conceptual definition in the prompt:

> A QCM belongs to the active clinical case when the information contained in that case is necessary or materially useful to answer the QCM. If the QCM can be answered correctly without using the case-specific information, classify it as not belonging, even if the QCM is about the same medical subject.

This avoids confusing:

```text
same topic
```

with:

```text
same clinical case
```

---

# 39. Security / reliability

Treat the XLSX and QCM text as untrusted input.

The model prompt must make the clinical case and QCM content data, not instructions.

Validate all model output against JSON schema.

Never execute content returned by the LLM.

---

# 40. Acceptance criteria

The feature is complete only when all of the following are true:

### Configuration

- [ ] `Clinical Case Checker` exists in Model Configuration.
- [ ] Model/provider/configuration is independent and configurable.
- [ ] `Clinical Case` exists in Metadata Strategies.
- [ ] User can select `Disabled`, `Per QCM`, or `Global`.

### Pipeline

- [ ] Running Step 2 still automatically runs Step 3.
- [ ] Clinical Case Checker starts after Step 3 output is available.
- [ ] Disabled mode changes nothing.

### Per QCM

- [ ] QCMs are processed in original order.
- [ ] Case Profile is created once for each detected case.
- [ ] Membership requests use Case Profile + current QCM + propositions.
- [ ] One NO does not close a case.
- [ ] Two consecutive NOs close a case.
- [ ] NO -> YES triggers correction/verification of the previous NO.

### Global

- [ ] Candidate discovery is parallelized.
- [ ] Independent candidate group ranges are processed in parallel.
- [ ] Concurrency is bounded.
- [ ] Results are reconciled by original XLSX index.
- [ ] Boundary conflicts are rechecked.
- [ ] Final grouping is deterministic after reconciliation.

### Data / reliability

- [ ] Results are persisted and resumable.
- [ ] LLM errors are distinguishable from NO decisions.
- [ ] JSON output is schema-validated.
- [ ] Existing Step 2/Step 3 behavior outside this feature is preserved.

---

# 41. Final architecture summary

The intended architecture is:

```text
                           USER
                            |
                            v
                  +----------------------+
                  | Model Configuration   |
                  | Clinical Case Checker |
                  +----------------------+
                            |
                            v
                  +----------------------+
                  | Metadata Strategies   |
                  | Clinical Case:        |
                  | Disabled / Per QCM   |
                  | / Global              |
                  +----------------------+
                            |
                            v
                          STEP 2
                            |
                            v
                          STEP 3
                            |
                            v
                  DETECTED / NORMALIZED QCMS
                            |
                            v
                +---------------------------+
                | Clinical Case Checker     |
                +---------------------------+
                    /                     \
                   /                       \
            PER QCM                       GLOBAL
              |                              |
              v                              v
       sequential state              parallel discovery
       machine + LLM                    |
              |                         v
              |                    parallel ranges
              |                         |
              |                         v
              |                    reconciliation
              |                         |
              +-----------+-------------+
                          |
                          v
                  FINAL CLINICAL CASES
                          |
                          v
                   DOWNSTREAM STEPS
```

The central design principle is:

> **LLM decides semantic membership; application code decides sequence, boundaries, concurrency, persistence, and reconciliation.**

The Case Profile is created once per case and reused. Global mode parallelizes independent candidate case ranges, while final reconciliation restores the exact sequence-aware logic of the XLSX.
