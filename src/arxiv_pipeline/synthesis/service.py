import re
from typing import Protocol

from arxiv_pipeline.retrieval.models import RetrievedPaper
from arxiv_pipeline.synthesis.models import SynthesisResult


class SynthesisError(Exception):
    """Base error for synthesis failures."""


class SynthesisUnavailableError(SynthesisError):
    """Raised when the generation dependency is temporarily unavailable."""


class CitationValidationError(SynthesisError):
    """Raised when generated citations cannot be safely validated."""


class GenerationBackend(Protocol):
    def generate(
        self,
        question: str,
        papers: list[RetrievedPaper],
        conversation_history: list[dict[str, str]] | None = None,
        citation_retry: bool = False,
    ) -> str: ...


class SynthesisService:
    def __init__(
        self,
        backend: GenerationBackend | None = None,
    ) -> None:
        self._backend = backend

    def validate_answer(
        self,
        answer: str,
        papers: list[RetrievedPaper],
    ) -> SynthesisResult:
        answer = re.sub(r"\s*\[\d+\]", "", answer)

        citation_pattern = (
            r"\[((?:\d{4}\.\d{4,5})(?:v\d+)?)\]"
        )

        numbered_items = re.findall(
            r"(?ms)^\s*\d+\.\s+(.+?)(?=^\s*\d+\.\s+|\Z)",
            answer,
        )

        for item in numbered_items:
            if not re.search(citation_pattern, item):
                raise CitationValidationError(
                    "numbered research item contains no citation"
                )

        sentences = re.split(r"(?<=[.!?])\s+", answer)

        for sentence in sentences:
            if re.search(
                r"\b\d+(?:\.\d+)?\s*(?:%|x)(?=\s|[.,;:!?)]|$)",
                sentence,
                re.IGNORECASE,
            ):
                if not re.search(citation_pattern, sentence):
                    raise CitationValidationError(
                        "quantitative claim contains no citation"
                    )

        papers_by_id = {
            paper.paper_id: paper
            for paper in papers
        }

        cited_paper_ids: list[str] = []
        seen_paper_ids: set[str] = set()

        for paper_id in re.findall(
            citation_pattern,
            answer,
        ):
            if paper_id not in papers_by_id:
                raise CitationValidationError(
                    f"unsupported citation: {paper_id}"
                )

            if paper_id in seen_paper_ids:
                continue

            cited_paper_ids.append(paper_id)
            seen_paper_ids.add(paper_id)

        if papers and not cited_paper_ids:
            raise CitationValidationError(
                "generated answer contains no citations"
            )

        cited_papers = [
            papers_by_id[paper_id]
            for paper_id in cited_paper_ids
        ]

        return SynthesisResult(
            answer=answer,
            cited_papers=cited_papers,
        )

    def synthesize(
        self,
        question: str,
        papers: list[RetrievedPaper],
        conversation_history: list[dict[str, str]] | None = None,
    ) -> SynthesisResult:
        if self._backend is None:
            raise RuntimeError("generation backend is not configured")

        if conversation_history is None:
            answer = self._backend.generate(
                question=question,
                papers=papers,
            )
        else:
            answer = self._backend.generate(
                question=question,
                papers=papers,
                conversation_history=conversation_history,
            )

        try:
            return self.validate_answer(
                answer=answer,
                papers=papers,
            )
        except CitationValidationError:
            retry_kwargs = {
                "question": question,
                "papers": papers,
                "citation_retry": True,
            }

            if conversation_history is not None:
                retry_kwargs["conversation_history"] = conversation_history

            retry_answer = self._backend.generate(**retry_kwargs)

            return self.validate_answer(
                answer=retry_answer,
                papers=papers,
            )
