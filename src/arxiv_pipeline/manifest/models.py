"""Typed models used by the arXiv manifest component."""

from pydantic import BaseModel, Field


class ArxivArchiveRecord(BaseModel):
    """One PDF TAR archive described by the official arXiv manifest."""

    filename: str
    yymm: str = Field(pattern=r"^\d{4}$")
    sequence_number: int
    number_of_items: int
    size_bytes: int
    tar_md5: str
    content_md5: str
    first_item: str
    last_item: str
    timestamp: str


class ArchiveWorkItem(BaseModel):
    """One archive-processing task written to the JSONL work list."""

    run_id: str
    source_bucket: str = "arxiv"
    source_key: str
    request_payer: str = "requester"
    target_year: int
    target_month: int
    sequence_number: int
    number_of_items: int
    size_bytes: int
    tar_md5: str
    first_item: str
    last_item: str
