# SJSU General Scholarship Phase 1 Goal

## Objective

Implement a **phase-1 production pipeline** for **SJSU General Scholarship** applications only.

The system should allow admins to:
- upload an application `.xlsx`
- parse it into structured JSON
- store it in DynamoDB
- trigger Bedrock scoring
- store the AI score output
- eventually view a first-pass AI score and compare it against historical human scoring when that comparison data exists

This phase is specifically about reducing the manpower needed for **first-pass candidate filtering and scoring** for the **SJSU General Scholarship** workflow.

## Scope

### In scope
- `SJSU General Scholarship` only
- both `25-26` and `26-27` application exports
- one shared rubric for SJSU General
- one shared prompt template for SJSU General
- deterministic parse -> store -> score pipeline
- production scoring flow
- evaluation flow kept separate from production scoring

### Out of scope
- department-specific scholarships
- claims that specialized scholarships are supported
- final award decision automation
- multi-rubric routing in the active phase-1 path
- overly generic architecture that slows down current delivery

### Important note on extensibility
Architecture should remain extensible for future scholarship types, but the **active code path** should be simplified for SJSU General only.

Keep placeholders/config stubs for specialized scholarships, but clearly mark them unsupported in phase 1.

## Product statement

We are building a foundation for scholarship scoring automation by delivering a pipeline where admins can upload **SJSU General Scholarship** files and receive AI-generated first-pass scores, with the ability to compare those scores to historical human scoring where deterministic joins are available.

## Two distinct flows

### 1. Production scoring flow
- admin uploads SJSU General application `.xlsx`
- parser converts rows into normalized JSON
- records are written to DynamoDB
- scoring Lambda calls Bedrock
- Bedrock returns structured scoring JSON
- scores are written to a scores table
- UI can read and display first-pass AI scores

### 2. Evaluation / historical comparison flow
- application `.xlsx` plus human score `.xlsx`
- deterministic join only
- Bedrock scores applications without seeing human scores
- evaluation code compares AI outputs to human criterion averages and weighted totals
- report/HTML output shows AI vs human comparison

**Do not couple production scoring to historical human score files.**

## Current business assumptions

- Stakeholders are comfortable focusing only on **SJSU General Scholarship** right now.
- Stakeholders do **not** currently understand the scoring process well enough for specialized scholarships.
- The most important operational pain point is reducing manual effort in first-pass scoring/filtering for general scholarships.
- The same prompt template should be used across both SJSU General years.
- The same rubric should be used across both SJSU General years.

## Data assumptions

### Application files
Application exports contain:
- `Student` (anonymized student UUID)
- `AvailabilityId_t`
- SJSU General essay / profile fields

### Human scoring files
Historical score files may or may not have a deterministic join key.

Use deterministic joins only.

### Key identity concepts

#### `student_uuid`
The full anonymized `Student` value from the application export.

#### `candidate_key`
A derived join key used for historical score comparison.

Definition:
- remove hyphens from `student_uuid`
- uppercase
- take the last 12 hex characters

Example:
- `student_uuid`: `3de3a742-4fd7-44db-9a8d-1b1d3def7b3b`
- `candidate_key`: `1B1D3DEF7B3B`

This is useful because some human score exports use a `Candidate` field that corresponds to that derived value.

#### `availability_id`
Keep as source metadata only.

Do **not** treat `availability_id` as a unique per-application key.
It may represent the scholarship availability name and can repeat across many rows.

## Required refactor direction

## 1. Simplify the parsed application schema

The phase-1 parsed schema should be specific to SJSU General and should not carry unnecessary multi-rubric abstractions.

Suggested shape:

```json
{
  "application_key": "sjsu_general#26-27#32bd3c1f-bb96-4de3-ac91-0020292b6223",
  "student_uuid": "32bd3c1f-bb96-4de3-ac91-0020292b6223",
  "availability_id": "SJSU General Scholarship",
  "candidate_key": "0020292B6223",
  "scholarship_scope": "sjsu_general",
  "year": "26-27",
  "student_name": "32bd3c1f-bb96-4de3-ac91-0020292b6223",
  "gpa": 3.8,
  "academic_program": "...",
  "academic_level": "...",
  "major": "...",
  "qa_pairs": [
    {
      "question_id": "career_goals",
      "question": "...",
      "answer": "..."
    }
  ],
  "source": {
    "file_name": "...",
    "sheet_name": "...",
    "row_number": 42
  },
  "status": "parsed"
}
```

