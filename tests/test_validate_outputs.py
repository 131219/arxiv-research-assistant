import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "infrastructure"
    / "lambda"
    / "validate_outputs"
    / "lambda_function.py"
)

spec = importlib.util.spec_from_file_location(
    "validate_outputs_lambda",
    MODULE_PATH,
)

validate_outputs = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(validate_outputs)


def make_client_error(
    code: str,
    operation: str = "GetObject",
) -> ClientError:
    return ClientError(
        {
            "Error": {
                "Code": code,
                "Message": "Test error",
            }
        },
        operation,
    )


def test_archive_id_from_source_key() -> None:
    result = validate_outputs.archive_id_from_source_key(
        "pdf/arXiv_pdf_2606_004.tar"
    )

    assert result == "arXiv_pdf_2606_004"


def test_validate_archive_passes_for_valid_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = {
        "expected_item_count": 133,
        "discovered_pdf_count": 133,
        "successful_count": 133,
        "failed_count": 0,
        "failure_rate": 0.0,
        "maximum_failure_rate": 0.05,
        "markdown_object_count": 133,
        "metadata_object_count": 133,
        "output_validation_passed": True,
    }

    monkeypatch.setattr(
        validate_outputs,
        "read_json_object",
        lambda bucket, key: marker,
    )

    work_item = {
        "source_key": "pdf/arXiv_pdf_2606_004.tar",
        "number_of_items": 133,
    }

    result = validate_outputs.validate_archive(
        bucket="test-bucket",
        work_item=work_item,
    )

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["successful_count"] == 133
    assert result["markdown_count"] == 133
    assert result["metadata_count"] == 133


def test_validate_archive_fails_when_counts_differ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = {
        "expected_item_count": 133,
        "discovered_pdf_count": 133,
        "successful_count": 132,
        "failed_count": 1,
        "failure_rate": 1 / 133,
        "maximum_failure_rate": 0.05,
        "markdown_object_count": 132,
        "metadata_object_count": 131,
        "output_validation_passed": False,
    }

    monkeypatch.setattr(
        validate_outputs,
        "read_json_object",
        lambda bucket, key: marker,
    )

    work_item = {
        "source_key": "pdf/arXiv_pdf_2606_004.tar",
        "number_of_items": 133,
    }

    result = validate_outputs.validate_archive(
        bucket="test-bucket",
        work_item=work_item,
    )

    assert result["valid"] is False
    assert (
        "Metadata object count does not match successful paper count"
        in result["errors"]
    )
    assert (
        "Markdown and metadata object counts differ"
        in result["errors"]
    )
    assert (
        "Worker output validation did not pass"
        in result["errors"]
    )


def test_validate_archive_fails_when_marker_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_missing_marker(
        bucket: str,
        key: str,
    ) -> dict:
        raise make_client_error("NoSuchKey")

    monkeypatch.setattr(
        validate_outputs,
        "read_json_object",
        raise_missing_marker,
    )

    work_item = {
        "source_key": "pdf/arXiv_pdf_2606_004.tar",
        "number_of_items": 133,
    }

    result = validate_outputs.validate_archive(
        bucket="test-bucket",
        work_item=work_item,
    )

    assert result["valid"] is False
    assert "Success marker unavailable" in result["errors"][0]


def test_lambda_handler_writes_validation_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_items = [
        {
            "source_key": "pdf/arXiv_pdf_2606_004.tar",
            "number_of_items": 133,
        },
        {
            "source_key": "pdf/arXiv_pdf_2606_005.tar",
            "number_of_items": 152,
        },
    ]

    archive_results = [
        {
            "archive_id": "arXiv_pdf_2606_004",
            "valid": True,
            "successful_count": 133,
            "failed_count": 0,
        },
        {
            "archive_id": "arXiv_pdf_2606_005",
            "valid": True,
            "successful_count": 152,
            "failed_count": 0,
        },
    ]

    monkeypatch.setattr(
        validate_outputs,
        "read_work_list",
        lambda bucket, key: work_items,
    )

    monkeypatch.setattr(
        validate_outputs,
        "validate_archive",
        lambda bucket, work_item: archive_results.pop(0),
    )

    mock_s3 = MagicMock()

    monkeypatch.setattr(
        validate_outputs,
        "s3_client",
        mock_s3,
    )

    event = {
        "run_id": "wave1-test",
        "manifest_bucket": "manifest-bucket",
        "manifest_key": "control/worklists/wave1-test.jsonl",
        "output_bucket": "output-bucket",
    }

    result = validate_outputs.lambda_handler(
        event=event,
        context=None,
    )

    assert result["validation_passed"] is True
    assert result["expected_archive_count"] == 2
    assert result["valid_archive_count"] == 2
    assert result["expected_pdf_count"] == 285
    assert result["successful_pdf_count"] == 285
    assert result["failed_pdf_count"] == 0
    assert (
        result["report_key"]
        == "reports/wave1-test/validation-report.json"
    )

    mock_s3.put_object.assert_called_once()

    put_request = mock_s3.put_object.call_args.kwargs

    assert put_request["Bucket"] == "output-bucket"
    assert (
        put_request["Key"]
        == "reports/wave1-test/validation-report.json"
    )

    report = json.loads(
        put_request["Body"].decode("utf-8")
    )

    assert report["validation_passed"] is True
    assert report["expected_archive_count"] == 2
