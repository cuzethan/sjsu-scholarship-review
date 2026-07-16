"""Query sjsu-scores-test and calculate total/avg latency."""
import boto3
from decimal import Decimal

session = boto3.Session(profile_name="Samson", region_name="us-west-2")
dynamo = session.resource("dynamodb")
table = dynamo.Table("sjsu-scores-test")

# Scan for records with latency_s
items = []
kwargs = {}
while True:
    resp = table.scan(**kwargs)
    items.extend(resp.get("Items", []))
    if "LastEvaluatedKey" not in resp:
        break
    kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

scored = [i for i in items if i.get("latency_s")]
total_latency = sum(float(i["latency_s"]) for i in scored)
avg_latency = total_latency / len(scored) if scored else 0

print(f"Total records: {len(items)}")
print(f"Records with LLM scores: {len(scored)}")
print(f"Total latency (sum): {total_latency:.1f}s ({total_latency/60:.1f} min)")
print(f"Avg latency per call: {avg_latency:.2f}s")
print(f"Min latency: {min(float(i['latency_s']) for i in scored):.2f}s" if scored else "")
print(f"Max latency: {max(float(i['latency_s']) for i in scored):.2f}s" if scored else "")
