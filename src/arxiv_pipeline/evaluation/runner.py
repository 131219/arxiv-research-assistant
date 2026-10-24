import json
from pathlib import Path
from typing import Any

from arxiv_pipeline.evaluation.retrieval import build_evaluation_record


def run_retrieval_evaluation(
    retrieval_service: Any,
    queries: list[dict[str, str]],
    max_papers: int,
    output_path: Path,
) -> None:
    records = []

    for item in queries:
        papers = retrieval_service.search(
            query=item["query"],
            max_papers=max_papers,
        )

        records.append(
            build_evaluation_record(
                query_id=item["query_id"],
                query=item["query"],
                papers=papers,
            )
        )

    output_path.write_text(
        json.dumps(records, indent=2)
    )
