# Parser — Memory / Change Log

## 2026-07-14: Config-Driven qa_pairs Refactor

### What Changed

The parser output was refactored from a hardcoded `essays` object to a config-driven `qa_pairs` array.

**Before:**
```python
# parser.py had hardcoded essay routing:
elif normalized_field == "essay_career_goals":
    record["essays"]["career_goals"] = value
elif normalized_field == "essay_challenge_or_mistake":
    record["essays"]["challenge_or_mistake"] = value
# ...etc
```

**After:**
```python
# parser.py has ZERO essay knowledge. It just loops:
for essay_def in config["essay_fields"]:
    # try column, build qa_pair from config metadata
```

---

### Why

1. The LLM scoring step needs `{question, answer}` pairs — not a fixed object with field names it has to interpret.
2. Different scholarships have different questions. Hardcoding means parser changes every time a scholarship is added.
3. Config-driven means adding a new scholarship or question is just a new entry in `scholarship_config.py`.

---

### Files Modified

| File | What Changed |
|---|---|
| `scholarship_config.py` | Split into `column_map` (non-essay structured fields only) + `essay_fields` (list of essay definitions). Each essay field has `raw_column`, `question_id`, `question`, and optional `topic`/`alt_columns`. |
| `parser.py` | Removed all `essay_`/`ESSAY_FIELD_PREFIX` logic. `normalize_row()` now iterates `config["essay_fields"]` to build `qa_pairs`. No question text or IDs exist in parser.py. |

---

### Config Shape (scholarship_config.py)

```python
{
    "scholarship_type": "College of Engineering Dean's Student Scholarship",
    "rubric_id": "coeng-deans",
    "column_map": {
        # Non-essay fields ONLY
        "AvailabilityId_t": "availability_id",
        "Student": "student_name",
        "PS_Cumulative GPA": "gpa",
    },
    "essay_fields": [
        {
            "raw_column": "FASO_General_Career Goals",   # Excel column name
            "question_id": "career_goals",               # stable ID for downstream scoring
            "question": "What are your career goals?",   # full question text sent to LLM
        },
        {
            "raw_column": "COENG_Leadership",
            "question_id": "department_specific",
            "question": "Describe your leadership experience...",
            "topic": "Leadership",                       # optional — included in output when present
        },
    ],
}
```

---

### Output Shape (per application)

```json
{
  "application_id": "uuid",
  "scholarship_type": "College of Engineering Dean's Student Scholarship",
  "rubric_id": "coeng-deans",
  "year": "25-26",
  "student_name": "anonymized-uuid",
  "availability_id": "Engineering Dean's Student Scholarship",
  "gpa": 3.7,
  "self_reported_gpa": null,
  "academic_program": null,
  "academic_level": null,
  "major": null,
  "qa_pairs": [
    {
      "question_id": "career_goals",
      "question": "What are your career goals?",
      "answer": "..."
    },
    {
      "question_id": "challenge_or_mistake",
      "question": "Describe a challenge or mistake and what you learned from it.",
      "answer": "..."
    },
    {
      "question_id": "department_specific",
      "question": "Describe your leadership experience...",
      "answer": "...",
      "topic": "Leadership"
    }
  ],
  "source": {
    "file_name": "College of Engineering Dean_s Student Scholarship 25-26 ad hoc report.xlsx",
    "sheet_name": "ScholarshipManagerData (26)",
    "row_number": 2
  }
}
```

---

### How It Works (step by step)

1. `parser.py` reads an xlsx from S3
2. Identifies the scholarship type from the filename → gets the config
3. For each row:
   - Iterates `config["column_map"]` → fills structured fields (`student_name`, `gpa`, etc.)
   - Iterates `config["essay_fields"]` → for each essay definition:
     - Tries `raw_column` first, then any `alt_columns` (handles naming inconsistencies)
     - If a non-empty answer is found, builds a qa_pair `{question_id, question, answer, ?topic}`
     - Appends to `record["qa_pairs"]`
   - Skips the entire record if `student_name` is null
4. Outputs grouped JSON files by rubric_id + year

---

### Edge Cases Handled

