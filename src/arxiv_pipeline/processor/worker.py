from datetime import datetime, timezone
from pathlib import Path

from arxiv_pipeline.processor.downloader import (
    create_s3_client,
    download_archive,
)
from arxiv_pipeline.processor.extractor import extract_archive
from arxiv_pipeline.processor.markdown_writer import save_markdown
from arxiv_pipeline.processor.ledger import (
    mark_archive_complete,
    mark_archive_running,
)
from arxiv_pipeline.processor.pdf_parser import extract_pdf_text
from arxiv_pipeline.processor.uploader import (
    s3_object_exists,
    upload_json,
    upload_json_lines,
    upload_markdown,
)

def count_s3_objects_with_suffix(
    s3_client,
    bucket: str,
    prefix: str,
    suffix: str,
) -> int:
    """
    Count S3 objects under a prefix whose keys end with a suffix.
    """
    paginator = s3_client.get_paginator("list_objects_v2")

    count = 0

    for page in paginator.paginate(
        Bucket=bucket,
        Prefix=prefix,
    ):
        for item in page.get("Contents", []):
            key = item["Key"]

            if key.endswith(suffix):
                count += 1

    return count

def process_archive(
    source_bucket: str,
    source_key: str,
    output_bucket: str,
    run_id: str,
    target_year: int,
    target_month: int,
    expected_item_count: int | None = None,
    tar_md5: str | None = None,
    request_payer: str = "requester",
    maximum_failure_rate: float = 0.05,
    skip_completed: bool = True,
) -> None:
    """
    Download one TAR archive, process every PDF, upload Markdown and
    Bedrock metadata sidecars, and write archive completion markers.
    """

    archive_name = Path(source_key).name
    archive_id = Path(archive_name).stem

    archive_path = Path("data/archives") / archive_name
    extraction_directory = Path("data/extracted") / archive_id
    markdown_directory = Path("data/markdown") / archive_id

    s3_client = create_s3_client()

    success_marker_key = (
        f"status/arxiv/{archive_id}/_SUCCESS.json"
    )

    if skip_completed and s3_object_exists(
        s3_client=s3_client,
        bucket=output_bucket,
        key=success_marker_key,
    ):
        print(
            f"Archive {archive_id} already has a success marker."
        )
        print(
            "Skipping archive to prevent duplicate processing."
        )
        return

    processor_version = __import__("os").getenv(
        "PROCESSOR_VERSION",
        "unknown",
    )

    mark_archive_running(
        archive_id=archive_id,
        run_id=run_id,
        source_bucket=source_bucket,
        source_key=source_key,
        source_md5=tar_md5,
        expected_pdfs=expected_item_count,
        processor_version=processor_version,
    )

    download_archive(
        s3_client=s3_client,
        source_bucket=source_bucket,
        source_key=source_key,
        destination_path=archive_path,
        request_payer=request_payer,
    )

    extract_archive(
        archive_path=archive_path,
        destination_directory=extraction_directory,
    )

    pdf_files = sorted(extraction_directory.rglob("*.pdf"))

    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found inside {extraction_directory}")

    print(f"Found {len(pdf_files)} PDF files " f"inside archive {archive_id}")

    if expected_item_count is not None and len(pdf_files) != expected_item_count:
        print(
            "Warning: extracted PDF count does not match manifest. "
            f"expected={expected_item_count}, "
            f"actual={len(pdf_files)}"
        )

    successful_count = 0
    failed_items: list[dict[str, str]] = []

    started_at = datetime.now(timezone.utc)
    for pdf_file in pdf_files:
        paper_id = pdf_file.stem

        try:
            print(f"Processing PDF: {pdf_file}")

            extracted_text = extract_pdf_text(pdf_file)

            markdown_path = markdown_directory / f"{paper_id}.md"

            saved_markdown_path = save_markdown(
                text=extracted_text,
                output_path=markdown_path,
                title=paper_id,
            )

            markdown_key = f"processed/{archive_id}/" f"{saved_markdown_path.name}"

            upload_markdown(
                s3_client=s3_client,
                local_path=saved_markdown_path,
                destination_bucket=output_bucket,
                destination_key=markdown_key,
            )

            metadata = {
                "metadataAttributes": {
                    "paper_id": paper_id,
                    "archive_id": archive_id,
                    "source_bucket": source_bucket,
                    "source_key": source_key,
                    "target_year": target_year,
                    "target_month": target_month,
                    "run_id": run_id,
                    "document_type": "arxiv_paper",
                }
            }

            metadata_key = f"{markdown_key}.metadata.json"

            upload_json(
                s3_client=s3_client,
                data=metadata,
                destination_bucket=output_bucket,
                destination_key=metadata_key,
            )

            successful_count += 1

            print(f"Successfully processed: {paper_id}")

        except Exception as error:
            failed_item = {
                "paper_id": paper_id,
                "pdf_path": str(pdf_file),
                "error_type": type(error).__name__,
                "error_message": str(error),
            }

            failed_items.append(failed_item)

            print(f"Failed to process {paper_id}: " f"{type(error).__name__}: {error}")

    finished_at = datetime.now(timezone.utc)

    total_count = len(pdf_files)
    failed_count = len(failed_items)
    failure_rate = failed_count / total_count if total_count > 0 else 1.0

    print(
        "Archive processing summary: "
        f"archive={archive_id}, "
        f"total={total_count}, "
        f"successful={successful_count}, "
        f"failed={failed_count}, "
        f"failure_rate={failure_rate:.4f}"
    )

    if failed_items:
        failure_report_key = f"reports/{run_id}/{archive_id}/" f"failed-items.jsonl"

        upload_json_lines(
            s3_client=s3_client,
            records=failed_items,
            destination_bucket=output_bucket,
            destination_key=failure_report_key,
        )

    summary = {
        "run_id": run_id,
        "archive_id": archive_id,
        "source_bucket": source_bucket,
        "source_key": source_key,
        "target_year": target_year,
        "target_month": target_month,
        "expected_item_count": expected_item_count,
        "discovered_pdf_count": total_count,
        "successful_count": successful_count,
        "failed_count": failed_count,
        "failure_rate": failure_rate,
        "maximum_failure_rate": maximum_failure_rate,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }

    processed_prefix = f"processed/{archive_id}/"

    markdown_object_count = count_s3_objects_with_suffix(
        s3_client=s3_client,
        bucket=output_bucket,
        prefix=processed_prefix,
        suffix=".md",
    )

    metadata_object_count = count_s3_objects_with_suffix(
        s3_client=s3_client,
        bucket=output_bucket,
        prefix=processed_prefix,
        suffix=".md.metadata.json",
    )

    summary["markdown_object_count"] = markdown_object_count
    summary["metadata_object_count"] = metadata_object_count

    print(
        "S3 output validation: "
        f"markdown={markdown_object_count}, "
        f"metadata={metadata_object_count}, "
        f"expected={successful_count}"
    )

    output_validation_passed = (
        markdown_object_count == successful_count
        and metadata_object_count == successful_count
    )

    summary["output_validation_passed"] = (
        output_validation_passed
    )

    if not output_validation_passed:
        failure_marker_key = (
            f"status/arxiv/{archive_id}/_FAILURE.json"
        )

        upload_json(
            s3_client=s3_client,
            data=summary,
            destination_bucket=output_bucket,
            destination_key=failure_marker_key,
        )

        raise RuntimeError(
            f"S3 output validation failed for {archive_id}. "
            f"successful={successful_count}, "
            f"markdown={markdown_object_count}, "
            f"metadata={metadata_object_count}"
        )

    if failure_rate > maximum_failure_rate:
        failure_marker_key = (
            f"status/arxiv/{archive_id}/_FAILURE.json"
        )

        upload_json(
            s3_client=s3_client,
            data=summary,
            destination_bucket=output_bucket,
            destination_key=failure_marker_key,
        )

        raise RuntimeError(
            f"Archive {archive_id} exceeded the allowed failure rate. "
            f"failure_rate={failure_rate:.4f}, "
            f"maximum={maximum_failure_rate:.4f}"
        )

    upload_json(
        s3_client=s3_client,
        data=summary,
        destination_bucket=output_bucket,
        destination_key=success_marker_key,
    )

    mark_archive_complete(
        archive_id=archive_id,
        discovered_pdfs=total_count,
        successful_pdfs=successful_count,
        failed_pdfs=failed_count,
        failure_rate=failure_rate,
    )

    print("Worker finished successfully.")
