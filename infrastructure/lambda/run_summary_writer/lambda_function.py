import json
import boto3


s3 = boto3.client("s3")


def lambda_handler(event, context):
    bucket = event["output_bucket"]
    run_id = event["run_id"]
    summary = event["run_summary"]

    key = f"runs/{run_id}/summary.json"

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(summary, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    return {
        "bucket": bucket,
        "key": key,
        "status": "WRITTEN",
    }
