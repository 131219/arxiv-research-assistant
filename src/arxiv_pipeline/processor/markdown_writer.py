from pathlib import Path
import unicodedata


_ALLOWED_CONTROL_CHARACTERS = {"\n", "\r", "\t"}


def sanitize_markdown(text: str) -> str:
    """
    Remove unsafe control characters from extracted PDF text.

    PDF extraction can introduce null bytes and other control characters.
    Those characters may cause Bedrock to detect an otherwise valid Markdown
    file as application/octet-stream.

    Form-feed characters are converted to newlines because they commonly
    represent PDF page boundaries.
    """
    cleaned_characters: list[str] = []

    for character in text:
        if character == "\f":
            cleaned_characters.append("\n")
        elif character in _ALLOWED_CONTROL_CHARACTERS:
            cleaned_characters.append(character)
        elif unicodedata.category(character) == "Cc":
            continue
        else:
            cleaned_characters.append(character)

    return "".join(cleaned_characters)


def save_markdown(
    text: str,
    output_path: Path,
    title: str | None = None,
) -> Path:
    """
    Save extracted PDF text as a sanitized UTF-8 Markdown file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    markdown_parts: list[str] = []

    if title:
        markdown_parts.append(f"# {title}")

    markdown_parts.append(text.strip())

    markdown_content = "\n\n".join(markdown_parts)
    sanitized_content = sanitize_markdown(markdown_content)

    # Explicit validation before writing.
    sanitized_content.encode("utf-8")

    output_path.write_text(
        sanitized_content,
        encoding="utf-8",
        newline="\n",
    )

    print(f"Markdown saved: {output_path}")
    return output_path
