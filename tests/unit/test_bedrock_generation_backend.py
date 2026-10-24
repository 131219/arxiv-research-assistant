from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from arxiv_pipeline.retrieval.models import RetrievedPaper
from arxiv_pipeline.synthesis.bedrock_backend import (
    BedrockGenerationBackend,
)
from arxiv_pipeline.synthesis.service import SynthesisUnavailableError


def make_paper(
    paper_id: str,
    passage: str,
) -> RetrievedPaper:
    return RetrievedPaper(
        paper_id=paper_id,
        passage=passage,
        arxiv_url=f"https://arxiv.org/abs/{paper_id}",
    )


def test_generate_builds_grounded_prompt_and_returns_model_text():
    client = MagicMock()

    client.converse.return_value = {
        "output": {
            "message": {
                "content": [
                    {
                        "text": (
                            "Sparse attention improves efficiency "
                            "[2606.11111]."
                        )
                    }
                ]
            }
        }
    }

    backend = BedrockGenerationBackend(
        client=client,
        model_id="test-model",
    )

    papers = [
        make_paper(
            "2606.11111",
            "Sparse attention reduces computation.",
        ),
        make_paper(
            "2606.22222",
            "Another method reduces memory use.",
        ),
    ]

    answer = backend.generate(
        question="How can attention be more efficient?",
        papers=papers,
    )

    assert answer == (
        "Sparse attention improves efficiency [2606.11111]."
    )

    client.converse.assert_called_once()

    _, kwargs = client.converse.call_args

    assert kwargs["modelId"] == "test-model"
    assert kwargs["inferenceConfig"]["maxTokens"] == 1600

    prompt = kwargs["messages"][0]["content"][0]["text"]

    assert "How can attention be more efficient?" in prompt
    assert "[2606.11111]" in prompt
    assert "Sparse attention reduces computation." in prompt
    assert "[2606.22222]" in prompt
    assert "Another method reduces memory use." in prompt


def test_generate_rejects_model_response_without_text():
    client = MagicMock()

    client.converse.return_value = {
        "output": {
            "message": {
                "content": [],
            }
        }
    }

    backend = BedrockGenerationBackend(
        client=client,
        model_id="test-model",
    )

    with pytest.raises(
        SynthesisUnavailableError,
        match="generation returned no usable text",
    ):
        backend.generate(
            question="Explain attention",
            papers=[
                make_paper(
                    "2606.11111",
                    "Relevant evidence.",
                )
            ],
        )


def test_generate_translates_throttling_into_synthesis_unavailable():
    client = MagicMock()

    client.converse.side_effect = ClientError(
        {
            "Error": {
                "Code": "ThrottlingException",
                "Message": "Rate exceeded",
            }
        },
        "Converse",
    )

    backend = BedrockGenerationBackend(
        client=client,
        model_id="test-model",
    )

    with pytest.raises(
        SynthesisUnavailableError,
        match="generation is temporarily unavailable",
    ):
        backend.generate(
            question="Explain attention",
            papers=[
                make_paper(
                    "2606.11111",
                    "Relevant evidence.",
                )
            ],
        )


def test_generate_translates_service_unavailable_into_synthesis_unavailable():
    client = MagicMock()

    client.converse.side_effect = ClientError(
        {
            "Error": {
                "Code": "ServiceUnavailableException",
                "Message": "Service temporarily unavailable",
            }
        },
        "Converse",
    )

    backend = BedrockGenerationBackend(
        client=client,
        model_id="test-model",
    )

    with pytest.raises(
        SynthesisUnavailableError,
        match="generation is temporarily unavailable",
    ):
        backend.generate(
            question="Explain attention",
            papers=[
                make_paper(
                    "2606.11111",
                    "Relevant evidence.",
                )
            ],
        )


def test_generate_translates_empty_model_response_into_synthesis_unavailable():
    client = MagicMock()

    client.converse.return_value = {
        "output": {
            "message": {
                "content": [],
            }
        }
    }

    backend = BedrockGenerationBackend(
        client=client,
        model_id="test-model",
    )

    with pytest.raises(
        SynthesisUnavailableError,
        match="generation returned no usable text",
    ):
        backend.generate(
            question="Explain attention",
            papers=[
                make_paper(
                    "2606.11111",
                    "Relevant evidence.",
                )
            ],
        )


