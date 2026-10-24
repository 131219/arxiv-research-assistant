import pytest

from arxiv_pipeline.common.models import ArchiveWorkItem


def test_archive_work_item_accepts_batch_contract() -> None:
    item = ArchiveWorkItem.model_validate(
        {
            "runId": "poc-run-001",
            "sourceBucket": "arxiv",
            "sourceKey": "pdf/example.tar",
            "requestPayer": "requester",
            "destinationBucket": "research-corpus-example",
            "destinationPrefix": "knowledge-base/arxiv/papers/",
            "statusPrefix": "status/arxiv/",
        }
    )

    assert item.run_id == "poc-run-001"
    assert item.request_payer == "requester"


def test_conversation_message_request_trims_message_and_defaults_max_papers():
    from arxiv_pipeline.api.models import ConversationMessageRequest

    request = ConversationMessageRequest(
        message="   Which of these approaches works best for long-context inference?   "
    )

    assert request.message == (
        "Which of these approaches works best for long-context inference?"
    )
    assert request.max_papers == 5


def test_conversation_message_request_rejects_unknown_fields():
    import pytest

    from arxiv_pipeline.api.models import ConversationMessageRequest

    with pytest.raises(ValueError):
        ConversationMessageRequest(
            message="Compare these approaches.",
            max_papers=5,
            unexpected="not-allowed",
        )


@pytest.mark.parametrize(
    "invalid_max_papers",
    [
        0,
        11,
        5.0,
        "5",
        True,
        None,
    ],
)
def test_conversation_message_request_rejects_invalid_max_papers(
    invalid_max_papers,
):
    from arxiv_pipeline.api.models import ConversationMessageRequest

    with pytest.raises(ValueError):
        ConversationMessageRequest(
            message="Compare these approaches.",
            max_papers=invalid_max_papers,
        )


def test_conversation_message_response_contains_conversation_and_citations():
    from arxiv_pipeline.api.models import (
        ConversationMessage,
        ConversationMessageResponse,
        WebsiteCitation,
    )

    response = ConversationMessageResponse(
        request_id="req-123",
        conversation_id="conv-123",
        message=ConversationMessage(
            role="assistant",
            content="Long-context methods reduce memory pressure [2606.03928].",
            citations=[
                WebsiteCitation(
                    paper_id="2606.03928",
                    arxiv_url="https://arxiv.org/abs/2606.03928",
                    passage="Relevant passage.",
                )
            ],
        ),
    )

    assert response.conversation_id == "conv-123"
    assert response.message.role == "assistant"
    assert response.message.citations[0].paper_id == "2606.03928"
