from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os

import boto3


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_table():
    table_name = os.getenv("ARCHIVE_PROCESSING_TABLE")

    if not table_name:
        return None

    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(table_name)


def mark_archive_running(
    *,
    archive_id: str,
    run_id: str,
    source_bucket: str,
    source_key: str,
    source_md5: str | None,
    expected_pdfs: int | None,
    processor_version: str,
) -> None:
    table = _get_table()

    if table is None:
        print(
            "ARCHIVE_PROCESSING_TABLE is not configured; "
            "skipping DynamoDB RUNNING update."
        )
        return

    expression_names = {
        "#status": "status",
    }

    expression_values = {
        ":running": "RUNNING",
        ":run_id": run_id,
        ":source_bucket": source_bucket,
        ":source_key": source_key,
        ":processor_version": processor_version,
        ":started_at": _utc_now(),
        ":zero": 0,
        ":one": 1,
    }

    set_parts = [
        "#status = :running",
        "run_id = :run_id",
        "source_bucket = :source_bucket",
        "source_key = :source_key",
        "processor_version = :processor_version",
        "started_at = :started_at",
        "attempt_count = if_not_exists(attempt_count, :zero) + :one",
    ]

    if source_md5:
        expression_values[":source_md5"] = source_md5
        set_parts.append("source_md5 = :source_md5")

    if expected_pdfs is not None:
        expression_values[":expected_pdfs"] = expected_pdfs
        set_parts.append("expected_pdfs = :expected_pdfs")

    table.update_item(
        Key={"archive_id": archive_id},
        UpdateExpression=(
            "SET "
            + ", ".join(set_parts)
            + " REMOVE completed_at, error_type, error_message"
        ),
        ExpressionAttributeNames=expression_names,
        ExpressionAttributeValues=expression_values,
    )

    print(f"DynamoDB ledger: {archive_id} -> RUNNING")


def mark_archive_complete(
    *,
    archive_id: str,
    discovered_pdfs: int,
    successful_pdfs: int,
    failed_pdfs: int,
    failure_rate: float,
) -> None:
    table = _get_table()

    if table is None:
        return

    table.update_item(
        Key={"archive_id": archive_id},
        UpdateExpression=(
            "SET #status = :complete, "
            "discovered_pdfs = :discovered, "
            "successful_pdfs = :successful, "
            "failed_pdfs = :failed, "
            "failure_rate = :failure_rate, "
            "completed_at = :completed_at"
        ),
        ExpressionAttributeNames={
            "#status": "status",
        },
        ExpressionAttributeValues={
            ":complete": "COMPLETE",
            ":discovered": discovered_pdfs,
            ":successful": successful_pdfs,
            ":failed": failed_pdfs,
            ":failure_rate": Decimal(str(failure_rate)),
            ":completed_at": _utc_now(),
        },
    )

    print(f"DynamoDB ledger: {archive_id} -> COMPLETE")


def mark_archive_failed(
    *,
    archive_id: str,
    error: Exception,
) -> None:
    table = _get_table()

    if table is None:
        return

    table.update_item(
        Key={"archive_id": archive_id},
        UpdateExpression=(
            "SET #status = :failed, "
            "error_type = :error_type, "
            "error_message = :error_message, "
            "completed_at = :completed_at"
        ),
        ExpressionAttributeNames={
            "#status": "status",
        },
        ExpressionAttributeValues={
            ":failed": "FAILED",
            ":error_type": type(error).__name__,
            ":error_message": str(error)[:2000],
            ":completed_at": _utc_now(),
        },
    )

    print(f"DynamoDB ledger: {archive_id} -> FAILED")
