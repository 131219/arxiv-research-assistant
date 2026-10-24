from datetime import date
from pydantic import BaseModel, Field


class ArchiveWorkItem(BaseModel):
    run_id: str = Field(alias="runId")
    source_bucket: str = Field(alias="sourceBucket")
    source_key: str = Field(alias="sourceKey")
    request_payer: str = Field(default="requester", alias="requestPayer")
    destination_bucket: str = Field(alias="destinationBucket")
    destination_prefix: str = Field(alias="destinationPrefix")
    status_prefix: str = Field(alias="statusPrefix")


class PaperMetadata(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    primary_category: str | None = None
    categories: list[str] = []
    publication_year: int | None = None
    published_date: date | None = None
    source: str = "arxiv"
    document_type: str = "research_paper"
