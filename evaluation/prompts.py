"""
prompts.py — build the system prompt (rubric) and user message (application).

The LLM input is ONLY:
- the scholarship-specific rubric/system prompt (prompts/*.md)
- the strict output-schema instructions
- the parsed application QA content

It NEVER contains the human score.
"""

from __future__ import annotations

from functools import lru_cache

from config import PROMPTS_DIR, RUBRIC_FILES
from schema import SCHEMA_INSTRUCTIONS


@lru_cache(maxsize=None)
def load_rubric(rubric_id: str) -> str:
    fname = RUBRIC_FILES.get(rubric_id)
    if not fname:
        raise ValueError(f"No rubric file mapped for rubric_id '{rubric_id}'")
    return (PROMPTS_DIR / fname).read_text(encoding="utf-8")


def build_system_prompt(rubric_id: str) -> str:
    """Rubric text + strict schema instructions."""
    return load_rubric(rubric_id) + "\n\n" + SCHEMA_INSTRUCTIONS


def build_user_message(record: dict) -> str:
    """Application content only. No human scores."""
    lines = []
    if record.get("gpa"):
        lines.append(f"GPA: {record['gpa']}")
    if record.get("self_reported_gpa"):
        lines.append(f"Self-Reported GPA: {record['self_reported_gpa']}")
    if record.get("major"):
        lines.append(f"Major: {record['major']}")
    if record.get("academic_level"):
        lines.append(f"Academic Level: {record['academic_level']}")
    if record.get("academic_program"):
        lines.append(f"Academic Program: {record['academic_program']}")

    lines.append("\n--- Application Essays ---\n")
    for qa in record.get("qa_pairs", []):
        topic = f" (topic: {qa['topic']})" if qa.get("topic") else ""
        lines.append(f"Question [{qa.get('question_id', '?')}]{topic}: {qa.get('question', '')}")
        lines.append(f"Answer: {qa.get('answer', '')}\n")

    return "\n".join(lines)
