import json
from pathlib import Path


STATE_MACHINE_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "step-functions"
    / "state-machine.asl.json"
)


def load_definition():
    with STATE_MACHINE_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def test_distributed_map_has_retry_and_zero_tolerance():
    definition = load_definition()

    process_archives = definition["States"]["ProcessArchives"]

    assert process_archives["Type"] == "Map"
    assert process_archives["ItemProcessor"]["ProcessorConfig"] == {
        "Mode": "DISTRIBUTED",
        "ExecutionType": "STANDARD",
    }
    assert process_archives["ToleratedFailureCount"] == 0

    submit_job = (
        process_archives["ItemProcessor"]
        ["States"]["SubmitBatchJob"]
    )

    retry_errors = {
        error
        for retry in submit_job["Retry"]
        for error in retry["ErrorEquals"]
    }

    assert "Batch.AWSBatchException" in retry_errors
    assert "States.TaskFailed" in retry_errors


def test_complete_ingestion_checks_document_failures():
    definition = load_definition()
    states = definition["States"]

    complete_choice = next(
        choice
        for choice in states[
            "CheckBedrockIngestionStatus"
        ]["Choices"]
        if choice.get("StringEquals") == "COMPLETE"
    )

    assert (
        complete_choice["Next"]
        == "CheckBedrockDocumentFailures"
    )

    failure_check = states["CheckBedrockDocumentFailures"]

    assert failure_check["Type"] == "Choice"
    assert failure_check["Default"] == "BedrockDocumentsFailed"

    zero_failures = failure_check["Choices"][0]

    assert zero_failures == {
        "Variable": (
            "$.bedrock_status.IngestionJob."
            "Statistics.NumberOfDocumentsFailed"
        ),
        "NumericEquals": 0,
        "Next": "BuildRunSummary",
    }


def test_bedrock_document_failures_stop_workflow():
    definition = load_definition()
    states = definition["States"]

    failure_state = states["BedrockDocumentsFailed"]

    assert failure_state["Type"] == "Fail"
    assert failure_state["Error"] == "BedrockDocumentsFailed"


def test_successful_ingestion_builds_and_writes_summary():
    definition = load_definition()
    states = definition["States"]

    assert states["BuildRunSummary"]["Next"] == "WriteRunSummary"

    write_summary = states["WriteRunSummary"]

    assert write_summary["Resource"] == (
        "arn:aws:states:::lambda:invoke"
    )
    assert (
        write_summary["Parameters"]["FunctionName"]
        == "${RunSummaryFunctionArn}"
    )
    assert write_summary["Next"] == "PipelineSucceeded"
