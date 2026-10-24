import os
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from arxiv_pipeline.api.models import ResearchCitation
from arxiv_pipeline.retrieval.service import RetrievalUnavailableError


class BedrockKnowledgeBaseService:
    def __init__(self) -> None:
        self.region = os.getenv("AWS_REGION", "us-east-1")

        self.knowledge_base_id = os.getenv("BEDROCK_KNOWLEDGE_BASE_ID")

        # Optional now.
        # MCP retrieval does not require a generative model.
        self.model_id = os.getenv("BEDROCK_MODEL_ID")

        aws_config = Config(
            connect_timeout=3,
            read_timeout=10,
            retries={
                "max_attempts": 3,
                "mode": "standard",
            },
        )

        # Used for Knowledge Base retrieval.
        self.agent_runtime = boto3.client(
            "bedrock-agent-runtime",
            region_name=self.region,
            config=aws_config,
        )

        # Only create the generative Bedrock client if a model is configured.
        self.bedrock_runtime = (
            boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                config=aws_config,
            )
            if self.model_id
            else None
        )

    def retrieve(
        self,
        question: str,
        number_of_results: int,
    ) -> list[dict[str, Any]]:
        """
        Retrieve semantically relevant chunks from the Bedrock Knowledge Base.
        """
        try:
            response = self.agent_runtime.retrieve(
                knowledgeBaseId=self.knowledge_base_id,
                retrievalQuery={
                    "text": question,
                },
                retrievalConfiguration={
                    "managedSearchConfiguration": {
                        "numberOfResults": number_of_results,
                    }
                },
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")

            if error_code in {
                "ThrottlingException",
                "ServiceUnavailableException",
            }:
                raise RetrievalUnavailableError(
                    "Bedrock retrieval is temporarily unavailable"
                ) from exc

            raise

        return response.get("retrievalResults", [])

    @staticmethod
    def _extract_text(result: dict[str, Any]) -> str:
        """
        Extract text content from one Bedrock retrieval result.
        """
        content = result.get("content", {})

        if "text" in content:
            return content["text"]

        return ""

    @staticmethod
    def _extract_source_uri(
        result: dict[str, Any],
    ) -> str | None:
        """
        Extract the original source URI from a Bedrock retrieval result.
        """
        location = result.get("location", {})

        s3_location = location.get("s3Location")
        if s3_location:
            return s3_location.get("uri")

        web_location = location.get("webLocation")
        if web_location:
            return web_location.get("url")

        return None

    def _build_context(
        self,
        retrieval_results: list[dict[str, Any]],
    ) -> str:
        """
        Convert retrieval results into context for an LLM prompt.
        """
        context_sections: list[str] = []

        for result in retrieval_results:
            text = self._extract_text(result)[:500]
            source_uri = self._extract_source_uri(result)
            metadata = result.get("metadata", {})
            paper_id = metadata.get("paper_id", "unknown")

            context_sections.append(
                f"[Paper {paper_id}]\n"
                f"URI: {source_uri or 'unknown'}\n"
                f"{text}"
            )

        return "\n\n".join(context_sections)

    def generate_answer(
        self,
        question: str,
        retrieval_results: list[dict[str, Any]],
    ) -> str:
        """
        Generate a final answer using a configured Bedrock foundation model.

        This is optional and is not required by the MCP retrieval path.
        """
        if not self.model_id or self.bedrock_runtime is None:
            raise ValueError("BEDROCK_MODEL_ID is required for answer generation.")

        context = self._build_context(retrieval_results)

        prompt = (
            "Answer the user's question using only the provided "
            "arXiv source passages.\n\n"
            "Rules:\n"
            "1. Do not invent facts not found in the sources.\n"
            "2. Cite every research claim using the paper ID exactly "
            "as shown in the sources, for example [2606.04032].\n"
            "3. Do not cite papers that are not present in the "
            "provided sources.\n"
            "4. If the sources do not contain enough information, "
            "say that clearly.\n\n"
            f"Question:\n{question}\n\n"
            f"Sources:\n{context}"
        )

        response = self.bedrock_runtime.converse(
            modelId=self.model_id,
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
                "maxTokens": 1000,
                "temperature": 0.1,
                "topP": 0.9,
            },
        )

        content_blocks = (
            response.get("output", {}).get("message", {}).get("content", [])
        )

        answer_parts = [block["text"] for block in content_blocks if "text" in block]

        if not answer_parts:
            raise RuntimeError("Bedrock returned no text response.")

        return "\n".join(answer_parts)

    def ask(
        self,
        question: str,
        number_of_results: int,
    ) -> tuple[str, list[ResearchCitation]]:
        """
        Retrieve relevant chunks and optionally generate an answer.

        This method is used by the existing FastAPI /ask endpoint.
        """
        retrieval_results = self.retrieve(
            question=question,
            number_of_results=number_of_results,
        )

        if not retrieval_results:
            return (
                "I could not find relevant information in the " "arXiv Knowledge Base.",
                [],
            )

        citations: list[ResearchCitation] = []

        for result in retrieval_results:
            metadata = result.get("metadata", {})

            paper_id = metadata.get("paper_id")
            if not paper_id:
                raise RuntimeError(
                    "Retrieved Bedrock result is missing paper_id."
                )

            year = metadata.get("target_year")
            month = metadata.get("target_month")

            citations.append(
                ResearchCitation(
                    paper_id=str(paper_id),
                    archive_id=metadata.get("archive_id"),
                    year=int(year) if year is not None else None,
                    month=int(month) if month is not None else None,
                    source_uri=self._extract_source_uri(result),
                    passage=self._extract_text(result),
                    score=result.get("score"),
                )
            )

        answer = self.generate_answer(
            question=question,
            retrieval_results=retrieval_results,
        )

        return answer, citations
