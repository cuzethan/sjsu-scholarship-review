# evaluation — Bedrock model evaluation harness

Evaluates multiple Bedrock models on scholarship application scoring and finds the
cheapest/smallest model that best matches human scores. Reuses the existing repo
parser (`Parser/`) — it does **not** rebuild parsing.

## How it works

```
input/applications/*.xlsx   (you upload)   input/scores/*.xlsx   (you upload)
        │                                          │
        ▼ reuse Parser/parser.normalize_row        ▼ Candidate = last 12 hex of student UUID
   parsed applications ──────── join on candidate_key ──────── human reviewer scores
                                    │ (valid 1:1 only)
                                    ▼ sample 20 / scholarship-year (seed 42)
                          eval dataset  ── LLM never sees human scores ──►
                                    │
              per-scholarship system prompt (prompts/*.md) + strict JSON schema
                                    ▼
                    Bedrock Converse (temp=0, top_p=1) × configurable model list
                                    ▼
              compare model total_score vs human_avg + individual reviewers
                                    ▼
                     output/report.html  +  JSON artifacts
```

## Setup

```bash
pip install -r requirements.txt
```

## 1. Upload your data (local, never from S3)

- Put application "ad hoc report" xlsx in `evaluation/input/applications/`
- Put human score sheets in `evaluation/input/scores/`

Score sheets must have a **`Candidate`** column that equals the last 12 hex chars
of the anonymized student UUID (the final UUID segment). Numeric reviewer-score
columns are auto-detected. Files without a Candidate column are **excluded** and
reported (no fuzzy matching).

## 2. Inspect uploaded columns (optional but recommended)

```bash
python inspect_xlsx.py
```
Confirms the detected Candidate column and reviewer-score columns per file.

## 3. Run

```bash
python run_eval.py --dry-run        # build dataset + resolve models, no inference/cost
python run_eval.py --limit 5        # small paid run (cost control)
python run_eval.py                  # full run (20/scholarship × available models)
python run_eval.py --models anthropic.claude-sonnet-4-20250514-v1:0
```

Outputs in `evaluation/output/`:
- `report.html` — the full visual report
- `dataset_report.json`, `inference_results.json`, `metrics.json`

## Models

Configured in `config.py` (`MODELS`). Unavailable models are marked and skipped —
the run never fails because a model is missing. If `USE_ALTERNATES=True`, a
missing shortlist model falls back to its closest enabled `alt` (labeled as a
substitution in the report).

Shortlist status in this account (us-west-2) at build time:
| Requested | Status |
|-----------|--------|
| amazon.nova-pro-v1:0 | available |
| qwen.qwen3-32b-v1:0 | available |
| anthropic.claude-sonnet-4-20250514-v1:0 | available |
| amazon.nova-micro-v1:0 | unavailable (alt: amazon.nova-2-lite-v1:0) |
| amazon.nova-lite-v1:0 | unavailable (alt: amazon.nova-2-lite-v1:0) |
| openai.gpt-5.4 | unavailable (alt: openai.gpt-oss-120b-1:0) |

## Constraints enforced

- LLM input = application content + scholarship system prompt + rubric only. **Never** human scores.
- Deterministic inference: `temperature=0`, `top_p=1`.
- One system prompt per scholarship (`prompts/*.md`).
- Strict output JSON schema (`schema.py`), validated per response.
- Only scholarship/year datasets with a reliable 1:1 join are evaluated; the rest
  are excluded and documented in the report.

## Files

| File | Purpose |
|------|---------|
| `config.py` | models, paths, sampling, deterministic settings, rubric map |
| `local_parser.py` | reuse `Parser/` to parse local application xlsx |
| `human_scores.py` | load score sheets, `Candidate` join key, reviewer scores |
| `dataset_builder.py` | join + filter + sample + exclusion report |
| `schema.py` | strict output schema + validator |
| `prompts.py` | build system prompt (rubric) + user message (application) |
| `inference.py` | resolve models + Bedrock Converse runner |
| `compare.py` | metrics vs human scores |
| `report.py` | self-contained HTML report (inline SVG) |
| `run_eval.py` | orchestrator CLI |
| `inspect_xlsx.py` | column inspector for uploaded files |
