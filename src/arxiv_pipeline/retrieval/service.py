from typing import Any, Protocol

from arxiv_pipeline.retrieval.models import RetrievedPaper
from arxiv_pipeline.retrieval.query_refinement import refine_retrieval_query


class RetrievalError(Exception):
    """Base error for retrieval failures."""


class RetrievalUnavailableError(RetrievalError):
    """Raised when the retrieval dependency is temporarily unavailable."""


class MalformedRetrievalResultError(RetrievalError):
    """Raised when a retrieval result has an unexpected shape."""


class RetrievalBackend(Protocol):
    def retrieve(
        self,
        question: str,
        number_of_results: int,
    ) -> list[dict[str, Any]]: ...


class PaperRetrievalService:
    def __init__(
        self,
        backend: RetrievalBackend,
    ) -> None:
        self._backend = backend

    def search(
        self,
        query: str,
        max_papers: int,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> list[RetrievedPaper]:
        candidate_count = min(max_papers * 3, 20)

        contextual_query = query

        if conversation_history:
            prior_user_messages = [
                message["content"]
                for message in conversation_history
                if message.get("role") == "user"
                and isinstance(message.get("content"), str)
            ]

            if prior_user_messages:
                contextual_query = (
                    "\n".join(prior_user_messages)
                    + "\n"
                    + query
                )

        retrieval_query = refine_retrieval_query(contextual_query)

        try:
            raw_results = self._backend.retrieve(
                question=retrieval_query,
                number_of_results=candidate_count,
            )
        except Exception as exc:
            raise RetrievalError("paper retrieval failed") from exc

        papers: list[RetrievedPaper] = []
        seen_paper_ids: set[str] = set()

        for result in raw_results:
            metadata = result.get("metadata") or {}

            if not isinstance(metadata, dict):
                raise MalformedRetrievalResultError(
                    "retrieval result metadata must be a dictionary"
                )

            content = result.get("content") or {}

            if not isinstance(content, dict):
                raise MalformedRetrievalResultError(
                    "retrieval result content must be a dictionary"
                )

            paper_id = metadata.get("paper_id")
            if not paper_id:
                raise MalformedRetrievalResultError(
                    "retrieval result is missing paper_id"
                )

            if not isinstance(paper_id, str):
                raise MalformedRetrievalResultError(
                    "retrieval result paper_id must be a string"
                )

            if paper_id in seen_paper_ids:
                continue

            location = result.get("location") or {}

            if not isinstance(location, dict):
                raise MalformedRetrievalResultError(
                    "retrieval result location must be a dictionary"
                )

            s3_location = location.get("s3Location") or {}

            if not isinstance(s3_location, dict):
                raise MalformedRetrievalResultError(
                    "retrieval result s3Location must be a dictionary"
                )

            paper = RetrievedPaper(
                paper_id=paper_id,
                archive_id=metadata.get("archive_id"),
                year=metadata.get("target_year"),
                month=metadata.get("target_month"),
                passage=content.get("text", ""),
                arxiv_url=f"https://arxiv.org/abs/{paper_id}",
                source_uri=s3_location.get("uri"),
                score=result.get("score"),
            )

            papers.append(paper)
            seen_paper_ids.add(paper_id)

            if len(papers) == max_papers:
                break

        return papers
