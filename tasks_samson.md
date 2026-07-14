# Tasks — Samson

## S3 Event-Driven Parse Lambda + DynamoDB Scoring Pipeline

**Goal:** Automate scholarship `.xlsx` ingestion — when a new spreadsheet lands in
`s3://dxhub-camp-2026-sjsu-scholarship-application-review/data/`, a Lambda parses it
and writes normalized application records to DynamoDB for the dashboard and future
Bedrock scoring.

---

## Architecture

```
.xlsx uploaded to data/ ──▶ Lambda: parse-applications ──▶ DynamoDB: sjsu-applications
                                                                       │
                         Lambda: score-applications ◀───────────────────┘
                                    │
                                    ├──▶ Bedrock Claude (invoke_model)
                                    │
                                    └──▶ DynamoDB: sjsu-scores
                                                       │
                         Dashboard API (tRPC) ◀────────┘
```

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Storage | DynamoDB | Faster path to demo; dashboard can query directly |
| Applications PK | `availability_id` | Stable ID from xlsx; idempotent on re-parse |
| Applications GSI | `rubric_id` | Query all apps for a specific scholarship |
| Scores PK | `availability_id` | 1:1 with application record |
| Scoring approach | Per-application Lambda (decoupled) | Can trigger manually, no timeout risk |
| Infra-as-code | SAM template.yaml | Reproducible, version-controlled |
| Parse trigger | S3 event notification | Event-driven, no polling |

---

## Task 1: Create SAM template with DynamoDB tables + Lambda scaffolding

- [ ] Define `infra/template.yaml`
  - `sjsu-applications` table: PK = `availability_id` (S), GSI on `rubric_id` (S) + sort key `availability_id`
  - `sjsu-scores` table: PK = `availability_id` (S)
  - Parse Lambda: Python 3.12, 512MB, 5 min timeout
  - S3 event trigger: prefix `data/`, suffix `.xlsx`
  - IAM: `s3:GetObject` on `data/*`, `dynamodb:PutItem`/`BatchWriteItem` on applications table
- [ ] Add `infra/samconfig.toml` with defaults (stack name, region, profile Samson)
- [ ] Validate: `sam validate` passes

---

## Task 2: Scaffold the parse Lambda project

- [ ] Create `lambdas/parse-applications/handler.py` (entry point)
- [ ] Adapt `Parser/parser.py` → `lambdas/parse-applications/parser.py` (remove CLI, accept S3 key)
- [ ] Copy `Parser/scholarship_config.py` → `lambdas/parse-applications/scholarship_config.py`
- [ ] Create `lambdas/parse-applications/requirements.txt` (pandas, openpyxl, boto3)

---

## Task 3: Implement the parse Lambda handler

- [ ] Extract bucket + key from `event["Records"][0]["s3"]`
- [ ] Validate key ends in `.xlsx` and is under `data/`
- [ ] Call parser to get normalized application dicts
- [ ] Use `availability_id` as DynamoDB primary key (skip records without one)
- [ ] Batch write to DynamoDB via `batch_writer()`
- [ ] Add provenance fields: `source_file`, `parsed_at` (ISO timestamp)
- [ ] Log summary: file name, records parsed, records written
- [ ] Unit test with mocked S3 event + mocked DynamoDB

---

## Task 4: Deploy and end-to-end test (parse)

- [ ] `sam build && sam deploy --profile Samson`
- [ ] Upload test `.xlsx` to `data/` prefix
- [ ] Verify Lambda execution in CloudWatch
- [ ] Query `sjsu-applications` table — confirm records exist
- [ ] Verify dashboard API can read records

---

## Task 5: Scaffold the scoring Lambda

- [ ] Create `lambdas/score-applications/handler.py`
- [ ] Accept `rubric_id` or `availability_id` as input
- [ ] Read application record(s) from `sjsu-applications`
- [ ] Load rubric criteria (hardcoded JSON initially)
- [ ] Construct scoring prompt:
  - Application content + rubric criteria
  - Enforce: exact quotes, structured JSON output, no hallucination
  - If evidence missing → say so explicitly
- [ ] Call Bedrock `invoke_model` (Claude)
- [ ] Parse structured response into score fields
- [ ] Write to `sjsu-scores` table (PK: `availability_id`)
- [ ] Unit test with mocked Bedrock response

---

## Task 6: End-to-end integration test

- [ ] Upload xlsx → parse Lambda fires → records in `sjsu-applications`
- [ ] Trigger score Lambda manually → scores in `sjsu-scores`
- [ ] Hit dashboard API → confirm application + score data returned
- [ ] Validate output: overall score, per-criterion scores, evidence quotes, confidence

---

## AWS Details

- **Account:** 606263411016
- **Region:** us-west-2
- **Profile:** Samson
- **Bucket:** dxhub-camp-2026-sjsu-scholarship-application-review
- **S3 prefix (raw):** `data/`
- **DynamoDB tables:** `sjsu-applications`, `sjsu-scores`

---

## Build Order (suggested)

1. SAM template + tables
2. Parse Lambda scaffolding
3. Parse Lambda implementation + deploy
4. Verify parse end-to-end
5. Score Lambda scaffolding
6. Score Lambda implementation + deploy
7. Full pipeline test
