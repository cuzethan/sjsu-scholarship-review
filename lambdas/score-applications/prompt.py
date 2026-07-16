"""
prompt.py — shared SJSU General prompt + rubric path (Phase 1).

ONE prompt-building path, ONE rubric file (sjsu_general_rubric.md). No
per-year, no per-department branching. Used by the scoring Lambda; the
evaluation harness points at the same rubric content.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

RUBRIC_PATH = Path(__file__).resolve().parent / "sjsu_general_rubric.md"

# Strict output schema (also enforced by validate()).
SCHEMA_INSTRUCTIONS = """
Return ONLY a single JSON object (no prose, no markdown fences) shaped exactly:

{
  "criterion_scores": [
    { "criterion": "string  // rubric category name",
      "score": 0,           // number within that category's scale
      "reasoning": "string",
      "evidence": [ { "question_id": "string", "quote": "string" } ] }
  ],
  "weighted_total": 0,      // sum of criterion scores (max 15)
  "reasoning_summary": "string  // 1-2 sentence overall justification",
  "confidence": 0.0         // 0.0 to 1.0
}

Rules:
- One entry per rubric category (5 total).
- Score only from provided application content; do not invent facts.
- Quote exact application text in evidence; empty list if none, and say so in reasoning.
- Return ONLY the JSON object.
"""


@lru_cache(maxsize=1)
def load_rubric() -> str:
    return RUBRIC_PATH.read_text(encoding="utf-8")


def build_system_prompt() -> str:
    """Shared SJSU General system prompt = rubric + strict schema instructions."""
    return load_rubric() + "\n\n" + SCHEMA_INSTRUCTIONS


def build_user_message(app: dict) -> str:
    """Application content only (no human scores)."""
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


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response (strips markdown fences)."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        brace = re.search(r"(\{.*\})", text, re.DOTALL)
        if brace:
            text = brace.group(1)
    return json.loads(text)


class SchemaError(ValueError):
    pass


def validate(obj) -> dict:
    """Validate a scoring response against the strict schema."""
    if not isinstance(obj, dict):
        raise SchemaError("top-level must be an object")
    cs = obj.get("criterion_scores")
    if not isinstance(cs, list) or not cs:
        raise SchemaError("criterion_scores must be a non-empty list")
    for i, c in enumerate(cs):
        if not isinstance(c, dict):
            raise SchemaError(f"criterion_scores[{i}] must be an object")
        if not isinstance(c.get("criterion"), str) or not c["criterion"].strip():
            raise SchemaError(f"criterion_scores[{i}].criterion must be a non-empty string")
        if isinstance(c.get("score"), bool) or not isinstance(c.get("score"), (int, float)):
            raise SchemaError(f"criterion_scores[{i}].score must be a number")
        if not isinstance(c.get("reasoning"), str):
            raise SchemaError(f"criterion_scores[{i}].reasoning must be a string")
        ev = c.get("evidence", [])
        if not isinstance(ev, list):
            raise SchemaError(f"criterion_scores[{i}].evidence must be a list")
    if isinstance(obj.get("weighted_total"), bool) or not isinstance(obj.get("weighted_total"), (int, float)):
        raise SchemaError("weighted_total must be a number")
    if not isinstance(obj.get("reasoning_summary", ""), str):
        raise SchemaError("reasoning_summary must be a string")
    conf = obj.get("confidence")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
        raise SchemaError("confidence must be a number in [0,1]")
    return obj
