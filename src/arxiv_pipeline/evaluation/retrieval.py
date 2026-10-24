from arxiv_pipeline.retrieval.models import RetrievedPaper


def build_evaluation_record(
    query_id: str,
    query: str,
    papers: list[RetrievedPaper],
) -> dict:
    return {
        "query_id": query_id,
        "query": query,
        "results": [
            {
                "rank": rank,
                "paper_id": paper.paper_id,
                "score": paper.score,
                "passage": paper.passage,
            }
            for rank, paper in enumerate(papers, start=1)
        ],
    }
