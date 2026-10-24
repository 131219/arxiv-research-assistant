from unittest.mock import MagicMock

from arxiv_pipeline.api.rate_limit import DynamoDBResearchRateLimiter


def test_dynamodb_rate_limiter_allows_request_below_limit():
    table = MagicMock()

    limiter = DynamoDBResearchRateLimiter(
        table=table,
        max_requests=10,
        window_seconds=60,
        clock=lambda: 120,
    )

    allowed = limiter.allow(user_id="user-123")

    assert allowed is True

    table.update_item.assert_called_once_with(
        Key={
            "rate_key": "research:user-123:120",
        },
        UpdateExpression=(
            "ADD request_count :one "
            "SET expires_at = if_not_exists(expires_at, :expires_at)"
        ),
        ConditionExpression=(
            "attribute_not_exists(request_count) "
            "OR request_count < :max_requests"
        ),
        ExpressionAttributeValues={
            ":one": 1,
            ":max_requests": 10,
            ":expires_at": 240,
        },
    )


def test_dynamodb_rate_limiter_denies_request_when_limit_is_exceeded():
    from botocore.exceptions import ClientError

    table = MagicMock()

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "ConditionalCheckFailedException",
                "Message": "The conditional request failed",
            }
        },
        "UpdateItem",
    )

    limiter = DynamoDBResearchRateLimiter(
        table=table,
        max_requests=10,
        window_seconds=60,
        clock=lambda: 120,
    )

    allowed = limiter.allow(user_id="user-123")

    assert allowed is False


def test_dynamodb_rate_limiter_propagates_unexpected_client_error():
    from botocore.exceptions import ClientError
    import pytest

    table = MagicMock()

    table.update_item.side_effect = ClientError(
        {
            "Error": {
                "Code": "ProvisionedThroughputExceededException",
                "Message": "Throughput exceeded",
            }
        },
        "UpdateItem",
    )

    limiter = DynamoDBResearchRateLimiter(
        table=table,
        max_requests=10,
        window_seconds=60,
        clock=lambda: 120,
    )

    with pytest.raises(ClientError):
        limiter.allow(user_id="user-123")
