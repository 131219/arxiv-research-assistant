from arxiv_pipeline.evaluation.retrieval import build_evaluation_record
from arxiv_pipeline.retrieval.models import RetrievedPaper


def test_build_evaluation_record_preserves_ranked_retrieval_evidence():
    papers = [
        RetrievedPaper(
            paper_id="2606.11111",
            passage="Sparse attention reduces computation.",
            arxiv_url="https://arxiv.org/abs/2606.11111",
            score=0.81,
        ),
        RetrievedPaper(
            paper_id="2606.22222",
            passage="KV-cache optimization reduces memory use.",
            arxiv_url="https://arxiv.org/abs/2606.22222",
            score=0.72,
        ),
    ]

    record = build_evaluation_record(
        query_id="attention-efficiency",
        query="What approaches improve transformer attention efficiency?",
        papers=papers,
    )

    assert record == {
        "query_id": "attention-efficiency",
        "query": "What approaches improve transformer attention efficiency?",
        "results": [
            {
                "rank": 1,
                "paper_id": "2606.11111",
                "score": 0.81,
                "passage": "Sparse attention reduces computation.",
            },
            {
                "rank": 2,
                "paper_id": "2606.22222",
                "score": 0.72,
                "passage": "KV-cache optimization reduces memory use.",
            },
        ],
    }


def test_retrieval_evaluation_queries_have_unique_ids():
    from arxiv_pipeline.evaluation.queries import RETRIEVAL_EVALUATION_QUERIES

    query_ids = [
        item["query_id"]
        for item in RETRIEVAL_EVALUATION_QUERIES
    ]

    assert len(query_ids) == len(set(query_ids))
    assert all(item["query"].strip() for item in RETRIEVAL_EVALUATION_QUERIES)


def test_run_retrieval_evaluation_writes_ranked_json(tmp_path):
    import json
    from unittest.mock import MagicMock

    from arxiv_pipeline.evaluation.runner import run_retrieval_evaluation
    from arxiv_pipeline.retrieval.models import RetrievedPaper

    retrieval_service = MagicMock()

    retrieval_service.search.return_value = [
        RetrievedPaper(
            paper_id="2606.11111",
            passage="Sparse attention reduces computation.",
            arxiv_url="https://arxiv.org/abs/2606.11111",
            score=0.81,
        ),
    ]

    output_path = tmp_path / "retrieval-evaluation.json"

    run_retrieval_evaluation(
        retrieval_service=retrieval_service,
        queries=[
            {
                "query_id": "attention-efficiency",
                "query": "What approaches improve transformer attention efficiency?",
            },
        ],
        max_papers=5,
        output_path=output_path,
    )

    body = json.loads(output_path.read_text())

    assert body == [
        {
            "query_id": "attention-efficiency",
            "query": "What approaches improve transformer attention efficiency?",
            "results": [
                {
                    "rank": 1,
                    "paper_id": "2606.11111",
                    "score": 0.81,
                    "passage": "Sparse attention reduces computation.",
                },
            ],
        },
    ]

    retrieval_service.search.assert_called_once_with(
        query="What approaches improve transformer attention efficiency?",
        max_papers=5,
    )


def test_refine_retrieval_query_preserves_original_intent():
    from arxiv_pipeline.retrieval.query_refinement import refine_retrieval_query

    refined = refine_retrieval_query(
        "What approaches improve transformer attention efficiency?"
    )

    assert "attention" in refined.lower()
    assert "computational" in refined.lower() or "memory" in refined.lower()
    assert refined != "What approaches improve transformer attention efficiency?"


def test_refine_retrieval_query_handles_long_context_efficiency():
    from arxiv_pipeline.retrieval.query_refinement import refine_retrieval_query

    original = (
        "What methods improve transformer efficiency "
        "for long-context processing?"
    )

    refined = refine_retrieval_query(original)

    assert refined != original
    assert "long-context" in refined.lower()
    assert (
        "kv-cache" in refined.lower()
        or "memory" in refined.lower()
        or "attention" in refined.lower()
    )


def test_refine_retrieval_query_leaves_specific_query_unchanged():
    from arxiv_pipeline.retrieval.query_refinement import refine_retrieval_query

    original = (
        "What techniques reduce KV-cache memory "
        "during transformer inference?"
    )

    assert refine_retrieval_query(original) == original
