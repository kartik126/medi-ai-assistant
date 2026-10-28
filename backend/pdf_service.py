from dataclasses import dataclass
from pathlib import Path
import pymupdf
from backend.chunking import normalize_page
from backend.errors import AppError


@dataclass
class Page:
    page_number: int
    text: str
    warning: str | None


def page_text(page):
    """Keep an existing column-major text stream when its geometry confirms it.

    Spatial sorting can stitch unrelated columns into individual lines. Only
    prefer native order when narrow blocks move right and restart higher up;
    ordinary pages retain the spatial-sort behavior. This is not table parsing.
    """
    blocks = [b for b in page.get_text('blocks', sort=False)
              if b[6] == 0 and b[4].strip()]
    width = page.rect.width
    column_major = any(
        a[2] - a[0] < width * .45 and b[2] - b[0] < width * .45
        and b[0] - a[0] > width * .18 and a[1] - b[1] > 40
        for a, b in zip(blocks, blocks[1:]))
    return page.get_text('text', sort=not column_major)


def extract_pdf(content: bytes, filename: str, max_pages: int):
    if Path(filename).suffix.lower() != ".pdf" or not content.startswith(b"%PDF-"):
        raise AppError("unsupported_file", "Upload a valid PDF file with a .pdf extension.")
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise AppError("corrupt_pdf", "The PDF could not be opened. Export a new PDF and retry.") from exc
    with doc:
        if doc.needs_pass or doc.is_encrypted:
            raise AppError("encrypted_pdf", "Password-protected PDFs are unsupported. Upload an unlocked copy.")
        if doc.page_count > max_pages:
            raise AppError("page_limit", f"This upload exceeds the remaining {max_pages} physical pages.", 413)
        pages = []
        try:
            for i, page in enumerate(doc):
                text = normalize_page(page_text(page))
                meaningful = any(c.isalnum() for c in text)
                warning = None if meaningful else ("ocr_required" if page.get_images() else "empty")
                if meaningful and len(text) < 40:
                    warning = "low_text_review"
                pages.append(Page(i + 1, text, warning))
        except Exception as exc:
            raise AppError("extraction_failed", "PDF text extraction failed. Export a new PDF and retry.") from exc
    if not any(any(c.isalnum() for c in p.text) for p in pages):
        raise AppError("no_text", "No extractable text. Scanned/image-only PDFs require OCR, which is unsupported.")
    return pages
