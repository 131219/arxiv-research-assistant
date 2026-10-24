from typing import Any

from botocore.exceptions import ClientError

from arxiv_pipeline.retrieval.models import RetrievedPaper
from arxiv_pipeline.synthesis.service import SynthesisUnavailableError


class BedrockGenerationBackend:
    def __init__(
        self,
        client: Any,
        model_id: str,
    ) -> None:
        self._client = client
        self._model_id = model_id

    def _build_prompt(
        self,
        question: str,
        papers: list[RetrievedPaper],
        conversation_history: list[dict[str, str]] | None = None,
        citation_retry: bool = False,
    ) -> str:
        source_sections: list[str] = []

        for paper in papers:
            source_sections.append(
                f"[{paper.paper_id}]\n"
                f"{paper.passage}"
            )

        sources = "\n\n".join(source_sections)

        conversation_context = ""

        citation_repair = ""
        if citation_retry:
            citation_repair = (
                "Citation repair instructions:\n"
                "The previous draft failed citation validation.\n"
                "Every quantitative statement must include an exact supplied "
                "[paper_id] citation in the same sentence.\n"
                "Every factual conclusion or comparison must be directly supported "
                "by an exact supplied [paper_id] citation.\n"
                "Do not output unsupported numbers.\n"
                "Do not cite any paper ID that is not provided in the evidence.\n\n"
            )

        if conversation_history:
            history_lines = [
                f"{message['role'].upper()}: {message['content']}"
                for message in conversation_history
            ]

            conversation_context = (
                "Conversation context:\n"
                + "\n".join(history_lines)
                + "\n\n"
            )

        return (
            "Answer the user's research question using only the "
            "provided arXiv evidence.\n\n"
            "Rules:\n"
            "1. Do not use facts that are not supported by the evidence.\n"
            "2. Cite research claims using exact [paper_id] citations.\n"
            "3. Only cite paper IDs provided below.\n"
            "4. If the evidence is insufficient, say so clearly.\n"
            "5. For each major approach, explain how each major approach works "
            "and why it improves efficiency.\n"
            "6. Include quantitative findings when they are present in the evidence.\n"
            "7. Discuss limitations or trade-offs when supported by the evidence.\n"
            "8. Compare related approaches across papers when the evidence allows it.\n"
            "9. Use 2-4 sentences per major approach rather than a one-line summary.\n"
            "10. Synthesize the evidence across papers instead of simply listing "
            "individual passages.\n"
            "11. Every major approach must include at least one exact [paper_id] citation.\n"
            "12. Place citations directly after the claims they support.\n"
            "13. Never present a quantitative finding without a citation.\n"
            "14. Never infer, transform, or combine numerical results.\n"
            "15. Reproduce quantitative findings only when the exact metric and value are explicitly supported by the evidence.\n"
            "16. Do not assign a number to a different metric than the source states.\n"
            "17. Every factual conclusion or comparison must have a supporting citation.\n"
            "18. Do not imply that a retrieved paper originally introduced a method "
            "unless the evidence explicitly supports that attribution.\n"
            "19. If the evidence discusses or cites prior work, describe the retrieved "
            "paper as discussing, reviewing, evaluating, or reporting that prior work.\n\n"
            f"{citation_repair}"
            f"{conversation_context}"
            f"Question:\n{question}\n\n"
            f"Evidence:\n{sources}"
        )

    def generate(
        self,
        question: str,
        papers: list[RetrievedPaper],
        conversation_history: list[dict[str, str]] | None = None,
        citation_retry: bool = False,
    ) -> str:
        prompt = self._build_prompt(
            question=question,
            papers=papers,
            conversation_history=conversation_history,
            citation_retry=citation_retry,
        )

        try:
            response = self._client.converse(
                modelId=self._model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": prompt,
                            }
                        ],
                    }
                ],
                inferenceConfig={
                    "maxTokens": 1600,
                    "temperature": 0.1,
                    "topP": 0.9,
                },
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")

            if error_code in {
                "ThrottlingException",
                "ServiceUnavailableException",
            }:
                raise SynthesisUnavailableError(
                    "generation is temporarily unavailable"
                ) from exc

            raise

        content_blocks = (
            response
            .get("output", {})
            .get("message", {})
            .get("content", [])
        )

        answer_parts = [
            block["text"]
            for block in content_blocks
            if isinstance(block, dict)
            and isinstance(block.get("text"), str)
        ]

        if not answer_parts:
            raise SynthesisUnavailableError(
                "generation returned no usable text"
            )

        return "\n".join(answer_parts)
