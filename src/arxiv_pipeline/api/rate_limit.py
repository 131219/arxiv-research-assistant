from collections.abc import Callable
from typing import Protocol

from botocore.exceptions import ClientError


class ResearchRateLimiter(Protocol):
    def allow(self, user_id: str) -> bool: ...


class AllowAllResearchRateLimiter:
    def allow(self, user_id: str) -> bool:
        return True


class DynamoDBResearchRateLimiter:
    def __init__(
        self,
        table,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], int],
    ) -> None:
        self._table = table
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._clock = clock

    def allow(self, user_id: str) -> bool:
        now = int(self._clock())
        window_start = (
            now // self._window_seconds
        ) * self._window_seconds

        rate_key = f"research:{user_id}:{window_start}"
        expires_at = window_start + (self._window_seconds * 2)

        try:
            self._table.update_item(
                Key={
                    "rate_key": rate_key,
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
                    ":max_requests": self._max_requests,
                    ":expires_at": expires_at,
                },
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")

            if error_code == "ConditionalCheckFailedException":
                return False

            raise

        return True
