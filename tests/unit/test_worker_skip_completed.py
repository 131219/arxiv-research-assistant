from unittest.mock import patch

import pytest

from arxiv_pipeline.processor.worker import process_archive


COMMON_ARGS = {
    "source_bucket": "arxiv",
    "source_key": "pdf/arXiv_pdf_2606_001.tar",
    "output_bucket": "test-output-bucket",
    "run_id": "test-run",
    "target_year": 2026,
    "target_month": 6,
    "expected_item_count": 100,
    "tar_md5": "abc123",
}


@patch("arxiv_pipeline.processor.worker.create_s3_client")
@patch("arxiv_pipeline.processor.worker.mark_archive_running")
@patch("arxiv_pipeline.processor.worker.s3_object_exists")
def test_existing_success_marker_is_skipped_when_enabled(
    mock_exists,
    mock_mark_running,
    mock_create_s3_client,
):
    mock_exists.return_value = True

    process_archive(
        **COMMON_ARGS,
        skip_completed=True,
    )

    mock_exists.assert_called_once()
    mock_mark_running.assert_not_called()


@patch("arxiv_pipeline.processor.worker.create_s3_client")
@patch("arxiv_pipeline.processor.worker.mark_archive_running")
@patch("arxiv_pipeline.processor.worker.s3_object_exists")
def test_existing_success_marker_does_not_block_forced_reprocess(
    mock_exists,
    mock_mark_running,
    mock_create_s3_client,
):
    mock_mark_running.side_effect = RuntimeError(
        "processing continued"
    )

    with pytest.raises(
        RuntimeError,
        match="processing continued",
    ):
        process_archive(
            **COMMON_ARGS,
            skip_completed=False,
        )

    mock_exists.assert_not_called()
    mock_mark_running.assert_called_once()
