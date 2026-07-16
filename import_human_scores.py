"""Import human scores from xlsx to sjsu-scores DynamoDB table.
Maps Candidate (last 12 hex of UUID) -> application_key (Student UUID).
Only updates records that are MISSING human_weighted_total."""
import re
import json
import pandas as pd
import boto3
from decimal import Decimal

scores_path = r"C:\Users\sfkim\OneDrive\Desktop\dxHub\recsuaisummercampdatarequestandphoneanexpert\SJSU General Scholarships 26-27 scores.xlsx"
apps_path = r"C:\Users\sfkim\OneDrive\Desktop\dxHub\data\SJSU General Scholarship 26-27 ad hoc report.xlsx"

AWS_PROFILE = "Samson"
AWS_REGION = "us-west-2"
SCORES_TABLE = "sjsu-scores-test"

# Load data
df_scores = pd.read_excel(scores_path)
df_apps = pd.read_excel(apps_path)

# Build mapping: Candidate -> Student UUID (application_key)
df_apps["student_tail"] = df_apps["Student"].apply(lambda x: str(x).replace("-", "")[-12:].upper())
df_scores["Candidate"] = df_scores["Candidate"].astype(str).str.upper()

merged = df_scores.merge(
    df_apps[["Student", "student_tail"]],
    left_on="Candidate",
    right_on="student_tail",
    how="left"
)
merged = merged[merged["Student"].notna()]  # drop unmatched

print(f"Matched records to import: {len(merged)}")


def extract_avg_score(text):
    """Extract average score from 'Average score: X.XX\\n...' text."""
    if pd.isna(text):
        return None
    match = re.search(r"Average score:\s*([\d.]+)", str(text))
    return float(match.group(1)) if match else None


# Connect to DynamoDB
session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
dynamo = session.resource("dynamodb")
table = dynamo.Table(SCORES_TABLE)

# Import human scores
updated = 0
skipped = 0
errors = 0

for _, row in merged.iterrows():
    app_key = row["Student"]
    
    # Extract criterion scores
    career = extract_avg_score(row.get("Chair: 1) Essay Response: SJSU Journey"))
    challenge = extract_avg_score(row.get("Chair: 2) Essay Response: Personal Challenge"))
    xc = extract_avg_score(row.get("Chair: 3) Extracurricular Activities"))
    initiative = extract_avg_score(row.get("Chair: 4) Initiative & Self-Motivation"))
    creativity = extract_avg_score(row.get("Chair: 5) Creativity"))
    weighted = row.get("Weighted Points")
    soft_match = row.get("Soft Match")

    if pd.isna(weighted):
        skipped += 1
        continue

    human_criterion_scores = []
    if career is not None:
        human_criterion_scores.append({"criterion": "Career Goals Essay", "score": Decimal(str(career))})
    if challenge is not None:
        human_criterion_scores.append({"criterion": "Challenge Essay", "score": Decimal(str(challenge))})
    if xc is not None:
        human_criterion_scores.append({"criterion": "Extracurricular Activities", "score": Decimal(str(xc))})
    if initiative is not None:
        human_criterion_scores.append({"criterion": "Initiative & Self-Motivation", "score": Decimal(str(initiative))})
    if creativity is not None:
        human_criterion_scores.append({"criterion": "Creativity", "score": Decimal(str(creativity))})

    try:
        update_expr = "SET human_weighted_total = :hwt, human_criterion_scores = :hcs"
        expr_values = {
            ":hwt": Decimal(str(int(weighted))),
            ":hcs": human_criterion_scores,
        }
        if not pd.isna(soft_match):
            update_expr += ", soft_match_pct = :sm"
            expr_values[":sm"] = Decimal(str(soft_match))

        table.update_item(
            Key={"application_key": app_key},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
        )
        updated += 1
        if updated % 100 == 0:
            print(f"  Updated {updated}...")
    except Exception as e:
        errors += 1
        if errors <= 5:
            print(f"  Error on {app_key}: {e}")

print(f"\nDone. Updated: {updated}, Skipped (no weighted): {skipped}, Errors: {errors}")
