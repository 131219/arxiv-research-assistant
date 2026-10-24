"""Command-line entry point for processing one arXiv TAR archive."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from arxiv_pipeline.processor.worker import process_archive
from arxiv_pipeline.processor.ledger import mark_archive_failed


def parse_bool(value: str) -> bool:
    """Parse true/false command-line values."""
    normalized = value.strip().lower()

    if normalized == "true":
        return True

    if normalized == "false":
        return False

    raise argparse.ArgumentTypeError(
        "Expected true or false."
    )


def read_work_item(
    manifest_path: Path,
    line_number: int,
) -> dict[str, Any]:
    """Read one JSON object from a JSONL work list."""

    if line_number < 1:
        raise ValueError("line_number must be at least 1")

    with manifest_path.open("r", encoding="utf-8") as manifest_file:
        for current_line_number, line in enumerate(
            manifest_file,
            start=1,
        ):
            if current_line_number == line_number:
                return json.loads(line)

    raise ValueError(
        f"Line {line_number} not found in {manifest_path}"
    )


def parse_arguments() -> argparse.Namespace:
    """Parse Batch-container command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Process one arXiv TAR archive."
    )

    # Production mode: Step Functions passes the work item directly.
    parser.add_argument("--source-bucket")
    parser.add_argument("--source-key")
    parser.add_argument("--request-payer", default="requester")
    parser.add_argument("--run-id")
    parser.add_argument("--target-year", type=int)
    parser.add_argument("--target-month", type=int)
    parser.add_argument("--expected-item-count", type=int)
    parser.add_argument("--tar-md5")
    parser.add_argument(
        "--skip-completed",
        type=parse_bool,
        default=True,
    )

    # Legacy/local mode: read one line from a local JSONL file.
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--line-number",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--output-bucket",
        default=os.getenv("OUTPUT_BUCKET"),
        help=(
            "Destination S3 bucket. Can also be supplied through "
            "the OUTPUT_BUCKET environment variable."
        ),
    )

    return parser.parse_args()


def build_work_item(args: argparse.Namespace) -> dict[str, Any]:
    """Build a work item from direct arguments or a local manifest."""

    if args.source_key:
        required_direct_arguments = {
            "source_bucket": args.source_bucket,
            "run_id": args.run_id,
            "target_year": args.target_year,
            "target_month": args.target_month,
        }

        missing_fields = [
            field_name
            for field_name, value in required_direct_arguments.items()
            if value is None
        ]

        if missing_fields:
            raise ValueError(
                "Missing required direct-processing arguments: "
                + ", ".join(missing_fields)
            )

        return {
            "source_bucket": args.source_bucket,
            "source_key": args.source_key,
            "request_payer": args.request_payer,
            "run_id": args.run_id,
            "target_year": args.target_year,
            "target_month": args.target_month,
            "number_of_items": args.expected_item_count,
            "tar_md5": args.tar_md5,
            "skip_completed": args.skip_completed,
        }

    if args.manifest is not None and args.line_number is not None:
        return read_work_item(
            manifest_path=args.manifest,
            line_number=args.line_number,
        )

    raise ValueError(
        "Provide either direct archive arguments beginning with "
        "--source-key, or provide both --manifest and --line-number."
    )


def main() -> None:
    """Process exactly one archive."""

    args = parse_arguments()

    if not args.output_bucket:
        raise ValueError(
            "Output bucket is required. Provide --output-bucket or "
            "set the OUTPUT_BUCKET environment variable."
        )

    work_item = build_work_item(args)

    print("Selected work item:")
    print(json.dumps(work_item, indent=2))

    archive_id = Path(work_item["source_key"]).stem

    try:
        process_archive(
            source_bucket=work_item["source_bucket"],
            source_key=work_item["source_key"],
            output_bucket=args.output_bucket,
            run_id=work_item["run_id"],
            target_year=work_item["target_year"],
            target_month=work_item["target_month"],
            expected_item_count=work_item.get("number_of_items"),
            tar_md5=work_item.get("tar_md5"),
            request_payer=work_item.get(
                "request_payer",
                "requester",
            ),
            skip_completed=work_item.get(
                "skip_completed",
                args.skip_completed,
            ),
        )
    except Exception as error:
        try:
            mark_archive_failed(
                archive_id=archive_id,
                error=error,
            )
        except Exception as ledger_error:
            print(
                "Failed to write FAILED state to DynamoDB: "
                f"{type(ledger_error).__name__}: {ledger_error}"
            )

        raise


if __name__ == "__main__":
    main()
