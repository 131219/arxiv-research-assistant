from pydantic import BaseModel


class Settings(BaseModel):
    aws_region: str = "us-west-2"
    source_bucket: str = "arxiv"
    destination_bucket: str
    processor_version: str = "0.1.0"
