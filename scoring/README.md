# scoring — Bedrock rubric scoring

Reads normalized applications from DynamoDB `sjsu-applications`, scores each
against its matching rubric in `../prompts/*.md` using Bedrock (Claude), and
writes structured JSON scores to DynamoDB `sjsu-scores`.

Both tables use composite key **`student_id` (PK) + `rubric_id` (SK)**, so each
score maps 1:1 to its application.

## rubric_id → rubric file

| rubric_id | prompt file | ScholarshipType |
|-----------|-------------|-----------------|
| `sjsu-general` | GeneralRubric.md | General |
| `lurie-coed-general` | EducationRubric.md | Education |
| `coeng-deans` | EngineeringRubric.md | Engineering |
| `physics-dept` | PhysicsRubric.md | Physics |

## Usage

```bash
# dry-run (score but don't write) — always test the prompt first
python score.py --rubric-id lurie-coed-general --limit 3 --dry-run

# real run (writes to sjsu-scores)
python score.py --rubric-id lurie-coed-general --limit 3

# score across all rubrics
python score.py --limit 5
python score.py                 # everything (watch Bedrock cost)
```

## Model

`us.anthropic.claude-haiku-4-5-20251001-v1:0` (inference profile, us region group).
Uses the Bedrock Converse API, temperature 0.0, max 2048 tokens.
Change `MODEL_ID` in `score.py` to use Sonnet/Opus for higher quality.

## AWS

Profile `Samson`, region `us-west-2`. Needs `bedrock:InvokeModel` on the model,
`dynamodb:Query/Scan` on sjsu-applications, `dynamodb:PutItem` on sjsu-scores.

## Output shape (sjsu-scores item)

```
student_id (PK), rubric_id (SK), application_id, scored_at, model_id,
scholarship_type, categories: { <Category>: { Score, Reasoning }, ... }
```
