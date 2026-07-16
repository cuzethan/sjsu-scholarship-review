import logging
import time
import uuid
from decimal import Decimal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# pull in .env before anything reads aws creds or table names
load_dotenv()

from db import applications_table, rubrics_table, scores_table
from rubric_generator import generate_from_pdf

logger = logging.getLogger("sjsu-api")

app = FastAPI(title="sjsu-api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/rubrics/generate")
async def rubrics_generate(file: UploadFile):
    pdf_bytes = await file.read()
    return generate_from_pdf(pdf_bytes)


def _decimalize(o):
    if isinstance(o, bool):
        return o
    if isinstance(o, float):
        return Decimal(str(o))
    if isinstance(o, dict):
        return {k: _decimalize(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_decimalize(v) for v in o]
    return o


@app.post("/rubrics")
def rubrics_save(questionnaire: dict):
    rubric_id = questionnaire.get("rubric_id") or str(uuid.uuid4())
    item = {**questionnaire, "rubric_id": rubric_id, "approved_at": int(time.time())}
    rubrics_table().put_item(Item=_decimalize(item))
    return {"rubric_id": rubric_id}


@app.get("/rubrics")
def rubrics_list():
    return {"rubrics": rubrics_table().scan().get("Items", [])}


# ---------------------------------------------------------------------------
# Applications + scores (real DynamoDB data for the dashboard)
# ---------------------------------------------------------------------------

# Mirrors the scorer WEIGHTS (lambdas/score-applications/prompt.py) so the UI can
# show per-criterion max + weight.
CRITERION_META = {
    "Extracurricular Activities":   {"max": 1, "weight": 10},
    "Career Goals Essay":           {"max": 4, "weight": 40},
    "Challenge Essay":              {"max": 4, "weight": 30},
    "Initiative & Self-Motivation": {"max": 3, "weight": 10},
    "Creativity":                   {"max": 3, "weight": 10},
}

SCHOLARSHIP_LABELS = {"sjsu_general": "SJSU General"}
DIVERGENCE_THRESHOLD = 15  # AI vs human gap (percent points) that flags a human review


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _round(v):
    return round(v) if v is not None else None


def _short_uuid(u):
    if not u or len(u) < 8:
        return u or ""
    return u[:4] + "\u2026" + u[-4:]


def _scholarship_label(scope):
    return SCHOLARSHIP_LABELS.get(scope, scope or "\u2014")


def _full_scan(table, **kwargs):
    """Paginated scan — DynamoDB returns max 1MB per call."""
    items = []
    resp = table.scan(**kwargs)
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
        items.extend(resp.get("Items", []))
    return items


# In-memory cache for the dashboard list (avoids re-scanning 4800+ items on every request)
_list_cache: dict = {"rows": None, "ts": 0}
_CACHE_TTL = 60  # seconds


def _build_list_rows():
    """Projected scan of both tables (only fields needed for the table view)."""
    apps = _full_scan(
        applications_table(),
        ProjectionExpression="application_key, scholarship_scope, major, academic_level, gpa, #y",
        ExpressionAttributeNames={"#y": "year"},
    )
    scores = _full_scan(
        scores_table(),
        ProjectionExpression="application_key, llm_weighted_score, human_weighted_total",
    )
    score_map = {s.get("application_key"): s for s in scores}

    rows = []
    for a in apps:
        key = a.get("application_key")
        score = score_map.get(key, {})
        ai = _round(_to_float(score.get("llm_weighted_score")))
        human = _round(_to_float(score.get("human_weighted_total")))
        delta = (ai - human) if (ai is not None and human is not None) else None
        needs_human = delta is not None and abs(delta) >= DIVERGENCE_THRESHOLD
        rows.append({
            "application_key": key,
            "student": _short_uuid(key),
            "scholarship": _scholarship_label(a.get("scholarship_scope")),
            "year": a.get("year"),
            "major": a.get("major") or "\u2014",
            "level": a.get("academic_level") or "\u2014",
            "gpa": _to_float(a.get("gpa")),
            "aiPercent": ai,
            "humanPercent": human,
            "delta": delta,
            "lowCount": 0,
            "needsHuman": needs_human,
            "status": "scored" if ai is not None else "pending",
        })
    return rows


@app.get("/applications")
def applications_list():
    """Dashboard rows: sjsu-applications joined with sjsu-scores (AI + human). Cached 60s."""
    now = time.time()
    if _list_cache["rows"] is not None and (now - _list_cache["ts"]) < _CACHE_TTL:
        return {"applications": _list_cache["rows"]}

    try:
        rows = _build_list_rows()
    except Exception:
        logger.exception("failed to read applications/scores")
        raise HTTPException(status_code=502, detail="could not read data store")

    _list_cache["rows"] = rows
    _list_cache["ts"] = now
    logger.info("applications_list: %d apps, %d scored (cache refreshed)", len(rows), sum(1 for r in rows if r["status"] == "scored"))
    return {"applications": rows}


@app.get("/applications/{application_key}")
def application_detail(application_key: str):
    """Review-dialog detail: essays (qa_pairs) + AI criterion scores + human comparison."""
    try:
        a = applications_table().get_item(Key={"application_key": application_key}).get("Item")
        score = scores_table().get_item(Key={"application_key": application_key}).get("Item") or {}
    except Exception:
        logger.exception("failed to read detail for %s", application_key)
        raise HTTPException(status_code=502, detail="could not read data store")

    if not a:
        raise HTTPException(status_code=404, detail="application not found")

    essays = [
        {"id": qa.get("question_id"), "title": qa.get("question"), "text": qa.get("answer") or ""}
        for qa in a.get("qa_pairs", [])
    ]

    human_by_crit = {
        c.get("criterion"): _to_float(c.get("score"))
        for c in (score.get("human_criterion_scores") or [])
    }

    criterion_scores = score.get("criterion_scores") or []
    categories = []
    for cs in criterion_scores:
        name = cs.get("criterion")
        meta = CRITERION_META.get(name, {"max": None, "weight": None})
        evidence = cs.get("evidence") or []
        first = evidence[0] if evidence else {}
        categories.append({
            "key": name,
            "label": name,
            "max": meta["max"],
            "weight": meta["weight"],
            "score": _to_float(cs.get("score")),
            "humanScore": human_by_crit.get(name),
            "confidence": "high",
            "essayId": first.get("question_id"),
            "quote": first.get("quote"),
            "anchor": cs.get("reasoning") or "",
        })

    ai = _round(_to_float(score.get("llm_weighted_score")))
    human = _round(_to_float(score.get("human_weighted_total")))
    delta = (ai - human) if (ai is not None and human is not None) else None
    return {
        "application_key": application_key,
        "student": _short_uuid(application_key),
        "scholarship": _scholarship_label(a.get("scholarship_scope")),
        "year": a.get("year"),
        "major": a.get("major") or "\u2014",
        "level": a.get("academic_level") or "\u2014",
        "gpa": _to_float(a.get("gpa")),
        "status": "scored" if ai is not None else "pending",
        "aiPercent": ai,
        "humanPercent": human,
        "delta": delta,
        "reasoning_summary": score.get("reasoning_summary"),
        "confidence": _to_float(score.get("confidence")),
        "essays": essays,
        "categories": categories,
    }
