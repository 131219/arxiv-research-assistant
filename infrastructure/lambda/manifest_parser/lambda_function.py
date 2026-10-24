"""AWS Lambda handler for generating an arXiv monthly JSONL work list."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from arxiv_pipeline.manifest.reader import (
    build_work_items,
    download_manifest,
    parse_manifest,
    select_month,
    write_jsonl,
)


s3_client = boto3.client("s3")


def required_integer(event: dict[str, Any], field_name: str) -> int:
    """Read a required integer field from the Step Functions input."""

    value = event.get(field_name)

    if value is None:
        raise ValueError(f"Missing required input field: {field_name}")

    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Input field {field_name} must be an integer"
        ) from error


def resolve_target_month(
    event: dict[str, Any],
    now: datetime | None = None,
) -> tuple[int, int]:
    """Resolve an explicit month or default to the previous UTC month."""

    year_value = event.get("year")
    month_value = event.get("month")

    if year_value is not None or month_value is not None:
        if year_value is None or month_value is None:
            raise ValueError(
                "year and month must either both be provided or both be omitted"
            )

        year = int(year_value)
        month = int(month_value)

        if not 1 <= month <= 12:
            raise ValueError("month must be between 1 and 12")

        return year, month

    now = now or datetime.now(timezone.utc)

    if now.month == 1:
        return now.year - 1, 12

    return now.year, now.month - 1


def lambda_handler(
    event: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    """Generate a monthly arXiv work-list and upload it to S3."""

    print(
        json.dumps(
            {
                "message": "Starting manifest generation",
                "event": event,
            }
        )
    )

    year, month = resolve_target_month(event)

    destination_bucket = (
        event.get("manifest_bucket")
        or os.environ.get("MANIFEST_BUCKET")
    )

    if not destination_bucket:
        raise ValueError(
            "manifest_bucket input or MANIFEST_BUCKET environment variable "
            "is required"
        )

    request_suffix = getattr(context, "aws_request_id", "manual")[:8]

    run_id = event.get("run_id") or (
        f"arxiv-{year:04d}-{month:02d}-{request_suffix}"
    )

    destination_key = event.get(
        "manifest_key",
        f"control/worklists/{run_id}.jsonl",
    )

    temporary_directory = Path("/tmp")
    source_manifest_path = (
        temporary_directory / "arXiv_pdf_manifest.xml"
    )
    work_list_path = temporary_directory / (
        f"arxiv-{year:04d}-{month:02d}.jsonl"
    )

    download_manifest(
        s3_client=s3_client,
        destination=source_manifest_path,
    )

    all_records = parse_manifest(source_manifest_path)

    selected_records = select_month(
        records=all_records,
        year=year,
        month=month,
    )

    skip_completed = event.get("skip_completed", True)

    if skip_completed:
        remaining_records = []

        for record in selected_records:
            archive_name = Path(record.filename).name
            archive_id = Path(archive_name).stem
            success_marker_key = (
                f"status/arxiv/{archive_id}/_SUCCESS.json"
            )

            try:
                s3_client.head_object(
                    Bucket=destination_bucket,
                    Key=success_marker_key,
                )
                print(
                    json.dumps(
                        {
                            "message": "Skipping completed archive",
                            "archive_id": archive_id,
                        }
                    )
                )
            except ClientError as error:
                error_code = error.response["Error"]["Code"]

                if error_code in {"404", "NoSuchKey", "NotFound"}:
                    remaining_records.append(record)
                else:
                    raise

        selected_records = remaining_records

    archive_limit_value = event.get("archive_limit")

    if archive_limit_value is not None:
        try:
            archive_limit = int(archive_limit_value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "archive_limit must be an integer"
            ) from error

        if archive_limit < 1:
            raise ValueError(
                "archive_limit must be at least 1"
            )

        selected_records = selected_records[:archive_limit]

    if not selected_records:
        raise ValueError(
            f"No arXiv archives found for {year:04d}-{month:02d}"
        )

    work_items = build_work_items(
        records=selected_records,
        year=year,
        month=month,
    )

    # Step Functions may provide a custom run ID.
    for work_item in work_items:
        work_item.run_id = run_id

    write_jsonl(
        work_items=work_items,
        destination=work_list_path,
    )

    s3_client.upload_file(
        str(work_list_path),
        destination_bucket,
        destination_key,
        ExtraArgs={
            "ContentType": "application/x-ndjson",
        },
    )

    expected_pdfs = sum(
        item.number_of_items for item in work_items
    )

    total_archive_bytes = sum(
        item.size_bytes for item in work_items
    )

    result = {
        "run_id": run_id,
        "year": year,
        "month": month,
        "manifest_bucket": destination_bucket,
        "manifest_key": destination_key,
        "archive_count": len(work_items),
        "expected_pdf_count": expected_pdfs,
        "total_archive_bytes": total_archive_bytes,
    }

    print(
        json.dumps(
            {
                "message": "Manifest generation completed",
                **result,
            }
        )
    )

    return result
