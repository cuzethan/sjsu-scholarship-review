"""
Parser: reads .xlsx scholarship application files from S3, normalizes each row
into structured JSON with qa_pairs ready for rubric-based AI scoring.

All essay-to-question mapping is driven by essay_fields in scholarship_config.py.
The parser has zero knowledge of specific essay columns or question text.

Usage:
    python parser.py                    # parse all xlsx files in the bucket
    python parser.py --file "SJSU General Scholarship 26-27 ad hoc report.xlsx"
    python parser.py --output ./output  # write JSON files to a directory
"""

import argparse
import io
import json
import uuid
from pathlib import Path

import boto3
import pandas as pd

from scholarship_config import extract_year, identify_scholarship

# S3 config
BUCKET_NAME = "dxhub-camp-2026-sjsu-scholarship-application-review"
S3_PREFIX = "data/"
AWS_PROFILE = "Samson"


def get_s3_client():
    """Create an S3 client using the configured AWS profile."""
    session = boto3.Session(profile_name=AWS_PROFILE)
    return session.client("s3")


def list_xlsx_files(s3_client) -> list[str]:
    """List all .xlsx files in the S3 bucket under the data prefix."""
    response = s3_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=S3_PREFIX)
    files = []
    for obj in response.get("Contents", []):
        key = obj["Key"]
        if key.endswith(".xlsx") and not key.split("/")[-1].startswith("~$"):
            files.append(key)
    return files


def read_xlsx_from_s3(s3_client, s3_key: str) -> tuple[pd.DataFrame, str]:
    """Download an xlsx file from S3 and return it as a DataFrame + sheet name."""
    response = s3_client.get_object(Bucket=BUCKET_NAME, Key=s3_key)
    body = response["Body"].read()
    xl = pd.ExcelFile(io.BytesIO(body), engine="openpyxl")
    sheet_name = xl.sheet_names[0]
    df = xl.parse(sheet_name)
    return df, sheet_name


def clean_value(value, is_numeric: bool = False):
    """Clean a cell value: handle NaN, strip strings, avoid float artifacts."""
    if pd.isna(value):
        return None
    if is_numeric:
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    if isinstance(value, float):
        return str(value) if value != int(value) else str(int(value))
    if isinstance(value, str):
        return value.strip() or None
    return str(value)


# Fields that should be parsed as numeric
NUMERIC_FIELDS = {"gpa", "self_reported_gpa"}


def normalize_row(
    row: pd.Series,
    config: dict,
    year: str,
    file_name: str,
    sheet_name: str,
    row_number: int,
) -> dict | None:
    """Convert a single DataFrame row into a normalized application dict.

    Builds qa_pairs entirely from config['essay_fields'].
    Builds structured fields entirely from config['column_map'].
    """
    column_map = config["column_map"]
    essay_fields = config["essay_fields"]

    # --- Structured fields from column_map ---
    record = {
        "application_id": str(uuid.uuid4()),
        "scholarship_type": config["scholarship_type"],
        "rubric_id": config["rubric_id"],
        "year": year,
        "student_name": None,
        "availability_id": None,
        "gpa": None,
        "self_reported_gpa": None,
        "academic_program": None,
        "academic_level": None,
        "major": None,
        "qa_pairs": [],
        "source": {
            "file_name": file_name,
            "sheet_name": sheet_name,
            "row_number": row_number,
        },
    }

    for raw_col, field_name in column_map.items():
        if raw_col not in row.index:
            continue
        is_numeric = field_name in NUMERIC_FIELDS
        value = clean_value(row[raw_col], is_numeric=is_numeric)

        if field_name == "availability_id":
            record["availability_id"] = str(row[raw_col]).strip() if not pd.isna(row[raw_col]) else None
        else:
            record[field_name] = value

    # Skip rows where student_name is missing
    if record["student_name"] is None:
        return None

    # --- qa_pairs from essay_fields ---
    for essay_def in essay_fields:
        # Try primary column, then alt_columns
        answer = None
        columns_to_try = [essay_def["raw_column"]] + essay_def.get("alt_columns", [])

        for col in columns_to_try:
            if col in row.index:
                answer = clean_value(row[col])
                if answer is not None:
                    break

        # Skip if no answer found
        if answer is None:
            continue

        qa_pair = {
            "question_id": essay_def["question_id"],
            "question": essay_def["question"],
            "answer": answer,
        }

        # Include topic if defined
        if "topic" in essay_def:
            qa_pair["topic"] = essay_def["topic"]

        record["qa_pairs"].append(qa_pair)

    return record


def parse_file(s3_client, s3_key: str) -> list[dict]:
    """Parse a single xlsx file from S3 into a list of normalized application dicts."""
    filename = s3_key.split("/")[-1]

    # Identify scholarship type
    config = identify_scholarship(filename)
    if config is None:
        print(f"  SKIP: No config found for '{filename}'")
        return []

    # Extract year
    year = extract_year(filename)
    if year is None:
        print(f"  WARN: Could not extract year from '{filename}', using 'unknown'")
        year = "unknown"

    # Read the file
    df, sheet_name = read_xlsx_from_s3(s3_client, s3_key)
    print(f"  Parsing: {filename} | {len(df)} rows | scholarship: {config['scholarship_type']} | year: {year}")

    # Normalize each row
    records = []
    for idx, row in df.iterrows():
        record = normalize_row(
            row,
            config,
            year,
            file_name=filename,
            sheet_name=sheet_name,
            row_number=idx + 2,  # +2: 1-indexed + header row
        )
        if record is not None:
            records.append(record)

    print(f"  -> {len(records)} applications parsed")
    return records


def parse_all(file_filter: str | None = None) -> list[dict]:
    """Parse all (or one) xlsx files from S3.

    Args:
        file_filter: If provided, only parse files containing this substring.

    Returns:
        List of all normalized application dicts.
    """
    s3_client = get_s3_client()
    xlsx_files = list_xlsx_files(s3_client)

    if file_filter:
        xlsx_files = [f for f in xlsx_files if file_filter in f]

    if not xlsx_files:
        print("No matching xlsx files found.")
        return []

    print(f"Found {len(xlsx_files)} xlsx file(s) to parse:\n")

    all_records = []
    for s3_key in sorted(xlsx_files):
        records = parse_file(s3_client, s3_key)
        all_records.extend(records)

    print(f"\nTotal: {len(all_records)} applications parsed across {len(xlsx_files)} file(s)")
    return all_records


def main():
    parser = argparse.ArgumentParser(description="Parse scholarship xlsx files from S3")
    parser.add_argument("--file", type=str, help="Filter to a specific file (substring match)")
    parser.add_argument("--output", type=str, help="Directory to write output JSON files")
    parser.add_argument("--sample", type=int, default=0, help="Print N sample records to stdout")
    args = parser.parse_args()

    records = parse_all(file_filter=args.file)

    if args.sample and records:
        print(f"\n--- Sample ({min(args.sample, len(records))} records) ---\n")
        for r in records[: args.sample]:
            print(json.dumps(r, indent=2))
            print()

    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

        from collections import defaultdict

        grouped = defaultdict(list)
        for r in records:
            key = f"{r['rubric_id']}_{r['year']}"
            grouped[key].append(r)

        for key, group in grouped.items():
            out_path = output_dir / f"{key}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(group, f, indent=2, ensure_ascii=False)
            print(f"  Wrote {len(group)} records to {out_path}")


if __name__ == "__main__":
    main()
