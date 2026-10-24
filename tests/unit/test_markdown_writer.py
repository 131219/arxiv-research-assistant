from pathlib import Path

from arxiv_pipeline.processor.markdown_writer import (
    sanitize_markdown,
    save_markdown,
)


def test_sanitize_markdown_removes_null_bytes() -> None:
    text = "hello\x00world"

    result = sanitize_markdown(text)

    assert result == "helloworld"
    assert "\x00" not in result


def test_sanitize_markdown_removes_unsafe_control_characters() -> None:
    text = "before\x01middle\x07after"

    result = sanitize_markdown(text)

    assert result == "beforemiddleafter"


def test_sanitize_markdown_converts_form_feed_to_newline() -> None:
    text = "page one\fpage two"

    result = sanitize_markdown(text)

    assert result == "page one\npage two"


def test_sanitize_markdown_preserves_tabs_newlines_and_unicode() -> None:
    text = "Title\nColumn\tValue\nPhysics–informed café"

    result = sanitize_markdown(text)

    assert result == text


def test_save_markdown_writes_clean_utf8_file(tmp_path: Path) -> None:
    output_path = tmp_path / "paper.md"

    saved_path = save_markdown(
        text="first page\x00\fsecond page",
        output_path=output_path,
        title="2606.01597",
    )

    content = saved_path.read_text(encoding="utf-8")
    raw_bytes = saved_path.read_bytes()

    assert saved_path == output_path
    assert content == "# 2606.01597\n\nfirst page\nsecond page"
    assert b"\x00" not in raw_bytes
    assert raw_bytes.decode("utf-8") == content
