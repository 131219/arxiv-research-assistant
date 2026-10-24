from unittest.mock import MagicMock, patch

from arxiv_pipeline.api.main import get_conversation_store


def test_get_conversation_store_uses_configured_dynamodb_table(monkeypatch):
    get_conversation_store.cache_clear()

    monkeypatch.setenv(
        "CONVERSATION_TABLE_NAME",
        "arxiv-conversations-test",
    )

    with patch(
        "arxiv_pipeline.api.main.boto3.resource"
    ) as dynamodb_resource:
        dynamodb = MagicMock()
        table = MagicMock()

        dynamodb_resource.return_value = dynamodb
        dynamodb.Table.return_value = table

        store = get_conversation_store()

    dynamodb_resource.assert_called_once_with(
        "dynamodb",
        region_name="us-east-1",
    )
    dynamodb.Table.assert_called_once_with(
        "arxiv-conversations-test"
    )

    assert store._table is table

    get_conversation_store.cache_clear()
