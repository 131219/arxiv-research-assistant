from pydantic import BaseModel

from arxiv_pipeline.retrieval.models import RetrievedPaper


class SynthesisResult(BaseModel):
    answer: str
    cited_papers: list[RetrievedPaper]
