"""Page-bounded chunks; offsets refer to the stored normalized page text."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TextChunk:
    text: str
    start_char: int
    end_char: int


def normalize_page(text):
    # Preserve newlines and numeric punctuation; collapse horizontal whitespace only.
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")).strip()


def _split_window(text, target, overlap, maximum):
    if not 0 <= overlap < target <= maximum:
        raise ValueError("Require 0 <= overlap < target <= maximum")
    chunks, start = [], 0
    while start < len(text):
        end = min(start + target, len(text))
        if end < len(text):
            # Prefer paragraph/sentence/line boundaries, falling back to a hard limit.
            window = text[start:end]
            boundaries = list(re.finditer(r"\n\n|(?<=[.!?])\s+|\n", window))
            valid = [m.end() for m in boundaries if m.end() >= target // 2]
            if valid:
                end = start + valid[-1]
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            chunks.append(TextChunk(text[left:right], left, right))
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def chunk_page(text, target=1500, overlap=200, maximum=2000):
    """Pack paragraphs, keeping explicit section headings with their content.

    Only recognize Markdown or PDF checkbox headings, not arbitrary short
    lines (which may be wrapped prose). Long sections use bounded overlapping
    windows. Every chunk remains an exact page substring; no invented headings.
    """
    if not 0 <= overlap < target <= maximum:
        raise ValueError('Require 0 <= overlap < target <= maximum')
    headings = [m.start() for m in re.finditer(
        r'(?m)^(?:#{1,6}\s+[^\n]+|[\x88\u2610\u25a1]\s*[^\n]+)$', text)]
    sections = sorted({0, *headings, len(text)})
    chunks = []
    for left, right in zip(sections, sections[1:]):
        # Paragraphs are kept intact if they fit. Wrapped PDF lines stay together.
        boundaries = [left] + [left + m.end() for m in re.finditer(r'\n\s*\n', text[left:right])] + [right]
        start = left
        end = left
        spans = []
        for a, b in zip(boundaries, boundaries[1:]):
            if b - start > target and end > start:
                spans.append((start, end))
                start = a
            end = b
        if end > start:
            spans.append((start, end))
        # Keep a short heading paragraph attached to its following paragraph.
        if len(spans) > 1 and spans[0][1] - spans[0][0] < target // 4:
            a, b = spans[0][0], spans[1][1]
            spans[:2] = [(a, b)]  # Bounded windows split a long body below.
        for a, b in spans:
            for chunk in _split_window(text[a:b], target, overlap, maximum):
                chunks.append(TextChunk(chunk.text, a + chunk.start_char, a + chunk.end_char))
    return chunks
