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
from decimal import Decimal
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

# Per-category max_score (from prompts/*.md) and weight_pct (must sum to 100 per rubric).
# Normalized total = sum((score / max_score) * weight_pct) → 0–100 scale.
# Replace weight_pct values with your official rubric percentages where they differ.
RUBRIC_CATEGORIES: dict[str, dict[str, dict[str, float]]] = {
    "sjsu-general": {
        "XCActivity": {"max_score": 1, "weight_pct": 10},
        "EssayCareerGoalsScore": {"max_score": 4, "weight_pct": 40},
        "EssayChallengeScore": {"max_score": 4, "weight_pct": 30},
        "InitiativeAndMotivation": {"max_score": 3, "weight_pct": 10},
        "Creativity": {"max_score": 3, "weight_pct": 10},
    },
    "lurie-coed-general": {
        "CareerGoals": {"max_score": 10, "weight_pct": 100 / 3},
        "PersonalGrowth": {"max_score": 10, "weight_pct": 100 / 3},
        "LCOEEssay": {"max_score": 10, "weight_pct": 100 / 3},
    },
    "coeng-deans": {
        "Essays": {"max_score": 5, "weight_pct": 50},
        "ExtracurricularsAndJobs": {"max_score": 5, "weight_pct": 50},
    },
    "physics-dept": {
        "Academics": {"max_score": 5, "weight_pct": 100 / 6},
        "Research": {"max_score": 5, "weight_pct": 100 / 6},
        "Service": {"max_score": 5, "weight_pct": 100 / 6},
        "ChallengesOvercome": {"max_score": 5, "weight_pct": 100 / 6},
        "FinancialNeed": {"max_score": 5, "weight_pct": 100 / 6},
        "FacultyEndorsement": {"max_score": 5, "weight_pct": 100 / 6},
    },
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


def get_categories(score_json: dict) -> dict:
    """Normalize model output (Categories) vs DynamoDB item (categories)."""
    return score_json.get("Categories") or score_json.get("categories") or {}


def get_category_scores(score_json: dict) -> dict[str, float]:
    """Return {category_name: raw_score} from either JSON shape."""
    scores = {}
    for name, data in get_categories(score_json).items():
        if isinstance(data, dict) and "Score" in data:
            scores[name] = float(data["Score"])
    return scores


def compute_total_score(rid: str, score_json: dict) -> float:
    """Weighted normalized total on a 0–100 scale.

    Each category contributes (score / max_score) * weight_pct.
    """
    config = RUBRIC_CATEGORIES.get(rid)
    if not config:
        raise ValueError(f"Unknown rubric_id: {rid}")

    scores = get_category_scores(score_json)
    missing = set(config) - set(scores)
    if missing:
        raise ValueError(f"Missing categories for {rid}: {sorted(missing)}")

    total = 0.0
    for name, spec in config.items():
        normalized = scores[name] / spec["max_score"]
        total += normalized * spec["weight_pct"]
    return round(total, 2)


def compute_score_breakdown(rid: str, score_json: dict) -> dict[str, dict]:
    """Per-category raw score, normalized fraction, and weighted contribution."""
    config = RUBRIC_CATEGORIES[rid]
    scores = get_category_scores(score_json)
    breakdown = {}
    for name, spec in config.items():
        raw = scores[name]
        normalized = raw / spec["max_score"]
        weighted = normalized * spec["weight_pct"]
        breakdown[name] = {
            "raw": raw,
            "max_score": spec["max_score"],
            "weight_pct": spec["weight_pct"],
            "normalized": round(normalized, 4),
            "weighted": round(weighted, 2),
        }
    return breakdown


def to_dynamo(value):
    """Recursively convert floats to Decimal — DynamoDB rejects Python floats."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_dynamo(v) for v in value]
    return value


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
        "categories": get_categories(score_json),
        "total_score": score_json.get("total_score"),
    }
    # drop None values
    item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=to_dynamo(item))


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
            score_json["total_score"] = compute_total_score(rid, score_json)

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
