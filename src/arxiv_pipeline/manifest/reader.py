"""Download and parse the official arXiv PDF manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import BinaryIO
from xml.etree import ElementTree

import boto3
from botocore.client import BaseClient

from arxiv_pipeline.manifest.models import (
    ArchiveWorkItem,
    ArxivArchiveRecord,
)

ARXIV_BUCKET = "arxiv"
ARXIV_PDF_MANIFEST_KEY = "pdf/arXiv_pdf_manifest.xml"
ARXIV_REGION = "us-east-1"


def create_s3_client() -> BaseClient:
    """Create the S3 client used to access the arXiv bucket."""

    return boto3.client("s3", region_name=ARXIV_REGION)


def download_manifest(
    s3_client: BaseClient,
    destination: Path,
) -> Path:
    """Download the official arXiv PDF manifest to a local file."""

    destination.parent.mkdir(parents=True, exist_ok=True)

    response = s3_client.get_object(
        Bucket=ARXIV_BUCKET,
        Key=ARXIV_PDF_MANIFEST_KEY,
        RequestPayer="requester",
    )

    body: BinaryIO = response["Body"]

    with destination.open("wb") as output_file:
        while chunk := body.read(1024 * 1024):
            output_file.write(chunk)

    return destination


def required_text(element: ElementTree.Element, tag: str) -> str:
    """Return required child text or raise a useful error."""

    child = element.find(tag)

    if child is None or child.text is None:
        raise ValueError(f"Manifest record is missing required field: {tag}")

    return child.text.strip()


def parse_manifest(manifest_path: Path) -> list[ArxivArchiveRecord]:
    """Parse all archive records from the downloaded XML manifest."""

    tree = ElementTree.parse(manifest_path)
    root = tree.getroot()

    records: list[ArxivArchiveRecord] = []

    for file_element in root.findall("file"):
        records.append(
            ArxivArchiveRecord(
                filename=required_text(file_element, "filename"),
                yymm=required_text(file_element, "yymm"),
                sequence_number=int(
                    required_text(file_element, "seq_num")
                ),
                number_of_items=int(
                    required_text(file_element, "num_items")
                ),
                size_bytes=int(required_text(file_element, "size")),
                tar_md5=required_text(file_element, "md5sum"),
                content_md5=required_text(
                    file_element,
                    "content_md5sum",
                ),
                first_item=required_text(file_element, "first_item"),
                last_item=required_text(file_element, "last_item"),
                timestamp=required_text(file_element, "timestamp"),
            )
        )

    return records


def month_code(year: int, month: int) -> str:
    """Convert 2026 and 6 into the arXiv month code 2606."""

    if year < 1991:
        raise ValueError("arXiv data does not exist before 1991")

    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")

    return f"{year % 100:02d}{month:02d}"


def select_month(
    records: list[ArxivArchiveRecord],
    year: int,
    month: int,
) -> list[ArxivArchiveRecord]:
    """Return archive records belonging to the requested month."""

    target_yymm = month_code(year, month)

    selected = [
        record
        for record in records
        if record.yymm == target_yymm
    ]

    return sorted(
        selected,
        key=lambda record: record.sequence_number,
    )


def build_work_items(
    records: list[ArxivArchiveRecord],
    year: int,
    month: int,
) -> list[ArchiveWorkItem]:
    """Convert manifest records into processor work items."""

    run_id = f"arxiv-{year:04d}-{month:02d}"

    return [
        ArchiveWorkItem(
            run_id=run_id,
            source_key=record.filename,
            target_year=year,
            target_month=month,
            sequence_number=record.sequence_number,
            number_of_items=record.number_of_items,
            size_bytes=record.size_bytes,
            tar_md5=record.tar_md5,
            first_item=record.first_item,
            last_item=record.last_item,
        )
        for record in records
    ]


def write_jsonl(
    work_items: list[ArchiveWorkItem],
    destination: Path,
) -> Path:
    """Write one archive-processing instruction per JSONL line."""

    destination.parent.mkdir(parents=True, exist_ok=True)

    with destination.open("w", encoding="utf-8") as output_file:
        for work_item in work_items:
            output_file.write(
                json.dumps(work_item.model_dump()) + "\n"
            )

    return destination
