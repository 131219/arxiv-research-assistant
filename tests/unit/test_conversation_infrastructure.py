from pathlib import Path


def test_state_stack_defines_conversation_table_and_outputs():
    template = Path(
        "infrastructure/cloudformation/templates/state.yaml"
    ).read_text()

    assert "ConversationTable:" in template
    assert 'TableName: !Sub "${ProjectName}-conversations-${Environment}"' in template

    assert "- AttributeName: pk" in template
    assert "- AttributeName: sk" in template
    assert "ConversationTableName:" in template
    assert "ConversationTableArn:" in template

    assert (
        'Name: !Sub "${ProjectName}-${Environment}-conversation-table-name"'
        in template
    )
    assert (
        'Name: !Sub "${ProjectName}-${Environment}-conversation-table-arn"'
        in template
    )
