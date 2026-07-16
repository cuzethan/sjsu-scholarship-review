"""
schema.py — strict output JSON schema for model scoring responses + validation.

Every model must return JSON conforming to this schema. The schema is designed
to support evaluation against human scores:
- per-criterion scores (comparable to per-category human rubric scores)
- evidence quotes tied to question_ids (auditability)
- a total_score and confidence (comparable to human composite + used for analysis)

We validate with a small hand-rolled validator (no jsonschema dependency) so the
harness stays dependency-light.
"""

from __future__ import annotations

# The strict schema, expressed as an example + rules. Included verbatim in the
# system prompt so the model knows exactly what to return.
OUTPUT_SCHEMA_EXAMPLE = {
    "criterion_scores": [
        {
            "criterion": "string",
            "score": 0,
            "reasoning": "string",
            "evidence": [
                {"question_id": "string", "quote": "string"}
            ],
        }
    ],
    "total_score": 0,
    "confidence": 0.0,
}

SCHEMA_INSTRUCTIONS = """
You MUST return ONLY a single JSON object (no prose, no markdown fences) with this exact shape:

{
  "criterion_scores": [
    {
      "criterion": "string  // the rubric category name",
      "score": 0,          // numeric score for this criterion, within the rubric's scale
      "reasoning": "string // why this score, grounded only in the application",
      "evidence": [
        { "question_id": "string // which application question this quote came from",
          "quote": "string      // exact quote from the application supporting the score" }
      ]
    }
  ],
  "total_score": 0,        // sum (or rubric-defined composite) of criterion scores
  "confidence": 0.0        // your confidence in this scoring, 0.0 to 1.0
}

Rules:
- One entry in "criterion_scores" per rubric category.
- "score" must be a number within the scale defined by the rubric for that category.
- Quote EXACT text from the application in "evidence". If no evidence exists for a
  criterion, use an empty "evidence" list and say so in "reasoning".
- Do NOT invent facts. Score only from the provided application content.
- Return ONLY the JSON object. No commentary, no markdown.
"""


class SchemaError(ValueError):
    """Raised when a model response does not conform to the strict schema."""


def validate(obj) -> dict:
    """Validate a parsed response against the strict schema.

    Returns the object (unchanged) if valid; raises SchemaError otherwise.
    """
    if not isinstance(obj, dict):
        raise SchemaError(f"top-level must be an object, got {type(obj).__name__}")

    if "criterion_scores" not in obj:
        raise SchemaError("missing 'criterion_scores'")
    cs = obj["criterion_scores"]
    if not isinstance(cs, list) or not cs:
        raise SchemaError("'criterion_scores' must be a non-empty list")

    for i, c in enumerate(cs):
        if not isinstance(c, dict):
            raise SchemaError(f"criterion_scores[{i}] must be an object")
        if not isinstance(c.get("criterion"), str) or not c["criterion"].strip():
            raise SchemaError(f"criterion_scores[{i}].criterion must be a non-empty string")
        if not isinstance(c.get("score"), (int, float)) or isinstance(c.get("score"), bool):
            raise SchemaError(f"criterion_scores[{i}].score must be a number")
        if not isinstance(c.get("reasoning"), str):
            raise SchemaError(f"criterion_scores[{i}].reasoning must be a string")
        ev = c.get("evidence", [])
        if not isinstance(ev, list):
            raise SchemaError(f"criterion_scores[{i}].evidence must be a list")
        for j, e in enumerate(ev):
            if not isinstance(e, dict):
                raise SchemaError(f"criterion_scores[{i}].evidence[{j}] must be an object")
            if not isinstance(e.get("question_id", ""), str):
                raise SchemaError(f"criterion_scores[{i}].evidence[{j}].question_id must be a string")
            if not isinstance(e.get("quote", ""), str):
                raise SchemaError(f"criterion_scores[{i}].evidence[{j}].quote must be a string")

    if not isinstance(obj.get("total_score"), (int, float)) or isinstance(obj.get("total_score"), bool):
        raise SchemaError("'total_score' must be a number")
    conf = obj.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool):
        raise SchemaError("'confidence' must be a number")
    if not (0.0 <= float(conf) <= 1.0):
        raise SchemaError("'confidence' must be between 0.0 and 1.0")

    return obj
