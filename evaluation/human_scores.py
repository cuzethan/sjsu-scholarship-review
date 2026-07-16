"""
human_scores.py — load human reviewer scores from local score sheets.

Real score-sheet format (discovered from the actual data):
- A `Candidate` column = 12 hex chars (uppercase) == last 12 hex of the student UUID.
- Per-criterion columns named "Chair: ..." whose cells look like:
      "Average score: 1.50 Jane  Huynh: 2 Yue  Luo: 1 "
  i.e. an average across reviewers, followed by "<Reviewer Name>: <int>" pairs.
- Often a numeric "Chair Total Score" (sum of per-criterion averages) and
  "Chair Average Score" (mean of per-criterion averages).

We therefore:
- parse each "Chair:" cell into (criterion_avg, {reviewer: score})
- human comparator = "Chair Total Score" if present & numeric,
  else the sum of parsed per-criterion averages
- capture per-reviewer totals (summed across criteria) for individual-reviewer
  comparison

Join is deterministic (last 12 hex). No fuzzy matching. Sheets without a
Candidate column, or with no Chair criterion/total columns, are EXCLUDED and
reported. Ambiguous (duplicate) candidates are dropped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

CANDIDATE_COL_PATTERNS = ["candidate"]
CRITERION_PREFIX = "chair:"          # criterion columns start with "Chair:"
TOTAL_COL_NAMES = {"chair total score"}
AVG_RE = re.compile(r"average\s*score\s*:\s*([-\d.]+)", re.IGNORECASE)
# "<Name>: <int>" reviewer pairs (name may contain spaces, '.', '-', "'")
REVIEWER_RE = re.compile(r"([A-Za-z][A-Za-z.\-'’ ]*?):\s*(-?\d+)")

# Map a score-sheet filename to the application rubric_id (deterministic keyword
# match — used only to SCOPE the join to the right scholarship, never to match
# individual candidates). Phase 1: SJSU General only; specialized sheets are
# intentionally NOT mapped (they resolve to None and are excluded/reported).
RUBRIC_KEYWORDS = [
    ("sjsu general", "sjsu-general"),
    # --- UNSUPPORTED in phase 1 (extension path only) ---
    # ("engineering", "coeng-deans"),
    # ("lurie", "lurie-coed-general"),
    # ("education", "lurie-coed-general"),
    # ("physics", "physics-dept"),
]

_YEAR_RE = re.compile(r"(\d{2}-\d{2})")


def rubric_id_from_filename(filename: str) -> str | None:
    name = filename.lower()
    for kw, rid in RUBRIC_KEYWORDS:
        if kw in name:
            return rid
    return None


def year_from_filename(filename: str) -> str | None:
    m = _YEAR_RE.search(filename)
    return m.group(1) if m else None


def candidate_key_from_uuid(student_uuid: str) -> str | None:
    """Last 12 hex chars of the UUID (final segment). Deterministic, no fuzzing."""
    if not student_uuid:
        return None
    hex_only = re.sub(r"[^0-9a-fA-F]", "", str(student_uuid))
    if len(hex_only) < 12:
        return None
    return hex_only[-12:].lower()


def _norm_candidate(raw) -> str | None:
    if pd.isna(raw):
        return None
    key = re.sub(r"[^0-9a-fA-F]", "", str(raw)).lower()
    return key[-12:] if len(key) >= 12 else None


def find_candidate_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        if any(p in str(col).strip().lower() for p in CANDIDATE_COL_PATTERNS):
            return col
    return None


def find_criterion_columns(df: pd.DataFrame) -> list:
    return [c for c in df.columns if str(c).strip().lower().startswith(CRITERION_PREFIX)]


def find_total_column(df: pd.DataFrame) -> str | None:
    for c in df.columns:
        if str(c).strip().lower() in TOTAL_COL_NAMES:
            return c
    return None


def parse_criterion_cell(text) -> tuple[float | None, dict]:
    """Parse 'Average score: X ...Name: n...' -> (avg, {reviewer: score})."""
    if pd.isna(text):
        return None, {}
    s = str(text)
    avg = None
    m = AVG_RE.search(s)
    if m:
        try:
            avg = float(m.group(1))
        except ValueError:
            avg = None
    # strip the "Average score: X" prefix so it isn't parsed as a reviewer
    remainder = AVG_RE.sub("", s)
    reviewers = {}
    for name, val in REVIEWER_RE.findall(remainder):
        name = name.strip()
        if not name or name.lower() == "average score":
            continue
        try:
            reviewers[name] = int(val)
        except ValueError:
            continue
    return avg, reviewers


def load_score_sheet(path: Path) -> dict:
    result = {"file": path.name, "included": False, "reason": "",
              "candidate_col": None, "criterion_cols": [], "total_col": None,
              "by_candidate": {}, "ambiguous_candidates": []}

    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
        df = xl.parse(xl.sheet_names[0])
    except Exception as e:
        result["reason"] = f"could not read: {e}"
        return result

    cand_col = find_candidate_column(df)
    if cand_col is None:
        result["reason"] = "no Candidate column (no deterministic join key)"
        return result
    result["candidate_col"] = cand_col

    criterion_cols = find_criterion_columns(df)
    total_col = find_total_column(df)
    result["criterion_cols"] = [str(c) for c in criterion_cols]
    result["total_col"] = str(total_col) if total_col is not None else None

    if not criterion_cols and total_col is None:
        result["reason"] = "no 'Chair:' criterion columns and no 'Chair Total Score'"
        return result

    by_candidate = {}
    ambiguous = set()
    for _, row in df.iterrows():
        key = _norm_candidate(row[cand_col])
        if key is None:
            continue
        if key in by_candidate:
            ambiguous.add(key)
            continue

        criterion_avgs = {}
        reviewer_totals = {}
        for c in criterion_cols:
            avg, reviewers = parse_criterion_cell(row[c])
            if avg is not None:
                criterion_avgs[str(c)] = avg
            for name, val in reviewers.items():
                reviewer_totals[name] = reviewer_totals.get(name, 0) + val

        # human comparator (total)
        human_total = None
        if total_col is not None:
            tv = pd.to_numeric(row[total_col], errors="coerce")
            if pd.notna(tv):
                human_total = float(tv)
        if human_total is None and criterion_avgs:
            human_total = sum(criterion_avgs.values())

        if human_total is None:
            continue

        by_candidate[key] = {
            "human_total": human_total,
            "criterion_avgs": criterion_avgs,
            "reviewer_totals": reviewer_totals,
        }

    for key in ambiguous:
        by_candidate.pop(key, None)

    result["by_candidate"] = by_candidate
    result["ambiguous_candidates"] = sorted(ambiguous)
    result["included"] = len(by_candidate) > 0
    if not result["included"]:
        result["reason"] = "no usable rows after parse/dedup"
    return result


def load_all_scores(scores_dir: Path) -> tuple[dict, list[dict]]:
    """Returns (candidate_index, sheet_reports).

    candidate_index is keyed by (rubric_id, year, candidate_key) so the join is
    scoped to the correct scholarship + year (a student who applied to multiple
    scholarships is kept once per scholarship). Value:
        {human_total, criterion_avgs, reviewer_totals, source_file}
    """
    candidate_index = {}
    cross_ambiguous = set()
    reports = []
    if not scores_dir.exists():
        return candidate_index, reports

    for path in sorted(scores_dir.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        r = load_score_sheet(path)
        rid = rubric_id_from_filename(path.name)
        year = year_from_filename(path.name)
        r["rubric_id"] = rid
        r["year"] = year
        # a sheet needs a scholarship identity to scope the join
        if r["included"] and rid is None:
            r["included"] = False
            r["reason"] = "cannot determine scholarship identity from filename"
        reports.append({k: v for k, v in r.items() if k != "by_candidate"})
        if not r["included"]:
            continue
        for cand_key, val in r["by_candidate"].items():
            idx_key = (rid, year, cand_key)
            if idx_key in candidate_index:
                cross_ambiguous.add(idx_key)
                continue
            candidate_index[idx_key] = {**val, "source_file": path.name}

    for key in cross_ambiguous:
        candidate_index.pop(key, None)
    return candidate_index, reports
