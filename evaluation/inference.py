"""
inference.py — run Bedrock models against eval records.

Uses the Bedrock Converse API (uniform across providers) with deterministic
settings (temperature=0, top_p=1). Captures raw response, parsed+validated JSON,
latency, token usage, and any failure mode. A model that is unavailable or errors
does NOT fail the run — it is recorded and skipped.
"""

from __future__ import annotations

import json
import re
import time

import boto3

from config import AWS_PROFILE, AWS_REGION, MAX_TOKENS, TEMPERATURE, TOP_P, invoke_id
from prompts import build_system_prompt, build_user_message
from schema import SchemaError, validate

_session = None
_bedrock = None
_bedrock_ctrl = None


def _clients():
    global _session, _bedrock, _bedrock_ctrl
    if _session is None:
        _session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
        _bedrock = _session.client("bedrock-runtime")
        _bedrock_ctrl = _session.client("bedrock")
    return _bedrock, _bedrock_ctrl


def list_available_model_ids() -> set[str]:
    """Return the set of foundation-model ids present in the account/region."""
    _, ctrl = _clients()
    ids = set()
    resp = ctrl.list_foundation_models()
    for m in resp.get("modelSummaries", []):
        ids.add(m["modelId"])
    return ids


def resolve_models(models: list[dict]) -> list[dict]:
    """Mark each shortlisted model available/unavailable; apply alternates.

    Adds keys: available (bool), effective_id (str|None), substituted (bool),
    unavailable_reason (str|None).
    """
    available_ids = list_available_model_ids()
    from config import USE_ALTERNATES

    resolved = []
    for m in models:
        entry = dict(m)
        if m["id"] in available_ids:
            entry.update(available=True, effective_id=m["id"], substituted=False,
                         unavailable_reason=None)
        elif USE_ALTERNATES and m.get("alt") and m["alt"] in available_ids:
            entry.update(available=True, effective_id=m["alt"], substituted=True,
                         unavailable_reason=f"'{m['id']}' not in account; using alt '{m['alt']}'")
        else:
            entry.update(available=False, effective_id=None, substituted=False,
                         unavailable_reason=f"'{m['id']}' not available in account/region")
        resolved.append(entry)
    return resolved


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        brace = re.search(r"(\{.*\})", text, re.DOTALL)
        if brace:
            text = brace.group(1)
    return json.loads(text)


def score_one(model: dict, record: dict) -> dict:
    """Run one model on one record. Returns a result dict (never raises)."""
    bedrock, _ = _clients()
    eff_id = model.get("effective_id") or model["id"]
    # profile models need us. prefix; build a temp dict carrying the effective id
    inv_id = invoke_id({"id": eff_id, "inference_type": model.get("inference_type")})

    system_prompt = build_system_prompt(record["rubric_id"])
    user_message = build_user_message(record)

    result = {
        "model_id": model["id"],
        "effective_id": eff_id,
        "substituted": model.get("substituted", False),
        "candidate_key": record["candidate_key"],
        "rubric_id": record["rubric_id"],
        "scholarship_type": record["scholarship_type"],
        "year": record["year"],
        "latency_s": None,
        "input_tokens": None,
        "output_tokens": None,
        "raw": None,
        "parsed": None,
        "valid": False,
        "failure": None,
    }

    t0 = time.time()
    try:
        # Deterministic settings. Anthropic models reject temperature + top_p
        # together, so for those we send temperature only (still deterministic).
        infcfg = {"maxTokens": MAX_TOKENS, "temperature": TEMPERATURE}
        if "anthropic." not in inv_id:
            infcfg["topP"] = TOP_P
        resp = bedrock.converse(
            modelId=inv_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig=infcfg,
        )
        result["latency_s"] = round(time.time() - t0, 3)
        usage = resp.get("usage", {})
        result["input_tokens"] = usage.get("inputTokens")
        result["output_tokens"] = usage.get("outputTokens")
        # Extract text from response — handle different model response shapes
        content = resp.get("output", {}).get("message", {}).get("content", [])
        text = ""
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text = block["text"]
                break
            elif isinstance(block, str):
                text = block
                break
        if not text:
            text = str(content)
        result["raw"] = text
        try:
            parsed = _extract_json(text)
            validate(parsed)
            result["parsed"] = parsed
            result["valid"] = True
        except (json.JSONDecodeError, SchemaError) as e:
            result["failure"] = f"parse/schema: {e}"
    except Exception as e:
        result["latency_s"] = round(time.time() - t0, 3)
        result["failure"] = f"inference: {type(e).__name__}: {e}"

    return result


def run_inference(resolved_models: list[dict], records: list[dict]) -> list[dict]:
    """Run every available model over every record. Returns flat list of results."""
    results = []
    available = [m for m in resolved_models if m.get("available")]
    for m in available:
        for rec in records:
            results.append(score_one(m, rec))
    return results
