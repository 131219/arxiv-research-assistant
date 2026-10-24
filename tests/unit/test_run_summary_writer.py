import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


LAMBDA_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "lambda"
    / "run_summary_writer"
    / "lambda_function.py"
)


def load_lambda_module(monkeypatch):
    fake_s3 = MagicMock()

    fake_boto3 = types.SimpleNamespace(
        client=lambda service_name: fake_s3
    )

    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    spec = importlib.util.spec_from_file_location(
        "run_summary_lambda",
        LAMBDA_PATH,
    )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module, fake_s3


def test_lambda_writes_valid_json_summary(monkeypatch):
    module, fake_s3 = load_lambda_module(monkeypatch)

    event = {
        "output_bucket": "test-output-bucket",
        "run_id": "test-run-123",
        "run_summary": {
            "run_id": "test-run-123",
            "ingestion_status": "COMPLETE",
            "max_concurrency": 3,
        },
    }

    result = module.lambda_handler(event, None)

    fake_s3.put_object.assert_called_once()

    request = fake_s3.put_object.call_args.kwargs

    assert request["Bucket"] == "test-output-bucket"
    assert request["Key"] == "runs/test-run-123/summary.json"
    assert request["ContentType"] == "application/json"

    stored_summary = json.loads(
        request["Body"].decode("utf-8")
    )

    assert stored_summary == event["run_summary"]

    assert result == {
        "bucket": "test-output-bucket",
        "key": "runs/test-run-123/summary.json",
        "status": "WRITTEN",
    }
