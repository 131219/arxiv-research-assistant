from pydantic import BaseModel, Field


class PaperSearchResult(BaseModel):
    paper_id: str
    archive_id: str | None = None
    year: int | None = None
    month: int | None = None

    text: str = Field(description="Relevant passage retrieved from the paper.")

    arxiv_url: str = Field(
        description="Public arXiv page for the research paper."
    )
    source_uri: str | None = None
    score: float | None = None


class SearchPapersResponse(BaseModel):
    query: str
    result_count: int
    results: list[PaperSearchResult]
