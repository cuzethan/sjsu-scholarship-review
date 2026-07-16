"""Test: score 100 applications by invoking the Lambda directly."""
import json
import time
import boto3
from boto3.dynamodb.conditions import Attr
from boto3.dynamodb.types import TypeSerializer

session = boto3.Session(profile_name="Samson", region_name="us-west-2")
dynamo = session.resource("dynamodb")
lambda_client = session.client("lambda")
table = dynamo.Table("sjsu-applications")

# Get 100 SJSU General apps
print("Scanning for 100 sjsu_general applications...")
resp = table.scan(
    FilterExpression=Attr("scholarship_scope").eq("sjsu_general"),
    Limit=100,
)
items = [i for i in resp["Items"] if i.get("qa_pairs")][:100]
print(f"Got {len(items)} applications to score.\n")

# Convert each to a stream event and invoke Lambda
serializer = TypeSerializer()
scored = 0
failed = 0
total_latency = 0
start = time.time()

for i, app in enumerate(items, 1):
    new_image = {k: serializer.serialize(v) for k, v in app.items()}
    test_event = {
        "Records": [{
            "eventName": "INSERT",
            "dynamodb": {"NewImage": new_image},
        }]
    }

    resp = lambda_client.invoke(
        FunctionName="sjsu-score-applications",
        InvocationType="RequestResponse",
        Payload=json.dumps(test_event),
    )
    payload = json.loads(resp["Payload"].read())
    body = json.loads(payload.get("body", "{}"))

    if body.get("scored", 0) > 0:
        scored += 1
    else:
        failed += 1

    if i % 10 == 0:
        elapsed = time.time() - start
        print(f"  [{i}/100] scored={scored} failed={failed} elapsed={elapsed:.1f}s")

elapsed = time.time() - start
print(f"\nDone. Scored: {scored}, Failed: {failed}")
print(f"Wall clock: {elapsed:.1f}s ({elapsed/len(items):.2f}s per app)")
