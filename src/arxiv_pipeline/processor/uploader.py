import json
from pathlib import Path
from typing import Any
from botocore.exceptions import ClientError


def s3_object_exists(
    s3_client: Any,
    bucket: str,
    key: str,
) -> bool:
    """
    Check whether an S3 object already exists.
    """
    try:
        s3_client.head_object(
            Bucket=bucket,
            Key=key,
        )
        return True

    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")

        if error_code in {
            "404",
            "NoSuchKey",
            "NotFound",
        }:
            return False

        raise


def upload_file(
    s3_client: Any,
    local_path: Path,
    destination_bucket: str,
    destination_key: str,
    content_type: str,
) -> None:
    """
    Upload one local file to S3.
    """
    if not local_path.exists():
        raise FileNotFoundError(f"Local file does not exist: {local_path}")

    print(f"Uploading file to " f"s3://{destination_bucket}/{destination_key}")

    s3_client.upload_file(
        Filename=str(local_path),
        Bucket=destination_bucket,
        Key=destination_key,
        ExtraArgs={
            "ContentType": content_type,
        },
    )

    print(f"Upload successful: " f"s3://{destination_bucket}/{destination_key}")


def upload_markdown(
    s3_client: Any,
    local_path: Path,
    destination_bucket: str,
    destination_key: str,
) -> None:
    """
    Upload one Markdown file to the output S3 bucket.
    """
    upload_file(
        s3_client=s3_client,
        local_path=local_path,
        destination_bucket=destination_bucket,
        destination_key=destination_key,
        content_type="text/markdown",
    )


def upload_json(
    s3_client: Any,
    data: dict[str, Any],
    destination_bucket: str,
    destination_key: str,
) -> None:
    """
    Upload a Python dictionary as a JSON S3 object.
    """
    print(f"Uploading JSON to " f"s3://{destination_bucket}/{destination_key}")

    s3_client.put_object(
        Bucket=destination_bucket,
        Key=destination_key,
        Body=json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8"),
        ContentType="application/json",
    )

    print(
        f"JSON uploaded successfully: " f"s3://{destination_bucket}/{destination_key}"
    )


def upload_json_lines(
    s3_client: Any,
    records: list[dict[str, Any]],
    destination_bucket: str,
    destination_key: str,
) -> None:
    """
    Upload a list of dictionaries as a JSON Lines S3 object.
    """
    body = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)

    if body:
        body += "\n"

    print(f"Uploading JSONL to " f"s3://{destination_bucket}/{destination_key}")

    s3_client.put_object(
        Bucket=destination_bucket,
        Key=destination_key,
        Body=body.encode("utf-8"),
        ContentType="application/x-ndjson",
    )

    print(
        f"JSONL uploaded successfully: " f"s3://{destination_bucket}/{destination_key}"
    )
