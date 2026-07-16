# Phase 1 — SJSU General Scholarship

Phase 1 is deliberately narrow: it supports **only the SJSU General Scholarship**,
across both the **25-26** and **26-27** datasets, using **one shared rubric** and
**one shared prompt**. It is the foundation for broader scholarship scoring later.

**Specialized / department scholarships (Engineering, Lurie/Education, Physics)
are NOT supported in phase 1.** Config stubs exist for them (clearly marked
`supported: False`) purely to document the extension path — they are never parsed
or scored.

Goal: reduce first-pass manpower for general scholarship filtering by producing a
consistent AI first-read that a human reviewer can build on.

## Production scoring flow (no human scores involved)

```
.xlsx uploaded to s3://<bucket>/data/
        │  S3 event
        ▼
Lambda: parse-applications        (SJSU General workbooks only)
        │  writes normalized records
        ▼
DynamoDB: sjsu-applications        (PK = application_key)
        │  DynamoDB Stream (NEW_IMAGE), batch size ~5
        ▼
Lambda: score-applications         (shared rubric + prompt, Bedrock, strict JSON)
        │  writes score records
        ▼
DynamoDB: sjsu-scores              (PK = application_key)
```

Production scoring depends only on parsed application content + the shared rubric.
It never reads historical human score files.

## Parsed application schema (phase 1)

Written to `sjsu-applications`, keyed by a deterministic `application_key`:

| Field | Notes |
|-------|-------|
| `application_key` | **PK** = `sjsu_general#{year}#{student_uuid}` (deterministic, idempotent) |
| `student_uuid` | from the Excel `Student` column |
| `availability_id` | raw scholarship label from the sheet (metadata only) |
| `candidate_key` | last 12 hex of `student_uuid`; used for evaluation-mode joins |
| `scholarship_scope` | always `sjsu_general` in phase 1 |
| `year` | `25-26` or `26-27` |
| `student_name` | null in this anonymized data |
| `gpa`, `academic_program`, `academic_level`, `major` | structured fields |
| `qa_pairs` | list of `{question_id, question, answer}` |
| `source` | `{file_name, sheet_name, row_number}` provenance |
| `status` | `parsed` |

There is **no `rubric_id`** in the phase-1 schema — a single shared rubric is used,
so the field carried no information.

## Scores schema

Written to `sjsu-scores`, keyed by `application_key`:

| Field | Notes |
|-------|-------|
| `application_key` | **PK** (1:1 with the application) |
| `criterion_scores` | list of `{criterion, score, reasoning, evidence[]}` |
| `weighted_total` | sum of criterion scores (max 15) |
| `reasoning_summary` | 1–2 sentence overall justification |
| `confidence` | 0.0–1.0 |
| `model_id` | Bedrock model used |
| `scholarship_scope`, `year` | copied from the application |
| `status` | `scored` or `score_failed` |
| `scored_at` | ISO timestamp |

## Shared prompt / rubric

- One rubric file: `lambdas/score-applications/sjsu_general_rubric.md`
- One prompt path: `lambdas/score-applications/prompt.py` (`build_system_prompt`)
- No multi-rubric branching. Both years use the same rubric and prompt.

## Evaluation mode (separate from production)

Evaluation mode (`evaluation/`) compares model output to **historical human
scores** and is used only for model selection — it is NOT part of production
scoring.

- Narrowed to SJSU General only (`EVAL_SCOPE_RUBRIC_IDS = {"sjsu-general"}`).
- Deterministic joins only: `candidate_key` = last 12 hex of the student UUID ==
  the score sheet's `Candidate` column.

### Scoring support vs human-comparison support

| Dataset | Production scoring | Human-comparison (eval) |
|---------|--------------------|-------------------------|
| SJSU General **26-27** | ✅ supported | ✅ supported (score sheet has a `Candidate` join key) |
| SJSU General **25-26** | ✅ supported | ❌ **not supported** — the 25-26 score sheet has **no `Candidate` column**, so there is no deterministic join to human scores |

The 25-26 application data can still be scored in production; it simply cannot be
evaluated against human scores because the human score file lacks a reliable join
key. This is verified by the evaluation dry-run, which excludes the 25-26 sheet
with reason *"no Candidate column (no deterministic join key)"*.

## What remains extensible

- New scholarships: add a config (like `SJSU_GENERAL_CONFIG`) + a rubric file; the
  key/stream/scoring machinery is scholarship-agnostic.
- `scholarship_scope` + the `scope-year-index` GSI already allow multiple scopes to
  coexist in the same tables.
- The scoring Lambda's `MODEL_ID` is env-configurable.
