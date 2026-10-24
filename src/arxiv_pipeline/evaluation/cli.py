import argparse
from pathlib import Path

from arxiv_pipeline.api.bedrock_service import BedrockKnowledgeBaseService
from arxiv_pipeline.evaluation.queries import RETRIEVAL_EVALUATION_QUERIES
from arxiv_pipeline.evaluation.runner import run_retrieval_evaluation
from arxiv_pipeline.retrieval.service import PaperRetrievalService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run retrieval-quality evaluation queries against the Bedrock Knowledge Base."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tmp/retrieval-evaluation.json"),
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        default=5,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    backend = BedrockKnowledgeBaseService()
    retrieval_service = PaperRetrievalService(
        backend=backend,
    )

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    run_retrieval_evaluation(
        retrieval_service=retrieval_service,
        queries=RETRIEVAL_EVALUATION_QUERIES,
        max_papers=args.max_papers,
        output_path=args.output,
    )

    print(f"Wrote retrieval evaluation to {args.output}")


if __name__ == "__main__":
    main()
