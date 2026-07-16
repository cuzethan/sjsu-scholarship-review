"""
local_parser.py — reuse the existing repo parser to parse LOCAL xlsx files.

The repo parser (Parser/parser.py) reads from S3. We reuse its row-normalization
logic (normalize_row, clean_value) and scholarship_config (identify_scholarship,
extract_year) unchanged, but feed it a locally-read DataFrame so the user can
upload files themselves. We do NOT rebuild the parser.

Note: the repo parser stores the anonymized student UUID (the "Student" column)
in the field `student_name`. We surface it as `student_uuid` for clarity.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from config import PARSER_DIR

# Reuse the existing parser package
sys.path.insert(0, str(PARSER_DIR))
import parser as repo_parser  # noqa: E402  (Parser/parser.py)
from scholarship_config import extract_year, identify_scholarship  # noqa: E402


def parse_local_xlsx(path: Path) -> list[dict]:
    """Parse a single local application xlsx into normalized application dicts.

    Reuses repo_parser.normalize_row (config-driven qa_pairs). Returns records
    with an added `student_uuid` alias (from the parser's `student_name`).
    """
    filename = path.name
    config = identify_scholarship(filename)
    if config is None:
        return []

    year = extract_year(filename) or "unknown"

    xl = pd.ExcelFile(path, engine="openpyxl")
    sheet_name = xl.sheet_names[0]
    df = xl.parse(sheet_name)

    records = []
    for idx, row in df.iterrows():
        record = repo_parser.normalize_row(
            row, config, year,
            file_name=filename, sheet_name=sheet_name, row_number=idx + 2,
        )
        if record is None:
            continue
        # Surface the student UUID under a clear name (parser calls it student_name)
        record["student_uuid"] = record.get("student_name")
        records.append(record)

    return records


def parse_all_applications(applications_dir: Path) -> tuple[list[dict], list[dict]]:
    """Parse every xlsx in applications_dir.

    Returns (records, skipped) where skipped is a list of
    {file, reason} for files with no matching scholarship config.
    """
    records, skipped = [], []
    if not applications_dir.exists():
        return records, skipped

    for path in sorted(applications_dir.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        config = identify_scholarship(path.name)
        if config is None:
            skipped.append({"file": path.name, "reason": "no matching scholarship config"})
            continue
        recs = parse_local_xlsx(path)
        if not recs:
            skipped.append({"file": path.name, "reason": "parsed 0 usable rows"})
            continue
        records.extend(recs)

    return records, skipped
