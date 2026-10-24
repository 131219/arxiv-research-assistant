"""Command-line interface for generating an arXiv monthly work list."""

from __future__ import annotations

import argparse
from pathlib import Path

from arxiv_pipeline.manifest.reader import (
    build_work_items,
    create_s3_client,
    download_manifest,
    parse_manifest,
    select_month,
    write_jsonl,
)


def parse_arguments() -> argparse.Namespace:
    """Read command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Generate an arXiv PDF archive work list."
    )

    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="Four-digit year, for example 2026.",
    )

    parser.add_argument(
        "--month",
        type=int,
        required=True,
        help="Month number from 1 to 12.",
    )

    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=Path("data/manifests/arXiv_pdf_manifest.xml"),
        help="Location where the downloaded manifest will be stored.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSONL output path.",
    )

    return parser.parse_args()


def main() -> None:
    """Generate the work list for the requested month."""

    arguments = parse_arguments()

    output_path = arguments.output or Path(
        f"data/worklists/arxiv-{arguments.year:04d}-"
        f"{arguments.month:02d}.jsonl"
    )

    print("Downloading official arXiv PDF manifest...")

    s3_client = create_s3_client()
    download_manifest(s3_client, arguments.manifest_path)

    print(f"Manifest saved to: {arguments.manifest_path}")

    all_records = parse_manifest(arguments.manifest_path)

    selected_records = select_month(
        all_records,
        arguments.year,
        arguments.month,
    )

    if not selected_records:
        raise SystemExit(
            f"No archive records found for "
            f"{arguments.year:04d}-{arguments.month:02d}. "
            "The month may not yet be available in the bulk manifest."
        )

    work_items = build_work_items(
        selected_records,
        arguments.year,
        arguments.month,
    )

    write_jsonl(work_items, output_path)

    expected_papers = sum(
        item.number_of_items for item in work_items
    )

    expected_bytes = sum(
        item.size_bytes for item in work_items
    )

    print()
    print("Work list generated successfully")
    print(f"Target month: {arguments.year:04d}-{arguments.month:02d}")
    print(f"Archive count: {len(work_items)}")
    print(f"Expected PDFs: {expected_papers}")
    print(f"Total archive bytes: {expected_bytes}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
