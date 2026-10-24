from functools import lru_cache
from typing import Any

from mcp.server import MCPServer

from arxiv_pipeline.api.bedrock_service import (
    BedrockKnowledgeBaseService,
)
from arxiv_pipeline.mcp.models import (
    PaperSearchResult,
    SearchPapersResponse,
)
from arxiv_pipeline.retrieval.service import PaperRetrievalService

server = MCPServer(
    name="arxiv-research-mcp",
)


@lru_cache
def get_bedrock_service() -> BedrockKnowledgeBaseService:
    return BedrockKnowledgeBaseService()


@lru_cache
def get_retrieval_service() -> PaperRetrievalService:
    return PaperRetrievalService(
        backend=get_bedrock_service(),
    )


def normalize_result(
    result: dict[str, Any],
) -> PaperSearchResult:
    service = get_bedrock_service()
    metadata = result.get("metadata", {})

    paper_id = metadata.get("paper_id")

    if not paper_id:
        raise ValueError("retrieval result is missing paper_id")

    return PaperSearchResult(
        paper_id=paper_id,
        archive_id=metadata.get("archive_id"),
        year=metadata.get("target_year"),
        month=metadata.get("target_month"),
        text=service._extract_text(result),
        arxiv_url=f"https://arxiv.org/abs/{paper_id}",
        source_uri=service._extract_source_uri(result),
        score=result.get("score"),
    )


@server.tool()
def search_papers(
    query: str,
    top_k: int = 5,
) -> SearchPapersResponse:
    """
    Search the arXiv research paper Knowledge Base.

    Args:
        query: Natural-language search query.
        top_k: Number of semantic search results to return.

    Returns:
        Relevant paper passages together with metadata,
        source locations, and retrieval scores.
    """

    query = query.strip()

    if not query:
        raise ValueError("query must not be empty")

    if top_k < 1 or top_k > 20:
        raise ValueError("top_k must be between 1 and 20")

    service = get_retrieval_service()

    retrieved_papers = service.search(
        query=query,
        max_papers=top_k,
    )

    results = [
        PaperSearchResult(
            paper_id=paper.paper_id,
            archive_id=paper.archive_id,
            year=paper.year,
            month=paper.month,
            text=paper.passage,
            arxiv_url=paper.arxiv_url,
            source_uri=paper.source_uri,
            score=paper.score,
        )
        for paper in retrieved_papers
    ]

    return SearchPapersResponse(
        query=query,
        result_count=len(results),
        results=results,
    )


if __name__ == "__main__":
    server.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8000,
        stateless_http=True,
        json_response=True,
    )
