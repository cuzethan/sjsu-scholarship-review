"""
Lambda: score-applications  (Phase 1 — SJSU General only)

Event-driven scorer. Triggered by the DynamoDB Stream (NEW_IMAGE) on the
sjsu-applications table. The event source mapping is configured with a small
batch size (~5), so each invocation receives up to ~5 newly-parsed applications
and we make at most one Bedrock call per application in that controlled batch —
never an uncontrolled fan-out.

Flow per application (status == "parsed"):
  1. Build the shared SJSU General system prompt (rubric + strict schema).
  2. Build the user message from the parsed qa_pairs (production scoring uses
     ONLY application content — never human score files).
  3. Call Bedrock (deterministic) and parse/validate strict JSON.
  4. Write a score record to sjsu-scores keyed by application_key.

Production scoring is independent of any historical human scores.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3

from prompt import build_system_prompt, build_user_message, extract_json, validate, SchemaError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SCORES_TABLE = os.environ.get("SCORES_TABLE", "sjsu-scores")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
# Default to a cheap, fast, ACTIVE model. Anthropic models are deterministic with
# temperature=0 alone (they reject temperature+top_p together).
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "2048"))

_dynamo = None
_bedrock = None


def _scores_table():
    global _dynamo
    if _dynamo is None:
        _dynamo = boto3.resource("dynamodb", region_name=AWS_REGION)
    return _dynamo.Table(SCORES_TABLE)


def _bedrock_client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    return _bedrock


def _deserialize(image: dict) -> dict:
    """Convert a DynamoDB Stream NEW_IMAGE (typed) into a plain dict."""
    from boto3.dynamodb.types import TypeDeserializer
    d = TypeDeserializer()
    return {k: d.deserialize(v) for k, v in image.items()}


def score_application(app: dict) -> dict:
    """Call Bedrock for one application; return a score record (never raises)."""
    bedrock = _bedrock_client()
    result = {
        "application_key": app.get("application_key"),
        "scholarship_scope": app.get("scholarship_scope"),
        "year": app.get("year"),
        "model_id": MODEL_ID,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "status": "scored",
        "latency_s": None,
        "criterion_scores": None,
        "weighted_total": None,
        "reasoning_summary": None,
        "confidence": None,
        "failure": None,
    }
    infcfg = {"maxTokens": MAX_TOKENS, "temperature": 0}
    if "anthropic." not in MODEL_ID:
        infcfg["topP"] = 1
    t0 = time.time()
    try:
        resp = bedrock.converse(
            modelId=MODEL_ID,
            system=[{"text": build_system_prompt()}],
            messages=[{"role": "user", "content": [{"text": build_user_message(app)}]}],
            inferenceConfig=infcfg,
        )
        result["latency_s"] = round(time.time() - t0, 3)
        content = resp.get("output", {}).get("message", {}).get("content", [])
        text = next((b["text"] for b in content if isinstance(b, dict) and "text" in b), "")
        parsed = extract_json(text)
        validate(parsed)
        result["criterion_scores"] = parsed["criterion_scores"]
        result["weighted_total"] = parsed.get("weighted_total")
        result["reasoning_summary"] = parsed.get("reasoning_summary")
        result["confidence"] = parsed.get("confidence")
    except (json.JSONDecodeError, SchemaError) as e:
        result["status"] = "score_failed"
        result["failure"] = f"parse/schema: {e}"
    except Exception as e:
        result["status"] = "score_failed"
        result["failure"] = f"inference: {type(e).__name__}: {e}"
    return result


def _write_score(rec: dict):
    table = _scores_table()
    item = {k: v for k, v in rec.items() if v is not None}
    # DynamoDB rejects Python floats anywhere in the item (incl. nested
    # criterion_scores). Convert all floats to Decimal via a JSON round-trip.
    item = json.loads(json.dumps(item), parse_float=Decimal)
    table.put_item(Item=item)


def handler(event, context):
    """DynamoDB Streams entry point. Batch size (~5) is set on the event source mapping."""
    records = event.get("Records", [])
    logger.info(f"Stream batch: {len(records)} record(s)")
    scored = failed = skipped = 0

    for r in records:
        if r.get("eventName") not in ("INSERT", "MODIFY"):
            continue
        image = r.get("dynamodb", {}).get("NewImage")
        if not image:
            continue
        app = _deserialize(image)

        # Only score parsed SJSU General applications; skip already-scored, etc.
        if app.get("scholarship_scope") != "sjsu_general":
            skipped += 1
            continue
        if app.get("status") not in ("parsed", None):
            skipped += 1
            continue
        if not app.get("qa_pairs"):
            skipped += 1
            continue

        rec = score_application(app)
        _write_score(rec)
        if rec["status"] == "scored":
            scored += 1
        else:
            failed += 1
            logger.warning(f"Score failed for {rec['application_key']}: {rec['failure']}")

    logger.info(f"Scored={scored} failed={failed} skipped={skipped}")
    return {"statusCode": 200,
            "body": json.dumps({"scored": scored, "failed": failed, "skipped": skipped})}