### Requirements
- remove `rubric_id` from the active phase-1 schema
- add `scholarship_scope = "sjsu_general"`
- use a deterministic `application_key`
- keep `student_uuid`
- keep `candidate_key`
- keep `year`
- keep only fields needed for SJSU General scoring and comparison

## 2. Refactor DynamoDB model

Use a simpler phase-1 DynamoDB design.

### Applications table
- PK: `application_key`
- store parsed application payload and metadata

Recommended key format:

```text
application_key = "sjsu_general#{year}#{student_uuid}"
```

This avoids collisions where the same student appears in multiple years.

### Scores table
- PK: `application_key`
- stores model-generated first-pass score output

Suggested score item shape:

```json
{
  "application_key": "sjsu_general#26-27#32bd3c1f-bb96-4de3-ac91-0020292b6223",
  "scholarship_scope": "sjsu_general",
  "year": "26-27",
  "criterion_scores": [
    {
      "criterion": "Essay Response: SJSU Journey",
      "score": 3,
      "reasoning": "...",
      "evidence": [
        {
          "question_id": "sjsu_journey",
          "quote": "..."
        }
      ]
    }
  ],
  "weighted_total": 73,
  "reasoning_summary": "...",
  "model_id": "...",
  "status": "scored"
}
```

### Notes
- keep the schema simple
- do not keep active multi-rubric routing fields if they are unused
- preserve enough metadata for UI and evaluation

## 3. Prompt / rubric handling

Simplify prompt loading for phase 1:
- one prompt template for SJSU General
- one rubric file for SJSU General
- same prompt + same rubric across both years

The active scoring code path should not branch across multiple scholarship types for phase 1.

## 4. Bedrock scoring Lambda

Implement or scaffold the production scoring Lambda.

### Expected behavior
- triggered after parsed application records are available
- processes records in small batches
- target batch size: `5`
- calls Bedrock using:
  - parsed SJSU General application content
  - SJSU General prompt
  - SJSU General rubric
- output must be strict JSON
- writes results to the scores table

### Important
- do not overload Bedrock with uncontrolled one-record-per-trigger fanout
- use a small-batch event-driven design

### Acceptable implementation direction
- DynamoDB Streams -> Lambda with batch size ~5
- or another minimal reliable batching mechanism if clearly simpler

### Production scoring input must NOT include
- historical human scores
- evaluation labels
- any human review scores

## 5. Evaluation mode limitations

Keep evaluation mode explicit and honest.

### Required behavior
- evaluate SJSU General only
- deterministic joins only
- if `25-26` historical score joins are not deterministic, document that clearly
- clearly separate:
  - scoring support
  - human-comparison support

## 6. Specialized scholarships

Keep config placeholders for specialized scholarships, but:
- mark them unsupported
- skip them cleanly
- do not pretend they are operational in phase 1

## 7. Documentation updates

Update docs/readme/context so they state:
- phase 1 supports SJSU General only
- this is a foundation for future scholarship scoring expansion
- specialized scholarships are intentionally unsupported for now
- the primary business goal is reducing first-pass manual scoring workload

## Acceptance criteria

This goal is complete when:

1. Parsed application schema is simplified for SJSU General phase 1
2. DynamoDB keys and tables reflect the simplified phase-1 design
3. `application_key` is deterministic
4. `candidate_key` is preserved for historical joins
5. Prompt/rubric handling is simplified to one SJSU General path
6. A Bedrock scoring Lambda exists or is clearly scaffolded
7. Batch processing is designed around about `5` applications at a time
8. Production scoring path does not depend on human score files
9. Docs clearly explain supported vs unsupported scope

## Suggested implementation order

1. Refactor parsed schema
2. Refactor DynamoDB table/item structure
3. Refactor prompt/rubric loading for SJSU General only
4. Implement/scaffold Bedrock scoring Lambda
5. Wire batching strategy
6. Update docs

## Non-goals

Do not spend time on:
- making all scholarship types work now
- solving final award decision logic
- building a fully generalized cross-rubric platform before phase 1 works
- coupling evaluation logic into production scoring

## Summary

Build a clean, phase-1, SJSU-General-only pipeline:

`xlsx upload -> parse -> DynamoDB -> Bedrock scoring -> scores table -> UI`

and keep historical human comparison as a separate evaluation path, not a runtime dependency.
