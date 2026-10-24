from pydantic import BaseModel


class RetrievedPaper(BaseModel):
    paper_id: str
    archive_id: str | None = None
    year: int | None = None
    month: int | None = None
    passage: str
    arxiv_url: str
    source_uri: str | None = None
    score: float | None = None