| Case | How |
|---|---|
| Lurie 25-26 uses `COED_Career Goals`, 26-27 uses `LCOE_Career Goals` | `alt_columns` in essay_fields — parser tries primary then alternates |
| Physics 26-27 missing `FASO_General_Challenge or Mistake` column | Essay just doesn't appear in qa_pairs (skipped gracefully) |
| Physics 26-27 missing `AvailabilityId_t` | `availability_id` stays null |
| Empty/null essay answers | Skipped — not included in qa_pairs |
| GPA of 0.0 in first Engineering row | Stored as-is (may be a data quality issue to flag later) |

---

### How to Add a New Scholarship

1. Open `scholarship_config.py`
2. Add a new key to `SCHOLARSHIP_CONFIGS` matching the filename pattern
3. Define `column_map` for non-essay structured fields
4. Define `essay_fields` with one entry per essay question
5. Run `python parser.py --sample 2` to verify

No changes to `parser.py` needed.


---

## 2026-07-14: Lambda Event-Driven Parse + DynamoDB Setup (Samson Chat)

### Context

Discussed the full architecture for the SJSU scholarship pipeline — decided on an event-driven Lambda approach with DynamoDB instead of Bedrock batch (DynamoDB is faster to demo). Then deployed the infrastructure.

### Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Storage | DynamoDB over S3/Bedrock batch | Faster path to a working demo; dashboard can query directly |
| Applications PK | `availability_id` | Stable ID from xlsx — idempotent on re-parse (no duplicates) |
| Applications GSI | `rubric_id` + `availability_id` | Query all apps for a specific scholarship |
| Scores PK | `availability_id` | 1:1 with application record |
| Scoring approach | Decoupled — separate Lambda triggered manually | Parse and score are independent; no timeout risk |
| Infra-as-code | Deferred (SAM template removed) | Manual deploy for now; will add SAM later when stable |
| Parse trigger | S3 event notification on `data/*.xlsx` | Event-driven, no polling |

### What Was Deployed to AWS (account 606263411016, us-west-2, profile: Samson)

| Resource | Name/ARN | Details |
|----------|----------|---------|
| S3 bucket (test) | `sjsu-scholarship-test-parse-trigger` | Has `data/` prefix; S3 event notification configured |
| Lambda function | `sjsu-parse-applications` | Python 3.12, 512MB, 5 min timeout, handler: `handler.handler` |
| IAM role | `sjsu-parse-lambda-role` | Trust: Lambda service. Policies: CloudWatch logs, S3 GetObject on `data/*`, DynamoDB PutItem/BatchWriteItem on `sjsu-applications` |
| DynamoDB table | `sjsu-applications` | PK: `availability_id` (S), GSI: `rubric-id-index` (rubric_id HASH + availability_id RANGE), PAY_PER_REQUEST |
| DynamoDB table | `sjsu-scores` | PK: `availability_id` (S), PAY_PER_REQUEST |
| S3 → Lambda trigger | Event notification | Fires on `s3:ObjectCreated:*` with prefix `data/` and suffix `.xlsx` |

### Git Branch

`feat/lambda-parse-trigger` — branched from `feat/parser`

### Files Created

```
lambdas/parse-applications/
├── handler.py              # Lambda entry point (S3 event → parse xlsx → batch write to DynamoDB)
├── scholarship_config.py   # Scholarship type configs (copied from Parser/, uses old essays format)
├── requirements.txt        # pandas==2.2.3, openpyxl==3.1.5, boto3==1.35.0
├── package/                # Linux-compatible dependencies (built with pip --platform manylinux2014_x86_64)
└── deployment.zip          # Zipped package uploaded to Lambda

tasks_samson.md             # Full task breakdown for the pipeline (may need re-creation due to OneDrive sync)
```

### How the Lambda Works

