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

from prompt import build_system_prompt, build_user_message, extract_json, validate, calculate_final_score, SchemaError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SCORES_TABLE = os.environ.get("SCORES_TABLE", "sjsu-scores")
APPLICATIONS_TABLE = os.environ.get("APPLICATIONS_TABLE", "sjsu-applications")
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


MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))


def score_application(app: dict) -> dict:
    """Call Bedrock for one application; return a score record.

    Retries up to MAX_RETRIES times on JSON parse or schema validation failures.
    """
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
        "llm_weighted_score": None,
        "reasoning_summary": None,
        "confidence": None,
        "failure": None,
    }
    infcfg = {"maxTokens": MAX_TOKENS, "temperature": 0}
    if "anthropic." not in MODEL_ID:
        infcfg["topP"] = 1

    system_prompt = build_system_prompt()
    user_message = build_user_message(app)
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        t0 = time.time()
        try:
            resp = bedrock.converse(
                modelId=MODEL_ID,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_message}]}],
                inferenceConfig=infcfg,
            )
            result["latency_s"] = round(time.time() - t0, 3)
            content = resp.get("output", {}).get("message", {}).get("content", [])
            text = next((b["text"] for b in content if isinstance(b, dict) and "text" in b), "")
            parsed = extract_json(text)
            validate(parsed)

            # Success — calculate weighted score out of 100
            result["criterion_scores"] = parsed["criterion_scores"]
            result["llm_weighted_score"] = calculate_final_score(parsed["criterion_scores"])
            result["reasoning_summary"] = parsed.get("reasoning_summary")
            result["confidence"] = parsed.get("confidence")
            return result

        except (json.JSONDecodeError, SchemaError) as e:
            last_error = f"parse/schema (attempt {attempt}/{MAX_RETRIES}): {e}"
            logger.warning(f"Retry {attempt}/{MAX_RETRIES} for {app.get('application_key')}: {last_error}")
            continue
        except Exception as e:
            # Non-retryable error (network, auth, etc.)
            result["status"] = "score_failed"
            result["failure"] = f"inference: {type(e).__name__}: {e}"
            return result

    # Exhausted retries
    result["status"] = "score_failed"
    result["failure"] = last_error
    return result


def _write_score(rec: dict):
    """Write LLM score fields to sjsu-scores using UpdateItem (preserves human score fields)."""
    table = _scores_table()

    app_key = rec.get("application_key")
    if not app_key:
        return

    # Build update expression from LLM fields only
    llm_fields = {
        "criterion_scores": rec.get("criterion_scores"),
        "llm_weighted_score": rec.get("llm_weighted_score"),
        "latency_s": rec.get("latency_s"),
        "model_id": rec.get("model_id"),
        "scholarship_scope": rec.get("scholarship_scope"),
        "scored_at": rec.get("scored_at"),
        "status": rec.get("status"),
        "year": rec.get("year"),
        "sort_key": rec.get("sort_key"),
        "failure": rec.get("failure"),
    }
    # Remove None values
    llm_fields = {k: v for k, v in llm_fields.items() if v is not None}

    if not llm_fields:
        return

    # Convert floats to Decimal
    llm_fields = json.loads(json.dumps(llm_fields), parse_float=Decimal)

    update_parts = []
    expr_values = {}
    for i, (k, v) in enumerate(llm_fields.items()):
        update_parts.append(f"#{k} = :v{i}")
        expr_values[f":v{i}"] = v

    # Need ExpressionAttributeNames because some field names might be reserved
    expr_names = {f"#{k}": k for k in llm_fields.keys()}

    table.update_item(
        Key={"application_key": app_key},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


def _update_application(rec: dict):
    """Write llm_weighted_score and score_status back to the original application record."""
    global _dynamo
    if _dynamo is None:
        _dynamo = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = _dynamo.Table(APPLICATIONS_TABLE)

    app_key = rec.get("application_key")
    if not app_key:
        return

    update_expr = "SET score_status = :status, llm_weighted_score = :score, scored_at = :ts, model_id = :model"
    expr_values = {
        ":status": rec["status"],
        ":score": json.loads(json.dumps(rec.get("llm_weighted_score")), parse_float=Decimal) if rec.get("llm_weighted_score") is not None else None,
        ":ts": rec["scored_at"],
        ":model": rec["model_id"],
    }

    # If scored, also write criterion_scores
    if rec["status"] == "scored" and rec.get("criterion_scores"):
        update_expr += ", criterion_scores = :cs"
        expr_values[":cs"] = json.loads(json.dumps(rec["criterion_scores"]), parse_float=Decimal)

    # If failed, write failure reason
    if rec.get("failure"):
        update_expr += ", score_error = :err"
        expr_values[":err"] = rec["failure"]

    # Remove None values from expression
    expr_values = {k: v for k, v in expr_values.items() if v is not None}

    table.update_item(
        Key={"application_key": app_key},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )


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
        _update_application(rec)
        if rec["status"] == "scored":
            scored += 1
        else:
            failed += 1
            logger.warning(f"Score failed for {rec['application_key']}: {rec['failure']}")

    logger.info(f"Scored={scored} failed={failed} skipped={skipped}")
    return {"statusCode": 200,
            "body": json.dumps({"scored": scored, "failed": failed, "skipped": skipped})}
