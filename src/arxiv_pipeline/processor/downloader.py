from pathlib import Path

import boto3
from botocore.client import BaseClient


def create_s3_client(region_name: str = "us-east-1") -> BaseClient:
    """
    Create and return an S3 client.

    Boto3 will use the AWS profile currently selected in the terminal,
    such as AWS_PROFILE=arxiv-pipeline.
    """
    return boto3.client("s3", region_name=region_name)


def download_archive(
    s3_client: BaseClient,
    source_bucket: str,
    source_key: str,
    destination_path: Path,
    request_payer: str = "requester",
) -> Path:
    """
    Download one TAR archive from S3 and save it locally.
    """
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    if destination_path.exists():
        print(f"Archive already exists: {destination_path}")
        print("Skipping download.")
        return destination_path

    print(f"Downloading s3://{source_bucket}/{source_key}")
    print(f"Saving to {destination_path}")

    response = s3_client.get_object(
        Bucket=source_bucket,
        Key=source_key,
        RequestPayer=request_payer,
    )

    with destination_path.open("wb") as archive_file:
        for chunk in iter(lambda: response["Body"].read(8 * 1024 * 1024), b""):
            archive_file.write(chunk)

    print("Download completed.")
    return destination_path
