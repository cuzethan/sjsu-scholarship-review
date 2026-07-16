"""
bulk_score.py — Parallel bulk scoring for sjsu-scores-test.

Reads apps from sjsu-applications, calls Bedrock in parallel (20 threads),
writes results to sjsu-scores-test using UpdateItem (preserves human scores).

Usage:
    python bulk_score.py --limit 100      # test with 100
    python bulk_score.py                   # score all
"""
import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import boto3

# --- Config ---
AWS_PROFILE = os.environ.get("AWS_PROFILE", "Samson")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
APPLICATIONS_TABLE = "sjsu-applications"
SCORES_TABLE = "sjsu-scores-test"
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
MAX_WORKERS = 20  # parallel Bedrock calls

# Rubric
RUBRIC_PATH = Path(__file__).resolve().parent / "lambdas" / "score-applications" / "sjsu_general_rubric.md"

SCHEMA_INSTRUCTIONS = """
Return ONLY a single JSON object (no prose, no markdown fences) shaped exactly:

{
  "criterion_scores": [
    { "criterion": "string  // rubric category name",
      "score": 0,           // number within that category's scale
      "reasoning": "string" }
  ],
  "weighted_total": 0,      // sum of criterion scores (max 15)
  "reasoning_summary": "string  // 1-2 sentence overall justification"
}

Rules:
- One entry per rubric category (5 total).
- Score only from provided application content; do not invent facts.
- All strings MUST be properly JSON-escaped.
- Return ONLY the JSON object.
"""

WEIGHTS = {
    "Extracurricular Activities":   {"max": 1, "weight": 10},
    "Career Goals Essay":           {"max": 4, "weight": 40},
    "Challenge Essay":              {"max": 4, "weight": 30},
    "Initiative & Self-Motivation": {"max": 3, "weight": 10},
    "Creativity":                   {"max": 3, "weight": 10},
}


def session():
    return boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)


def load_rubric():
    return RUBRIC_PATH.read_text(encoding="utf-8")


def build_system_prompt(rubric_text):
    return rubric_text + "\n\n" + SCHEMA_INSTRUCTIONS


def build_user_message(app):
    lines = []
    if app.get("gpa"):
        lines.append(f"GPA: {app['gpa']}")
    if app.get("major"):
        lines.append(f"Major: {app['major']}")
    if app.get("academic_level"):
        lines.append(f"Academic Level: {app['academic_level']}")
    if app.get("academic_program"):
        lines.append(f"Academic Program: {app['academic_program']}")
    lines.append("\n--- Application Essays ---\n")
    for qa in app.get("qa_pairs", []):
        lines.append(f"Question [{qa.get('question_id','?')}]: {qa.get('question','')}")
        lines.append(f"Answer: {qa.get('answer','')}\n")
    return "\n".join(lines)


def extract_json(text):
    text = (text or "").strip()
    fence = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        brace = re.search(r'(\{.*\})', text, re.DOTALL)
        if brace:
            text = brace.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Repair: fix newlines and trailing commas
        repaired = re.sub(r'(?<!\\)\n', '\\n', text)
        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
        return json.loads(repaired)


def calculate_final_score(criterion_scores):
    total = 0.0
    for cs in criterion_scores:
        w = WEIGHTS.get(cs["criterion"])
        if w and w["max"] > 0:
            total += (cs["score"] / w["max"]) * w["weight"]
    return round(total, 2)


def read_applications(dynamo, limit=None):
    table = dynamo.Table(APPLICATIONS_TABLE)
    items = []
    kwargs = {"FilterExpression": boto3.dynamodb.conditions.Attr("scholarship_scope").eq("sjsu_general")}
    while True:
        resp = table.scan(**kwargs)
        for item in resp.get("Items", []):
            if item.get("qa_pairs"):
                items.append(item)
        if limit and len(items) >= limit:
            return items[:limit]
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def score_one(bedrock, system_prompt, app):
    """Score a single application. Returns (app_key, result_dict)."""
    app_key = app.get("application_key")
    t0 = time.time()
    try:
        resp = bedrock.converse(
            modelId=MODEL_ID,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": build_user_message(app)}]}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0},
        )
        latency = round(time.time() - t0, 3)
        text = resp["output"]["message"]["content"][0]["text"]
        parsed = extract_json(text)
        cs = parsed["criterion_scores"]
        return app_key, {
            "status": "scored",
            "latency_s": latency,
            "llm_weighted_score": calculate_final_score(cs),
            "criterion_scores": cs,
            "reasoning_summary": parsed.get("reasoning_summary", ""),
            "model_id": MODEL_ID,
            "scored_at": datetime.now(timezone.utc).isoformat(),
            "scholarship_scope": "sjsu_general",
            "year": app.get("year", ""),
        }
    except Exception as e:
        return app_key, {"status": "score_failed", "failure": str(e)}


def write_score(table, app_key, result):
    """UpdateItem — only writes LLM fields, preserves human scores."""
    fields = {k: v for k, v in result.items() if v is not None}
    fields = json.loads(json.dumps(fields), parse_float=Decimal)

    update_parts = []
    expr_values = {}
    expr_names = {}
    for i, (k, v) in enumerate(fields.items()):
        update_parts.append(f"#{k} = :v{i}")
        expr_values[f":v{i}"] = v
        expr_names[f"#{k}"] = k

    table.update_item(
        Key={"application_key": app_key},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="Max apps to score")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS, help="Parallel threads")
    args = ap.parse_args()

    sess = session()
    dynamo = sess.resource("dynamodb")
    scores_table = dynamo.Table(SCORES_TABLE)

    print(f"Loading applications from {APPLICATIONS_TABLE}...")
    apps = read_applications(dynamo, args.limit)
    print(f"Loaded {len(apps)} applications to score.")
    print(f"Workers: {args.workers}, Model: {MODEL_ID}")
    print(f"Target table: {SCORES_TABLE}\n")

    rubric_text = load_rubric()
    system_prompt = build_system_prompt(rubric_text)

    # Each thread gets its own Bedrock client
    def make_bedrock():
        return sess.client("bedrock-runtime")

    scored = 0
    failed = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for app in apps:
            bedrock = make_bedrock()
            f = pool.submit(score_one, bedrock, system_prompt, app)
            futures[f] = app.get("application_key")

        for f in as_completed(futures):
            app_key, result = f.result()
            write_score(scores_table, app_key, result)
            if result["status"] == "scored":
                scored += 1
            else:
                failed += 1
            total = scored + failed
            if total % 10 == 0:
                elapsed = time.time() - start
                rate = total / elapsed
                print(f"  [{total}/{len(apps)}] scored={scored} failed={failed} "
                      f"elapsed={elapsed:.0f}s rate={rate:.1f}/s")

    elapsed = time.time() - start
    print(f"\nDone. Scored: {scored}, Failed: {failed}")
    print(f"Total time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"Avg: {elapsed/len(apps):.2f}s per app, effective rate: {len(apps)/elapsed:.1f} apps/s")


if __name__ == "__main__":
    main()
