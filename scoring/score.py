"""
score.py — Bedrock scoring step for SJSU scholarship applications.

Reads normalized application records from DynamoDB (sjsu-applications),
scores each against its matching rubric prompt (prompts/*.md) using Bedrock
(Claude), and writes structured JSON scores to DynamoDB (sjsu-scores).

Key design: both tables use composite key student_id (PK) + rubric_id (SK),
so a score maps 1:1 to its application.

Usage:
    python score.py --rubric-id lurie-coed-general --limit 3 --dry-run
    python score.py --rubric-id lurie-coed-general --limit 3
    python score.py --limit 5                 # score across all rubrics
    python score.py                           # score everything (careful: cost)
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import boto3

# --- Config ---
AWS_PROFILE = "Samson"
AWS_REGION = "us-west-2"
APPLICATIONS_TABLE = "sjsu-applications"
SCORES_TABLE = "sjsu-scores"

# Bedrock models use inference profiles — prefix with the region group ("us.")
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# rubric_id (in DynamoDB) -> rubric prompt markdown file
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
RUBRIC_FILES = {
    "sjsu-general": "GeneralRubric.md",
    "lurie-coed-general": "EducationRubric.md",
    "coeng-deans": "EngineeringRubric.md",
    "physics-dept": "PhysicsRubric.md",
}

# Extra guardrails appended to every rubric system prompt
SYSTEM_SUFFIX = """

STRICT INSTRUCTIONS:
- Score ONLY from the application content provided. Do not invent facts.
- Where the rubric asks for evidence, quote exact supporting text from the application.
- If evidence for a category is missing, say so explicitly in the Reasoning and score accordingly.
- Return ONLY the JSON object specified above. No prose, no markdown fences, no commentary.
"""


def session():
    return boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)


def load_rubric(rubric_id: str) -> str:
    """Load the rubric markdown for a given rubric_id."""
    fname = RUBRIC_FILES.get(rubric_id)
    if not fname:
        raise ValueError(f"No rubric file mapped for rubric_id '{rubric_id}'")
    path = PROMPTS_DIR / fname
    return path.read_text(encoding="utf-8")


def read_applications(dynamo, rubric_id: str | None, limit: int | None) -> list[dict]:
    """Read application records from sjsu-applications.

    If rubric_id given, query the GSI; otherwise scan.
    """
    table = dynamo.Table(APPLICATIONS_TABLE)
    items = []

    if rubric_id:
        from boto3.dynamodb.conditions import Key
        kwargs = {
            "IndexName": "rubric-id-index",
            "KeyConditionExpression": Key("rubric_id").eq(rubric_id),
        }
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if limit and len(items) >= limit:
                items = items[:limit]
                break
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    else:
        kwargs = {}
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if limit and len(items) >= limit:
                items = items[:limit]
                break
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    return items


def build_user_message(app: dict) -> str:
    """Build the applicant content block from a normalized application record."""
    lines = []
    if app.get("gpa"):
        lines.append(f"GPA: {app['gpa']}")
    if app.get("self_reported_gpa"):
        lines.append(f"Self-Reported GPA: {app['self_reported_gpa']}")
    if app.get("major"):
        lines.append(f"Major: {app['major']}")
    if app.get("academic_level"):
        lines.append(f"Academic Level: {app['academic_level']}")
    if app.get("academic_program"):
        lines.append(f"Academic Program: {app['academic_program']}")

    lines.append("\n--- Application Essays ---\n")
    for qa in app.get("qa_pairs", []):
        topic = f" (topic: {qa['topic']})" if qa.get("topic") else ""
        lines.append(f"Q ({qa.get('question_id', '?')}){topic}: {qa.get('question', '')}")
        lines.append(f"A: {qa.get('answer', '')}\n")

    return "\n".join(lines)


def extract_json(text: str) -> dict:
    """Pull a JSON object out of the model response (strips markdown fences)."""
    text = text.strip()
    # Strip ```json ... ``` fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        # Grab the first {...} block
        brace = re.search(r"(\{.*\})", text, re.DOTALL)
        if brace:
            text = brace.group(1)
    return json.loads(text)


def score_application(bedrock, rubric_text: str, app: dict) -> dict:
    """Call Bedrock to score one application. Returns parsed score JSON."""
    system_prompt = rubric_text + SYSTEM_SUFFIX
    user_message = build_user_message(app)

    resp = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_message}]}],
        inferenceConfig={"maxTokens": 2048, "temperature": 0.0},
    )
    text = resp["output"]["message"]["content"][0]["text"]
    return extract_json(text)


def write_score(dynamo, app: dict, score_json: dict):
    """Write a score record to sjsu-scores (composite key student_id + rubric_id)."""
    table = dynamo.Table(SCORES_TABLE)
    item = {
        "student_id": app["student_id"],
        "rubric_id": app["rubric_id"],
        "application_id": app.get("application_id"),
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "model_id": MODEL_ID,
        "scholarship_type": score_json.get("ScholarshipType"),
        "categories": score_json.get("Categories", score_json),
    }
    # drop None values
    item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=item)


def main():
    ap = argparse.ArgumentParser(description="Score SJSU scholarship applications with Bedrock")
    ap.add_argument("--rubric-id", help="Only score this rubric_id (uses GSI). Omit to score all.")
    ap.add_argument("--limit", type=int, help="Max applications to score")
    ap.add_argument("--dry-run", action="store_true", help="Score but do NOT write to DynamoDB; print results")
    args = ap.parse_args()

    sess = session()
    dynamo = sess.resource("dynamodb")
    bedrock = sess.client("bedrock-runtime")

    apps = read_applications(dynamo, args.rubric_id, args.limit)
    print(f"Loaded {len(apps)} application(s) to score.\n")

    # cache rubric text per rubric_id
    rubric_cache = {}
    scored, failed = 0, 0

    for i, app in enumerate(apps, 1):
        rid = app.get("rubric_id")
        sid = app.get("student_id")
        try:
            if rid not in rubric_cache:
                rubric_cache[rid] = load_rubric(rid)
            score_json = score_application(bedrock, rubric_cache[rid], app)

            if args.dry_run:
                print(f"[{i}/{len(apps)}] {rid} / {sid}")
                print(json.dumps(score_json, indent=2))
                print()
            else:
                write_score(dynamo, app, score_json)
                print(f"[{i}/{len(apps)}] scored + wrote: {rid} / {sid}")
            scored += 1
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(apps)}] FAILED {rid} / {sid}: {e}")

    print(f"\nDone. Scored: {scored}, Failed: {failed}"
          + (" (dry-run, nothing written)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