def test_build_prompt_requests_deep_cross_paper_research_synthesis():
    backend = BedrockGenerationBackend(
        client=MagicMock(),
        model_id="test-model",
    )

    papers = [
        make_paper(
            "2606.11111",
            "Sparse attention reduces the number of attention operations.",
        ),
        make_paper(
            "2606.22222",
            "KV-cache optimization reduces repeated inference work.",
        ),
    ]

    prompt = backend._build_prompt(
        question="How can transformer attention be made more efficient?",
        papers=papers,
    )

    assert "explain how each major approach works" in prompt
    assert "why it improves efficiency" in prompt
    assert "quantitative findings" in prompt
    assert "limitations or trade-offs" in prompt
    assert "compare related approaches across papers" in prompt.lower()
    assert "2-4 sentences per major approach" in prompt
    assert "Every major approach must include at least one exact [paper_id] citation" in prompt
    assert "Place citations directly after the claims they support" in prompt
    assert "Never present a quantitative finding without a citation" in prompt
    assert "Never infer, transform, or combine numerical results" in prompt
    assert "Reproduce quantitative findings only when the exact metric and value are explicitly supported by the evidence" in prompt
    assert "Do not assign a number to a different metric than the source states" in prompt
    assert "Every factual conclusion or comparison must have a supporting citation" in prompt

    assert "[2606.11111]" in prompt
    assert "[2606.22222]" in prompt
    assert "Sparse attention reduces the number of attention operations." in prompt
    assert "KV-cache optimization reduces repeated inference work." in prompt


def test_build_prompt_prevents_false_primary_source_attribution():
    backend = BedrockGenerationBackend(
        client=MagicMock(),
        model_id="test-model",
    )

    papers = [
        make_paper(
            "2606.11111",
            "Prior work such as DistilBERT [21] reported faster inference.",
        ),
    ]

    prompt = backend._build_prompt(
        question="What improves transformer efficiency?",
        papers=papers,
    )

    assert (
        "Do not imply that a retrieved paper originally introduced a method "
        "unless the evidence explicitly supports that attribution"
        in prompt
    )
    assert (
        "If the evidence discusses or cites prior work, describe the retrieved "
        "paper as discussing, reviewing, evaluating, or reporting that prior work"
        in prompt
    )


def test_generate_includes_conversation_history_in_prompt():
    from unittest.mock import MagicMock

    from arxiv_pipeline.retrieval.models import RetrievedPaper
    from arxiv_pipeline.synthesis.bedrock_backend import BedrockGenerationBackend

    client = MagicMock()
    client.converse.return_value = {
        "output": {
            "message": {
                "content": [
                    {
                        "text": (
                            "KV-cache compression helps long-context inference "
                            "[2606.03928]."
                        )
                    }
                ]
            }
        }
    }

    backend = BedrockGenerationBackend(
        client=client,
        model_id="test-model",
    )

    paper = RetrievedPaper(
        paper_id="2606.03928",
        archive_id="arXiv_pdf_2606_001",
        year=2026,
        month=6,
        passage="KV-cache compression reduces memory usage.",
        arxiv_url="https://arxiv.org/abs/2606.03928",
        source_uri="s3://bucket/2606.03928.md",
        score=0.91,
    )

    backend.generate(
        question="Which of these is useful for long-context inference?",
        papers=[paper],
        conversation_history=[
            {
                "role": "user",
                "content": (
                    "What approaches improve transformer attention efficiency?"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "Several approaches include KV-cache compression."
                ),
            },
        ],
    )

    prompt = client.converse.call_args.kwargs[
        "messages"
    ][0]["content"][0]["text"]

    assert "Conversation context:" in prompt
    assert (
        "USER: What approaches improve transformer attention efficiency?"
        in prompt
    )
    assert (
        "ASSISTANT: Several approaches include KV-cache compression."
        in prompt
    )
    assert (
        "Question:\nWhich of these is useful for long-context inference?"
        in prompt
    )


def test_generate_adds_strict_citation_repair_instructions_on_retry():
    client = MagicMock()

    client.converse.return_value = {
        "output": {
            "message": {
                "content": [
                    {
                        "text": (
                            "The method improves runtime by 60% "
                            "[2606.11111]."
                        )
                    }
                ]
            }
        }
    }

    backend = BedrockGenerationBackend(
        client=client,
        model_id="test-model",
    )

    papers = [
        make_paper(
            "2606.11111",
            "The method improves runtime by 60%.",
        ),
    ]

    backend.generate(
        question="Which approach works well for short context?",
        papers=papers,
        citation_retry=True,
    )

    _, kwargs = client.converse.call_args
    prompt = kwargs["messages"][0]["content"][0]["text"]

    assert "previous draft failed citation validation" in prompt.lower()
    assert "every quantitative statement" in prompt.lower()
    assert "same sentence" in prompt.lower()
    assert "do not output unsupported numbers" in prompt.lower()