1. S3 event fires when `.xlsx` lands in `data/`
2. Lambda extracts bucket + key from event
3. Validates: must be `data/*.xlsx`, not a temp `~$` file
4. Calls `parse_file()` → identifies scholarship config from filename, reads xlsx, normalizes rows
5. `write_to_dynamodb()` → batch writes records using `availability_id` as PK
6. Adds provenance: `source_file`, `parsed_at` (ISO timestamp)
7. Strips None values (DynamoDB doesn't accept them)
8. Raises on error (lets Lambda retry)

### ⚠️ Known Issue: Lambda Uses Old Parser Format

The Lambda's `scholarship_config.py` uses the **old `essays` dict format** (hardcoded essay field routing), not the newer `qa_pairs`/`essay_fields` config-driven format documented above. This needs to be synced once the `qa_pairs` parser is finalized and tested.

### How to Test

```bash
# Upload a test xlsx (filename must match a scholarship config key)
aws s3 cp "SJSU General Scholarship 26-27 ad hoc report.xlsx" s3://sjsu-scholarship-test-parse-trigger/data/ --profile Samson

# Check DynamoDB for records
aws dynamodb scan --table-name sjsu-applications --profile Samson --region us-west-2

# Check Lambda logs
aws logs tail /aws/lambda/sjsu-parse-applications --profile Samson --region us-west-2
```

### Next Steps

1. Sync Lambda parser with the `qa_pairs` format (once finalized)
2. Test end-to-end: upload xlsx → verify records in DynamoDB
3. Build scoring Lambda (reads from `sjsu-applications`, calls Bedrock, writes to `sjsu-scores`)
4. Wire dashboard API to read from both tables
5. (Later) Add SAM template for reproducible deployments


---

## 2026-07-14: Lambda Pipeline — FINAL WORKING STATE (supersedes above)

The section above describes the *initial plan*. During implementation, several decisions
changed after hitting real bugs. This section is the source of truth for the final state.

### Final Deployed Infrastructure (account 606263411016, us-west-2, profile: Samson)

| Resource | Name | Final Config |
|----------|------|--------------|
| S3 bucket (test) | `sjsu-scholarship-test-parse-trigger` | `data/` prefix; event notification on `s3:ObjectCreated:*`, prefix `data/`, suffix `.xlsx` |
| Lambda | `sjsu-parse-applications` | Python 3.12, 512MB, 300s timeout, handler `handler.handler` |
| IAM role | `sjsu-parse-lambda-role` | CloudWatch logs + S3 GetObject on `data/*` + DynamoDB PutItem/BatchWriteItem on `sjsu-applications` |
| DynamoDB | `sjsu-applications` | **PK: `application_id` (UUID)**, GSI `rubric-id-index` (rubric_id HASH + application_id RANGE), PAY_PER_REQUEST |
| DynamoDB | `sjsu-scores` | PK: `availability_id` (S), PAY_PER_REQUEST — not used yet |

### KEY DECISION CHANGE: Primary Key

- **Original plan:** `availability_id` as PK (from xlsx, for idempotency).
- **Reality:** The Lurie spreadsheet stores the SCHOLARSHIP NAME in the `AvailabilityId_t`
  column for every row, and an anonymized UUID in the `Student` column. So all 281 rows
  had identical `availability_id` = "Lurie College of Education General Scholarship".
- **Fix:** Switched PK to `application_id` (UUID generated per row → always unique).
  GSI on `rubric_id` still allows querying all apps for a scholarship type.
- **Tradeoff:** Lost idempotency — re-uploading the same file creates NEW records with
  new UUIDs (duplicates). Acceptable for demo; revisit if idempotency needed.

### Bugs Hit & Fixed During Deployment

| # | Bug | Root Cause | Fix |
|---|-----|------------|-----|
| 1 | `Runtime.ImportModuleError: numpy` | Built deps with `cp313` wheels (local Python 3.13) but Lambda runs Python 3.12 | Rebuild with `pip install --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12 --implementation cp` |
| 2 | `No config found for 'Lurie+College+...'` | S3 URL-encodes keys — spaces become `+`, so `identify_scholarship()` couldn't match | Added `unquote_plus()` on the S3 key in handler |
| 3 | `BatchWriteItem: Provided list of item keys contains duplicates` | All rows shared the same `availability_id` → duplicate composite keys in one batch | Switched PK to `application_id` (see above) |

### VERIFIED WORKING (end-to-end)

- Upload `Lurie College of Education General Scholarship 25-26 ad hoc report.xlsx` → `data/`
- CloudWatch log: "Parsed 281 applications" + "Wrote 281 records to sjsu-applications"
- DynamoDB `scan --select COUNT` → **281 records**
- Sample record verified: correct `application_id`, `rubric_id`, `qa_pairs` (3 essays with
  question_id/question/answer/topic), `source` (file/sheet/row), `student_name`, `year`,
  `parsed_at`, `source_file`.

### Lambda Handler Final Logic (lambdas/parse-applications/handler.py)

1. S3 event → extract bucket + `unquote_plus(key)`
2. Validate: `data/*.xlsx`, skip `~$` temp files
3. `parse_file()` → identify scholarship from filename, read xlsx (first sheet), normalize rows
4. Uses the **qa_pairs / essay_fields** config-driven format (synced with Parser/parser.py)
5. `write_to_dynamodb()` → `batch_writer()`, PK `application_id`, strips None values,
   stores `qa_pairs` + `source` as nested structures
6. Raises on error (Lambda retries)

Handler now matches the good `qa_pairs` parser (the old `essays` format issue is resolved).

### Known Efficiency Ceilings (identified, NOT fixed — fine at current scale)

- boto3 clients created per-invocation (could be module-level singletons for warm-start reuse)
- `df.iterrows()` is slow (fine for 281 rows, slow for thousands)
- Full event JSON logged every invocation (CloudWatch cost at scale)
- Entire xlsx buffered in memory (fine <1MB, risky for 50MB files)
- No idempotency guard (S3 at-least-once delivery → possible dup records)

Ponytail verdict: none worth fixing at 281 rows / <500KB / 2.4s / 180MB. Only cleaned up
one dead variable (`skipped`).

### Repo Decisions

- `Parser/` — KEPT as local dev/test harness (CLI: `--file`, `--output`, `--sample`,
  reads prod bucket, writes JSON files locally).
- `lambdas/parse-applications/` — deployed version (S3 trigger → DynamoDB).
- `scholarship_config.py` is duplicated in both — acceptable for now.

### Git

- Branch: `feat/parser` (note: `feat/lambda-parse-trigger` was created earlier but the
  final commit landed on `feat/parser`).
- Commit `67a728f`: "feat: add S3-triggered parse Lambda for xlsx → DynamoDB pipeline"
  - Added: handler.py, scholarship_config.py, requirements.txt (in lambdas/parse-applications/)
  - Updated: .gitignore (ignores lambda `package/`, `deployment.zip`, `output.json`), Parser/memory.md
- NOT merged to main yet (user's choice).

### Build Command (to redeploy Lambda)

```bash
# 1. Build Linux-compatible deps (Python 3.12)
pip install --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12 \
  --implementation cp --target lambdas/parse-applications/package pandas==2.2.3 openpyxl==3.1.5

# 2. Zip package + handler
cd lambdas/parse-applications/package; Compress-Archive -Path * -DestinationPath ..\deployment.zip
cd ..; Compress-Archive -Path handler.py, scholarship_config.py -DestinationPath deployment.zip -Update

# 3. Deploy
aws lambda update-function-code --function-name sjsu-parse-applications \
  --zip-file fileb://deployment.zip --profile Samson --region us-west-2
```

### Next Steps (unchanged)

1. Build scoring Lambda: read from `sjsu-applications` → build prompt (qa_pairs + rubric +
   system instructions) → Bedrock (Claude) → write structured score to `sjsu-scores`.
2. Define rubric format.
3. Wire dashboard API to read both tables.
4. (Later) SAM template for reproducible deploys.


---

## 2026-07-15: Composite Key Migration + Bedrock Scoring (Samson Chat)

### Key-design change: application_id → student_id + rubric_id

**Why:** The Excel `Student` column holds a STABLE per-student UUID (e.g.
`015f4b90-155f-44e9-9af3-adc986747e71`). Previously this landed in `student_name`
and we keyed on the generated `application_id` (new UUID every parse → not
idempotent). Renamed `student_name` → `student_id` (it was always a UUID, never a
name) and switched BOTH tables to composite key:
- **PK: `student_id`** (stable Excel UUID)
- **SK: `rubric_id`** (a student can apply to multiple scholarships)

This is stable + unique + idempotent on re-parse.

### Changes made

- `lambdas/parse-applications/scholarship_config.py`: all 4 configs `"Student": "student_name"` → `"student_id"`.
- `lambdas/parse-applications/handler.py`: record dict `student_id`; skip check on `student_id`; `write_to_dynamodb` now uses `batch_writer(overwrite_by_pkeys=["student_id","rubric_id"])`, item keyed on `student_id`+`rubric_id` (+ application_id, source_file, parsed_at). No more `student_name` anywhere.
- Recreated both DynamoDB tables (both were safe to drop — app table had only test data, scores was empty):
  - `sjsu-applications`: PK student_id, SK rubric_id, GSI `rubric-id-index` (rubric_id HASH + student_id RANGE), PAY_PER_REQUEST.
  - `sjsu-scores`: PK student_id, SK rubric_id, PAY_PER_REQUEST (no GSI).
- Redeployed Lambda `sjsu-parse-applications`. Re-tested: 281 records parsed and written, verified in DynamoDB (student_id PK + rubric_id SK).

### ⚠️ Build gotcha: OneDrive file lock on package/

Zipping `lambdas/parse-applications/package/` failed with "Access denied" (OneDrive
holds handles on the pip-installed files). **Workaround:** build deps fresh into a
temp dir OUTSIDE OneDrive and zip there:
```powershell
$b = "$env:TEMP\sjsu-lambda-build"
pip install --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12 --implementation cp --target $b pandas==2.2.3 openpyxl==3.1.5
Copy-Item handler.py,scholarship_config.py $b
# zip via [System.IO.Compression.ZipFile]::CreateFromDirectory($b, "$env:TEMP\sjsu-deployment.zip")
aws lambda update-function-code --function-name sjsu-parse-applications --zip-file fileb://$env:TEMP\sjsu-deployment.zip --profile Samson --region us-west-2
```

### NEW: Bedrock scoring step (scoring/score.py)

Local Python scorer (source of truth; wrap in Lambda later):
1. Reads apps from `sjsu-applications` (GSI query by rubric_id, or scan).
2. Loads matching rubric from `prompts/*.md`:
   - `sjsu-general`→GeneralRubric.md, `lurie-coed-general`→EducationRubric.md,
     `coeng-deans`→EngineeringRubric.md, `physics-dept`→PhysicsRubric.md.
3. Rubric = system prompt (+ strict guardrails: score only from content, quote
   evidence, say when evidence missing, JSON-only output). qa_pairs + gpa = user msg.
4. Bedrock **Converse API**, model `us.anthropic.claude-haiku-4-5-20251001-v1:0`
   (inference profile — needs `us.` prefix), temp 0.0, maxTokens 2048.
5. Parses JSON (strips ```json fences), writes to `sjsu-scores`:
   `student_id`+`rubric_id` (key), `application_id`, `scored_at`, `model_id`,
   `scholarship_type`, `categories: {<Cat>: {Score, Reasoning}}`.

CLI: `--rubric-id`, `--limit`, `--dry-run`. Files: `scoring/score.py`,
`scoring/README.md`, `scoring/requirements.txt`.

**Verified:** dry-run on 2 Lurie apps → valid Education JSON (CareerGoals/
PersonalGrowth/LCOEEssay, Score+Reasoning with exact essay quotes). Real run wrote
2 records to `sjsu-scores` (confirmed via scan).

### Bedrock models available (us-west-2, account 606263411016)

Claude Haiku 4.5 (using), Sonnet 4.5, Opus 4.5, plus older 3.x. All ACTIVE ones
use INFERENCE_PROFILE (prefix model id with `us.`).

### Next steps

1. Score full batches per rubric (watch cost); consider batching / concurrency.
2. Wrap scorer in a Lambda (manual/scheduled/DynamoDB-Streams trigger) once prompts finalized.
3. Wire dashboard API (apps/api) to read sjsu-applications + sjsu-scores.
4. Add human-review / disagreement workflow later.
5. IAM for scoring Lambda: bedrock:InvokeModel + dynamodb Query/Scan (apps) + PutItem (scores).


---

## 2026-07-15: Phase 1 refactor — SJSU General ONLY (branch feat/phase1-sjsu-general)

Narrowed the whole project to phase-1 scope: SJSU General Scholarship only, both
25-26 and 26-27, one shared rubric + one shared prompt. Specialized scholarships
are marked-unsupported stubs (never parsed/scored).

### Schema change (removed rubric_id)
Parsed application schema is now keyed by a deterministic `application_key =
sjsu_general#{year}#{student_uuid}`. Fields: student_uuid, availability_id,
candidate_key (last 12 hex, for eval joins), scholarship_scope=sjsu_general, year,
student_name(None), gpa, academic_program, academic_level, major, qa_pairs,
source, status='parsed'. **No rubric_id** in the active path.

### DynamoDB (recreated, keyed by application_key)
- `sjsu-applications`: PK application_key; NEW_IMAGE stream (ARN ...stream/2026-07-15T23:28:18.363); GSI scope-year-index (scholarship_scope HASH + year RANGE).
- `sjsu-scores`: PK application_key. Stores criterion_scores, weighted_total, reasoning_summary, confidence, model_id, scholarship_scope, year, status, scored_at.

### Files
- `lambdas/parse-applications/{handler.py, scholarship_config.py}` — rewritten for phase-1 schema; identify_scholarship returns SJSU General only.
- `lambdas/score-applications/{handler.py, prompt.py, sjsu_general_rubric.md, requirements.txt}` — NEW scoring Lambda. DynamoDB Streams trigger, batch ~5 (set on ESM at deploy), Bedrock Converse (MODEL_ID env, default us.anthropic.claude-haiku-4-5, temp=0 / anthropic omits topP), strict JSON validate, writes to sjsu-scores. boto3-only (Lambda runtime), no package/ needed.
- `evaluation/{config.py, human_scores.py, dataset_builder.py}` — narrowed to sjsu-general (EVAL_SCOPE_RUBRIC_IDS). Verified dry-run: only "SJSU General Scholarship | 26-27" (4875 joined, 20 sampled); 25-26 excluded (no Candidate column).
- `docs/phase1-sjsu-general.md` + README updated.

### Scoring support vs human-comparison support (KEY)
- Production scoring: BOTH 25-26 and 26-27 (independent of human scores).
- Human comparison (eval): 26-27 ONLY. 25-26 score sheet has NO Candidate column → no deterministic join → excluded/documented.

### Deploy TODO (not yet done)
- Redeploy parse Lambda (schema change). Build in temp dir (OneDrive lock on package/).
- Deploy score-applications Lambda + create event source mapping on the applications stream (batch size 5, StartingPosition LATEST). IAM: bedrock:InvokeModel + dynamodb read on stream + PutItem on sjsu-scores + AWSLambdaDynamoDBExecutionRole.

### DEPLOYED + VERIFIED END-TO-END (2026-07-15)
- Parse Lambda rewritten to use **openpyxl directly (no pandas/numpy)** — eliminated the heavy dependency that kept failing to build on the low-disk machine. Zip ~808KB. Redeployed sjsu-parse-applications.
- Score Lambda deployed: sjsu-score-applications (boto3-only, 5.2KB zip, MODEL_ID=us.anthropic.claude-haiku-4-5, memory 256MB). IAM role sjsu-score-lambda-role (bedrock:InvokeModel + stream read + scores PutItem + basic exec).
- Event source mapping created: applications stream -> score Lambda, BatchSize=5, MaxBatchingWindow=10s, StartingPosition=LATEST (UUID 643b9651-e46f-42fb-ada2-667bd28ef512).
- Bug found + fixed during test: scoring Lambda put_item failed "Float types not supported" — nested criterion_scores floats. Fixed by converting whole item to Decimal via json round-trip (parse_float=Decimal). Redeployed.
- E2E TEST (2-row synthetic SJSU General 25-26 file uploaded to test bucket data/): parse wrote 2 records to sjsu-applications (application_key sjsu_general#25-26#..., status=parsed); stream triggered score Lambda; Bedrock scored both; sjsu-scores got 2 records (weighted_total, confidence, 5 criterion_scores w/ evidence quotes, reasoning_summary, model_id, status=scored). Verified via scan (Count=2). Test data cleaned up afterward.
- NOTE: never upload a full ~4880-row SJSU file to the trigger bucket unless you intend thousands of Bedrock scoring calls (stream scores every parsed row). Use small batches or disable the ESM for bulk loads.
