from unittest.mock import MagicMock, patch

from arxiv_pipeline.processor.ledger import (
    mark_archive_complete,
    mark_archive_failed,
    mark_archive_running,
)


@patch("arxiv_pipeline.processor.ledger._get_table")
def test_mark_archive_running_increments_attempt_count(mock_get_table):
    table = MagicMock()
    mock_get_table.return_value = table

    mark_archive_running(
        archive_id="arXiv_pdf_2606_017",
        run_id="test-run",
        source_bucket="arxiv",
        source_key="pdf/arXiv_pdf_2606_017.tar",
        source_md5="abc123",
        expected_pdfs=121,
        processor_version="direct-workitem-v2",
    )

    table.update_item.assert_called_once()

    request = table.update_item.call_args.kwargs

    assert request["Key"] == {
        "archive_id": "arXiv_pdf_2606_017"
    }

    assert (
        "attempt_count = if_not_exists(attempt_count, :zero) + :one"
        in request["UpdateExpression"]
    )

    assert request["ExpressionAttributeValues"][":running"] == (
        "RUNNING"
    )


@patch("arxiv_pipeline.processor.ledger._get_table")
def test_mark_archive_complete_records_counts(mock_get_table):
    table = MagicMock()
    mock_get_table.return_value = table

    mark_archive_complete(
        archive_id="arXiv_pdf_2606_017",
        discovered_pdfs=121,
        successful_pdfs=121,
        failed_pdfs=0,
        failure_rate=0.0,
    )

    request = table.update_item.call_args.kwargs

    assert request["ExpressionAttributeValues"][":complete"] == (
        "COMPLETE"
    )
    assert request["ExpressionAttributeValues"][":successful"] == 121
    assert request["ExpressionAttributeValues"][":failed"] == 0


@patch("arxiv_pipeline.processor.ledger._get_table")
def test_mark_archive_failed_records_error(mock_get_table):
    table = MagicMock()
    mock_get_table.return_value = table

    error = RuntimeError("processing failed")

    mark_archive_failed(
        archive_id="arXiv_pdf_2606_017",
        error=error,
    )

    request = table.update_item.call_args.kwargs

    assert request["ExpressionAttributeValues"][":failed"] == (
        "FAILED"
    )
    assert request["ExpressionAttributeValues"][":error_type"] == (
        "RuntimeError"
    )
    assert request["ExpressionAttributeValues"][":error_message"] == (
        "processing failed"
    )
