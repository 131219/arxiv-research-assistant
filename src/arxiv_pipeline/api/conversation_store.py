from collections.abc import Callable
from typing import Any


class DynamoDBConversationStore:
    def __init__(
        self,
        table: Any,
        id_factory: Callable[[], str],
        clock: Callable[[], int],
    ) -> None:
        self._table = table
        self._id_factory = id_factory
        self._clock = clock

    def create_conversation(
        self,
        user_id: str,
    ) -> str:
        conversation_id = self._id_factory()
        now = self._clock()

        self._table.put_item(
            Item={
                "pk": f"USER#{user_id}",
                "sk": f"CONV#{conversation_id}",
                "entity_type": "conversation",
                "conversation_id": conversation_id,
                "user_id": user_id,
                "created_at": now,
                "updated_at": now,
            },
            ConditionExpression=(
                "attribute_not_exists(pk) AND attribute_not_exists(sk)"
            ),
        )

        return conversation_id

    def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        citations: list[dict[str, str]],
    ) -> str:
        message_id = self._id_factory()
        now = self._clock()

        self._table.put_item(
            Item={
                "pk": f"USER#{user_id}",
                "sk": (
                    f"CONV#{conversation_id}"
                    f"#MSG#{now}"
                    f"#{message_id}"
                ),
                "entity_type": "message",
                "conversation_id": conversation_id,
                "message_id": message_id,
                "role": role,
                "content": content,
                "citations": citations,
                "created_at": now,
            }
        )

        return message_id

    def conversation_exists(
        self,
        user_id: str,
        conversation_id: str,
    ) -> bool:
        response = self._table.get_item(
            Key={
                "pk": f"USER#{user_id}",
                "sk": f"CONV#{conversation_id}",
            },
            ConsistentRead=True,
        )

        item = response.get("Item")

        return bool(
            item
            and item.get("entity_type") == "conversation"
            and item.get("conversation_id") == conversation_id
            and item.get("user_id") == user_id
        )

    def get_messages(
        self,
        user_id: str,
        conversation_id: str,
        limit: int,
    ) -> list[dict[str, object]]:
        response = self._table.query(
            KeyConditionExpression=(
                "pk = :pk AND begins_with(sk, :sk_prefix)"
            ),
            ExpressionAttributeValues={
                ":pk": f"USER#{user_id}",
                ":sk_prefix": f"CONV#{conversation_id}#MSG#",
            },
            ScanIndexForward=False,
            Limit=limit,
        )

        return list(reversed(response.get("Items", [])))
