import json
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError


s3_client = boto3.client("s3")


def read_json_object(bucket: str, key: str) -> dict[str, Any]:
    response = s3_client.get_object(
        Bucket=bucket,
        Key=key,
    )

    return json.loads(
        response["Body"].read().decode("utf-8")
    )


def read_work_list(bucket: str, key: str) -> list[dict[str, Any]]:
    response = s3_client.get_object(
        Bucket=bucket,
        Key=key,
    )

    content = response["Body"].read().decode("utf-8")

    return [
        json.loads(line)
        for line in content.splitlines()
        if line.strip()
    ]


def archive_id_from_source_key(source_key: str) -> str:
    return Path(source_key).stem


def validate_archive(
    bucket: str,
    work_item: dict[str, Any],
) -> dict[str, Any]:
    archive_id = archive_id_from_source_key(
        work_item["source_key"]
    )

    marker_key = (
        f"status/arxiv/{archive_id}/_SUCCESS.json"
    )

    expected_count = int(
        work_item["number_of_items"]
    )

    errors: list[str] = []

    try:
        marker = read_json_object(
            bucket=bucket,
            key=marker_key,
        )
    except ClientError as error:
        error_code = error.response["Error"]["Code"]

        if error_code in {
            "NoSuchKey",
            "404",
            "NotFound",
            "AccessDenied",
            "403",
        }:
            return {
                "archive_id": archive_id,
                "source_key": work_item["source_key"],
                "valid": False,
                "errors": [
                    f"Success marker unavailable: {marker_key}"
                ],
            }

        raise

    marker_expected_count = int(
        marker.get("expected_item_count", -1)
    )
    discovered_count = int(
        marker.get("discovered_pdf_count", -1)
    )
    successful_count = int(
        marker.get("successful_count", -1)
    )
    failed_count = int(
        marker.get("failed_count", -1)
    )
    markdown_count = int(
        marker.get("markdown_object_count", -1)
    )
    metadata_count = int(
        marker.get("metadata_object_count", -1)
    )
    failure_rate = float(
        marker.get("failure_rate", 1.0)
    )
    maximum_failure_rate = float(
        marker.get("maximum_failure_rate", 0.0)
    )
    output_validation_passed = bool(
        marker.get("output_validation_passed", False)
    )

    if marker_expected_count != expected_count:
        errors.append(
            "Manifest expected count does not match "
            "success marker expected count"
        )

    if discovered_count != expected_count:
        errors.append(
            "Discovered PDF count does not match "
            "expected count"
        )

    if successful_count + failed_count != discovered_count:
        errors.append(
            "Successful plus failed count does not "
            "match discovered count"
        )

    if markdown_count != successful_count:
        errors.append(
            "Markdown object count does not match "
            "successful paper count"
        )

    if metadata_count != successful_count:
        errors.append(
            "Metadata object count does not match "
            "successful paper count"
        )

    if markdown_count != metadata_count:
        errors.append(
            "Markdown and metadata object counts differ"
        )

    if failure_rate > maximum_failure_rate:
        errors.append(
            "Archive failure rate exceeds the "
            "maximum allowed rate"
        )

    if not output_validation_passed:
        errors.append(
            "Worker output validation did not pass"
        )

    return {
        "archive_id": archive_id,
        "source_key": work_item["source_key"],
        "marker_key": marker_key,
        "expected_count": expected_count,
        "discovered_count": discovered_count,
        "successful_count": successful_count,
        "failed_count": failed_count,
        "markdown_count": markdown_count,
        "metadata_count": metadata_count,
        "failure_rate": failure_rate,
        "maximum_failure_rate": maximum_failure_rate,
        "valid": not errors,
        "errors": errors,
    }


def lambda_handler(
    event: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    print(
        json.dumps(
            {
                "message": "Validation started",
                "event": event,
            }
        )
    )

    run_id = event["run_id"]
    manifest_bucket = event["manifest_bucket"]
    manifest_key = event["manifest_key"]

    output_bucket = event.get(
        "output_bucket",
        os.environ.get("OUTPUT_BUCKET"),
    )

    if not output_bucket:
        raise ValueError(
            "output_bucket was not provided"
        )

    work_items = read_work_list(
        bucket=manifest_bucket,
        key=manifest_key,
    )

    archive_results = [
        validate_archive(
            bucket=output_bucket,
            work_item=work_item,
        )
        for work_item in work_items
    ]

    valid_archives = [
        result
        for result in archive_results
        if result["valid"]
    ]

    invalid_archives = [
        result
        for result in archive_results
        if not result["valid"]
    ]

    expected_pdf_count = sum(
        int(item["number_of_items"])
        for item in work_items
    )

    successful_pdf_count = sum(
        int(result.get("successful_count", 0))
        for result in archive_results
    )

    failed_pdf_count = sum(
        int(result.get("failed_count", 0))
        for result in archive_results
    )

    validation_passed = not invalid_archives

    report = {
        "run_id": run_id,
        "manifest_bucket": manifest_bucket,
        "manifest_key": manifest_key,
        "output_bucket": output_bucket,
        "expected_archive_count": len(work_items),
        "valid_archive_count": len(valid_archives),
        "invalid_archive_count": len(invalid_archives),
        "expected_pdf_count": expected_pdf_count,
        "successful_pdf_count": successful_pdf_count,
        "failed_pdf_count": failed_pdf_count,
        "validation_passed": validation_passed,
        "archives": archive_results,
    }

    report_key = (
        f"reports/{run_id}/validation-report.json"
    )

    s3_client.put_object(
        Bucket=output_bucket,
        Key=report_key,
        Body=(
            json.dumps(
                report,
                indent=2,
            )
            + "\n"
        ).encode("utf-8"),
        ContentType="application/json",
    )

    result = {
        "run_id": run_id,
        "validation_passed": validation_passed,
        "expected_archive_count": len(work_items),
        "valid_archive_count": len(valid_archives),
        "invalid_archive_count": len(invalid_archives),
        "expected_pdf_count": expected_pdf_count,
        "successful_pdf_count": successful_pdf_count,
        "failed_pdf_count": failed_pdf_count,
        "report_bucket": output_bucket,
        "report_key": report_key,
    }

    print(
        json.dumps(
            {
                "message": "Validation completed",
                **result,
            }
        )
    )

    return result
