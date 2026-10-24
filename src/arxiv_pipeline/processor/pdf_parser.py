from pathlib import Path

import fitz


def extract_pdf_text(pdf_path: Path) -> str:
    """
    Extract text from every page of one PDF.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    page_texts: list[str] = []

    with fitz.open(pdf_path) as document:
        print(f"Reading PDF: {pdf_path}")
        print(f"Total pages: {document.page_count}")

        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text")

            if text.strip():
                page_texts.append(text)

            print(f"Processed page {page_number}/{document.page_count}")

    complete_text = "\n\n".join(page_texts)

    print(f"Extracted {len(complete_text)} characters.")
    return complete_text
