"""
Lambda: parse-applications

Triggered by S3 event when a new .xlsx lands in the data/ prefix.
Parses the spreadsheet into normalized application records and writes them
to DynamoDB (sjsu-applications table).
"""

import io
import json
import logging
import os
from datetime import datetime, timezone

import boto3
import pandas as pd

from scholarship_config import SCHOLARSHIP_CONFIGS, extract_year, identify_scholarship

logger = logging.getLogger()
logger.setLevel(logging.INFO)

APPLICATIONS_TABLE = os.environ.get("APPLICATIONS_TABLE", "sjsu-applications")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")


def get_dynamo_table():
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return dynamodb.Table(APPLICATIONS_TABLE)


def read_xlsx_from_s3(bucket: str, key: str) -> pd.DataFrame:
    """Download an xlsx file from S3 and return it as a DataFrame."""
    s3 = boto3.client("s3", region_name=AWS_REGION)
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()
    return pd.read_excel(io.BytesIO(body), engine="openpyxl")


def normalize_row(row: pd.Series, config: dict, year: str) -> dict:
    """Convert a single DataFrame row into a normalized application dict."""
    column_map = config["column_map"]

    record = {
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
        "essays": {
            "career_goals": None,
            "challenge_or_mistake": None,
            "department_specific": None,
            "department_essay_topic": config["department_essay_topic"],
            "extracurricular_activities": None,
        },
    }

    for raw_col, normalized_field in column_map.items():
        if raw_col not in row.index:
            continue

        value = row[raw_col]

        if pd.isna(value):
            value = None
        elif isinstance(value, float) and normalized_field not in ("gpa", "self_reported_gpa"):
            value = str(value) if value != int(value) else str(int(value))
        elif isinstance(value, str):
            value = value.strip()

        if normalized_field == "student_name":
            record["student_name"] = value
        elif normalized_field == "availability_id":
            if value is not None:
                try:
                    record["availability_id"] = str(int(float(str(value))))
                except (ValueError, TypeError):
                    record["availability_id"] = str(value)
        elif normalized_field == "gpa":
            record["gpa"] = str(float(value)) if value is not None else None
        elif normalized_field == "self_reported_gpa":
            record["self_reported_gpa"] = str(value) if value is not None else None
        elif normalized_field == "academic_program":
            record["academic_program"] = value
        elif normalized_field == "academic_level":
            record["academic_level"] = value
        elif normalized_field == "major":
            record["major"] = value
        elif normalized_field == "essay_career_goals":
            record["essays"]["career_goals"] = value
        elif normalized_field == "essay_challenge_or_mistake":
            record["essays"]["challenge_or_mistake"] = value
        elif normalized_field == "essay_department_specific":
            record["essays"]["department_specific"] = value
        elif normalized_field == "essay_extracurricular_activities":
            record["essays"]["extracurricular_activities"] = value

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

    df = read_xlsx_from_s3(bucket, key)
    logger.info(f"Parsing: {filename} | {len(df)} rows | scholarship: {config['scholarship_type']} | year: {year}")

    records = []
    for _, row in df.iterrows():
        record = normalize_row(row, config, year)
        # Skip rows missing both student_name and availability_id
        if record["student_name"] is None and record["availability_id"] is None:
            continue
        records.append(record)

    logger.info(f"Parsed {len(records)} applications from {filename}")
    return records


def write_to_dynamodb(records: list[dict], source_file: str):
    """Batch write parsed records to DynamoDB."""
    table = get_dynamo_table()
    parsed_at = datetime.now(timezone.utc).isoformat()
    written = 0

    with table.batch_writer() as batch:
        for record in records:
            if not record.get("availability_id"):
                logger.warning(f"Skipping record with no availability_id: {record.get('student_name')}")
                continue

            # DynamoDB doesn't accept None values in nested dicts — strip them
            item = {
                "availability_id": record["availability_id"],
                "source_file": source_file,
                "parsed_at": parsed_at,
            }

            # Add non-None top-level fields
            for field in ("scholarship_type", "rubric_id", "year", "student_name",
                          "gpa", "self_reported_gpa", "academic_program",
                          "academic_level", "major"):
                if record.get(field) is not None:
                    item[field] = record[field]

            # Add essays (only non-None values)
            essays = {k: v for k, v in record.get("essays", {}).items() if v is not None}
            if essays:
                item["essays"] = essays

            batch.put_item(Item=item)
            written += 1

    logger.info(f"Wrote {written} records to {APPLICATIONS_TABLE}")
    return written


def handler(event, context):
    """Lambda entry point — triggered by S3 event."""
    logger.info(f"Event received: {json.dumps(event)}")

    records_written = 0

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

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
            raise  # Let Lambda retry

    return {
        "statusCode": 200,
        "body": json.dumps({"message": f"Processed {records_written} application records"}),
    }
