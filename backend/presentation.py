"""Display-only cleanup; never decode arbitrary escapes in scientific notation."""
import re


def clean_text(text):
    # Decode only formatting escapes, never unicode_escape/backslash escapes
    # generally: scientific names, HGVS strings and numeric punctuation survive.
    text = re.sub(r'\\(?:r\\n|[nrt]|u00a0|u008[38]|x8[38])', ' ', text, flags=re.I)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def clean_answer(text):
    # Keep deliberate answer paragraphs while cleaning their contents.
    return '\n\n'.join(clean_text(p) for p in re.split(r'\n\s*\n', text) if clean_text(p))
