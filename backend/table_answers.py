"""Conservative text-coordinate table projection, without vision or free claims.

Only aligned, single-line headers and their adjacent data rows are supported.
Values are copied verbatim from the column, with a source-substring quotation.
No gene, variant, numeric answer or physical page is special-cased.
"""
import re
import pymupdf
from backend.citations import whitespace
from backend.evidence import Unit
from backend.presentation import clean_text

# Terminology expansion, not a value lookup. Other column labels stay literal.
LABELS = {'vaf': 'variant allele frequency'}
SUBJECT_HEADERS = {'gene', 'marker', 'analyte', 'test'}


def tokens(text):
    return set(re.findall(r'[a-z0-9]+', text.lower()))


def lines(words):
    result = []
    for word in sorted(words, key=lambda w: (w[1], w[0])):
        # Small baseline jitter is common between different fonts in one row.
        row = next((r for r in reversed(result[-3:]) if abs(r[0][1]-word[1]) <= 2), None)
        if row is None:
            result.append([word])
        else:
            row.append(word)
    return [sorted(row, key=lambda w: w[0]) for row in result]


def headers(row):
    groups = []
    for word in row:
        if not groups or word[0]-groups[-1][-1][2] > 10:
            groups.append([word])
        else:
            groups[-1].append(word)
    return [(' '.join(w[4] for w in g), (g[0][0]+g[-1][2])/2) for g in groups]


def project_page(question, page, sources, part=0):
    """Return requested field/value facts only when row/column scope is clear."""
    rows = lines(page.get_text('words', sort=False))
    query = tokens(question)
    facts = []
    for i, row in enumerate(rows[:-1]):
        columns = headers(row)
        if len(columns) < 3 or columns[0][0].lower() not in SUBJECT_HEADERS:
            continue
        if any(not re.fullmatch(r'[A-Za-z /-]+', label) for label, _ in columns):
            continue
        requested = [(j, LABELS.get(label.lower(), label.lower()))
                     for j, (label, _) in enumerate(columns[1:], 1)
                     if tokens(LABELS.get(label.lower(), label)) <= query
                     or tokens(label) <= query]
        if not requested:
            continue
        height = max(w[3]-w[1] for w in row)
        first_boundary = (columns[0][1]+columns[1][1])/2
        # Ignore isolated watermark words interleaved by vertical ordering.
        data = next((r for r in rows[i+1:i+6]
                     if 0 < r[0][1]-row[0][1] <= height*3
                     and r[0][0] < first_boundary and len(r) >= len(columns)), None)
        if data is None:
            continue
        centers = [center for _, center in columns]
        boundaries = [(a+b)/2 for a, b in zip(centers, centers[1:])]
        cells = [[] for _ in columns]
        ambiguous = False
        for word in data:
            center = (word[0]+word[2])/2
            index = sum(center > b for b in boundaries)
            # A word crossing a column boundary cannot establish a cell.
            relevant = {0} | {j for j, _ in requested} | {j-1 for j, _ in requested}
            if any(k in relevant and word[0]+1 < b < word[2]-1 for k, b in enumerate(boundaries)):
                ambiguous = True
                break
            cells[index].append(word[4])
        if ambiguous:
            continue
        values = [' '.join(cell) for cell in cells]
        subject = values[0]
        if not subject or not re.search(r'(?<![\w-])'+re.escape(subject)+r'(?![\w-])', question, re.I):
            continue
        header_text = ' '.join(w[4] for w in row)
        row_text = ' '.join(w[4] for w in data)
        # The coordinate interpretation must have exact textual provenance in
        # the already retrieved chunk. Never fabricate a supporting quotation.
        owner = next((s for s in sources if whitespace(header_text+' '+row_text) in whitespace(s['text'])), None)
        quote = header_text+'\n'+row_text
        if owner is None:
            owner = next((s for s in sources if whitespace(row_text) in whitespace(s['text'])), None)
            quote = row_text
            if owner is not None:
                normalized = whitespace(owner['text'])
                end = normalized.find(whitespace(row_text))
                start = normalized.rfind(whitespace(header_text), 0, end)
                if start >= 0 and end + len(whitespace(row_text)) - start <= 600:
                    # Keep intervening watermark/wrapped text as evidence,
                    # rather than concatenating noncontiguous source spans.
                    quote = normalized[start:end+len(whitespace(row_text))]
        if owner is None or len(quote) > 600:
            continue
        for j, field in requested:
            value = values[j]
            if not value or len(value) > 100:
                continue
            qualifier = next((values[k] for k, (label, _) in enumerate(columns)
                              if label.lower() == 'alteration' and values[k]
                              and tokens(values[k]) <= query), '')
            display = clean_text(f'{subject} {qualifier} {field}: {value}.')
            unit = Unit(quote, owner, header_text, 'field', part=part, parts={part}, display=display)
            facts.append(unit)
    # Do not silently collapse conflicting/multiple variants into one gene fact.
    if len({f.display for f in facts}) != len(facts):
        facts = list({(str(f.source['document_id']), f.display): f for f in facts}.values())
    return facts


def field_units(store, sid, question, sources, part=0):
    result = []
    grouped = {}
    for source in sources:
        grouped.setdefault(str(source['document_id']), {}).setdefault(source['page_number'], []).append(source)
    for did, pages in grouped.items():
        path = store.directory(sid) / f'{did}.pdf'
        try:
            with pymupdf.open(path) as pdf:
                for number, rows in pages.items():
                    result.extend(project_page(question, pdf[number-1], rows, part))
        except (OSError, RuntimeError):
            continue  # Source text remains available; no invented cell values.
    return result
