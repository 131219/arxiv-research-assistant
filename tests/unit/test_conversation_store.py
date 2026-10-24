from unittest.mock import MagicMock

from arxiv_pipeline.api.conversation_store import DynamoDBConversationStore


def test_create_conversation_writes_user_scoped_metadata_item():
    table = MagicMock()

    store = DynamoDBConversationStore(
        table=table,
        id_factory=lambda: "conv-123",
        clock=lambda: 1728080000,
    )

    conversation_id = store.create_conversation(
        user_id="user-123",
    )

    assert conversation_id == "conv-123"

    table.put_item.assert_called_once_with(
        Item={
            "pk": "USER#user-123",
            "sk": "CONV#conv-123",
            "entity_type": "conversation",
            "conversation_id": "conv-123",
            "user_id": "user-123",
            "created_at": 1728080000,
            "updated_at": 1728080000,
        },
        ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
    )


def test_add_message_writes_message_under_user_conversation():
    table = MagicMock()

    store = DynamoDBConversationStore(
        table=table,
        id_factory=lambda: "msg-001",
        clock=lambda: 1728080000,
    )

    message_id = store.add_message(
        user_id="user-123",
        conversation_id="conv-123",
        role="user",
        content="Which approach works best for long-context inference?",
        citations=[],
    )

    assert message_id == "msg-001"

    table.put_item.assert_called_once_with(
        Item={
            "pk": "USER#user-123",
            "sk": "CONV#conv-123#MSG#1728080000#msg-001",
            "entity_type": "message",
            "conversation_id": "conv-123",
            "message_id": "msg-001",
            "role": "user",
            "content": (
                "Which approach works best for long-context inference?"
            ),
            "citations": [],
            "created_at": 1728080000,
        }
    )


def test_get_messages_returns_conversation_messages_in_order():
    table = MagicMock()

    table.query.return_value = {
        "Items": [
            {
                "pk": "USER#user-123",
                "sk": "CONV#conv-123#MSG#1728080001#msg-002",
                "entity_type": "message",
                "conversation_id": "conv-123",
                "message_id": "msg-002",
                "role": "assistant",
                "content": "The retrieved evidence suggests...",
                "citations": [
                    {
                        "paper_id": "2606.03928",
                        "arxiv_url": "https://arxiv.org/abs/2606.03928",
                        "passage": "Relevant passage.",
                    }
                ],
                "created_at": 1728080001,
            },
            {
                "pk": "USER#user-123",
                "sk": "CONV#conv-123#MSG#1728080000#msg-001",
                "entity_type": "message",
                "conversation_id": "conv-123",
                "message_id": "msg-001",
                "role": "user",
                "content": "Which method works best?",
                "citations": [],
                "created_at": 1728080000,
            },
        ]
    }

    store = DynamoDBConversationStore(
        table=table,
        id_factory=lambda: "unused",
        clock=lambda: 1728080000,
    )

    messages = store.get_messages(
        user_id="user-123",
        conversation_id="conv-123",
        limit=20,
    )

    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
    ]
    assert messages[1]["citations"][0]["paper_id"] == "2606.03928"

    table.query.assert_called_once()


def test_conversation_exists_checks_user_scoped_metadata_item():
    table = MagicMock()

    table.get_item.return_value = {
        "Item": {
            "pk": "USER#user-123",
            "sk": "CONV#conv-123",
            "entity_type": "conversation",
            "conversation_id": "conv-123",
            "user_id": "user-123",
        }
    }

    store = DynamoDBConversationStore(
        table=table,
        id_factory=lambda: "unused",
        clock=lambda: 1728080000,
    )

    assert store.conversation_exists(
        user_id="user-123",
        conversation_id="conv-123",
    )

    table.get_item.assert_called_once_with(
        Key={
            "pk": "USER#user-123",
            "sk": "CONV#conv-123",
        },
        ConsistentRead=True,
    )


def test_get_messages_fetches_newest_messages_and_returns_chronological_order():
    table = MagicMock()

    # DynamoDB returns newest first when ScanIndexForward=False.
    table.query.return_value = {
        "Items": [
            {
                "pk": "USER#user-123",
                "sk": "CONV#conv-123#MSG#1728080021#msg-022",
                "entity_type": "message",
                "conversation_id": "conv-123",
                "message_id": "msg-022",
                "role": "assistant",
                "content": "Newest assistant response.",
                "citations": [],
                "created_at": 1728080021,
            },
            {
                "pk": "USER#user-123",
                "sk": "CONV#conv-123#MSG#1728080020#msg-021",
                "entity_type": "message",
                "conversation_id": "conv-123",
                "message_id": "msg-021",
                "role": "user",
                "content": "Newest user question.",
                "citations": [],
                "created_at": 1728080020,
            },
        ]
    }

    store = DynamoDBConversationStore(
        table=table,
        id_factory=lambda: "unused",
        clock=lambda: 1728080000,
    )

    messages = store.get_messages(
        user_id="user-123",
        conversation_id="conv-123",
        limit=20,
    )

    # Callers should still receive history oldest-to-newest.
    assert [message["message_id"] for message in messages] == [
        "msg-021",
        "msg-022",
    ]

    table.query.assert_called_once_with(
        KeyConditionExpression=(
            "pk = :pk AND begins_with(sk, :sk_prefix)"
        ),
        ExpressionAttributeValues={
            ":pk": "USER#user-123",
            ":sk_prefix": "CONV#conv-123#MSG#",
        },
        ScanIndexForward=False,
        Limit=20,
    )
