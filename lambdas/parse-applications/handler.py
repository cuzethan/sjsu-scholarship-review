"""
Lambda: parse-applications

Triggered by S3 event when a new .xlsx lands in the data/ prefix.
Parses the spreadsheet into normalized application records (with qa_pairs)
and writes them to DynamoDB (sjsu-applications table).

Parser logic mirrors Parser/parser.py from the feat/parser branch.
"""

import io
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote_plus

import boto3
import pandas as pd

from scholarship_config import extract_year, identify_scholarship

logger = logging.getLogger()
logger.setLevel(logging.INFO)

APPLICATIONS_TABLE = os.environ.get("APPLICATIONS_TABLE", "sjsu-applications")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

# Fields that should be parsed as numeric
NUMERIC_FIELDS = {"gpa", "self_reported_gpa"}


def get_dynamo_table():
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return dynamodb.Table(APPLICATIONS_TABLE)


def read_xlsx_from_s3(bucket: str, key: str) -> tuple[pd.DataFrame, str]:
    """Download an xlsx file from S3 and return as DataFrame + sheet name."""
    s3 = boto3.client("s3", region_name=AWS_REGION)
    response = s3.get_object(Bucket=bucket, Key=key)
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


def normalize_row(
    row: pd.Series,
    config: dict,
    year: str,
    file_name: str,
    sheet_name: str,
    row_number: int,
) -> dict | None:
    """Convert a single DataFrame row into a normalized application dict.

    Builds qa_pairs from config['essay_fields'].
    Builds structured fields from config['column_map'].
    """
    column_map = config["column_map"]
    essay_fields = config["essay_fields"]

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

    # --- Structured fields from column_map ---
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
        answer = None
        columns_to_try = [essay_def["raw_column"]] + essay_def.get("alt_columns", [])

        for col in columns_to_try:
            if col in row.index:
                answer = clean_value(row[col])
                if answer is not None:
                    break

        if answer is None:
            continue

        qa_pair = {
            "question_id": essay_def["question_id"],
            "question": essay_def["question"],
            "answer": answer,
        }
        if "topic" in essay_def:
            qa_pair["topic"] = essay_def["topic"]

        record["qa_pairs"].append(qa_pair)

    return record


def parse_file(bucket: str, key: str) -> list[dict]:
    """Parse a single xlsx file from S3 into normalized application dicts."""
    filename = key.split("/")[-1]

    config = identify_scholarship(filename)
    if config is None:
        logger.warning(f"No config found for '{filename}', skipping.")
        return []

    year = extract_year(filename)
    if year is None:
        logger.warning(f"Could not extract year from '{filename}', using 'unknown'.")
        year = "unknown"

    df, sheet_name = read_xlsx_from_s3(bucket, key)
    logger.info(f"Parsing: {filename} | {len(df)} rows | scholarship: {config['scholarship_type']} | year: {year}")

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

    logger.info(f"Parsed {len(records)} applications from {filename}")
    return records


def write_to_dynamodb(records: list[dict], source_file: str):
    """Batch write parsed records to DynamoDB. PK is application_id (UUID, always unique)."""
    table = get_dynamo_table()
    parsed_at = datetime.now(timezone.utc).isoformat()
    written = 0

    with table.batch_writer() as batch:
        for record in records:
            item = {
                "application_id": record["application_id"],
                "source_file": source_file,
                "parsed_at": parsed_at,
            }

            # Add non-None top-level fields
            for field in ("scholarship_type", "rubric_id", "year", "student_name",
                          "availability_id", "academic_program", "academic_level", "major"):
                if record.get(field) is not None:
                    item[field] = record[field]

            # Numeric fields — store as string for DynamoDB compatibility
            for field in ("gpa", "self_reported_gpa"):
                if record.get(field) is not None:
                    item[field] = str(record[field])

            # qa_pairs — store as list (DynamoDB handles nested structures)
            if record.get("qa_pairs"):
                item["qa_pairs"] = record["qa_pairs"]

            # Source provenance
            if record.get("source"):
                item["source"] = record["source"]

            batch.put_item(Item=item)
            written += 1

    logger.info(f"Wrote {written} records to {APPLICATIONS_TABLE}")
    return written


def handler(event, context):
    """Lambda entry point - triggered by S3 event."""
    logger.info(f"Event received: {json.dumps(event)}")

    records_written = 0

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        # Only process .xlsx files in data/ prefix
        if not key.startswith("data/") or not key.endswith(".xlsx"):
            logger.info(f"Skipping non-xlsx or non-data/ file: {key}")
            continue

        # Skip temp files (Excel lock files)
        filename = key.split("/")[-1]
        if filename.startswith("~$"):
            logger.info(f"Skipping temp file: {key}")
            continue

        logger.info(f"Processing: s3://{bucket}/{key}")

        try:
            applications = parse_file(bucket, key)
            if applications:
                written = write_to_dynamodb(applications, source_file=key)
                records_written += written
            else:
                logger.info(f"No applications parsed from {key}")
        except Exception as e:
            logger.error(f"Error processing {key}: {e}", exc_info=True)
            raise

    return {
        "statusCode": 200,
        "body": json.dumps({"message": f"Processed {records_written} application records"}),
    }
