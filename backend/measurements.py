"""Recognize lesion-size requests and exact dimensional evidence, not diagnoses."""
import re

SIZE = re.compile(
    r'\b\d+(?:\.\d+)?(?:\s*[×xX*]\s*\d+(?:\.\d+)?){0,2}'
    r'\s*[-–‑]?\s*(?:cm|mm|centimeters?|millimeters?)\b', re.I)
# PostgreSQL's POSIX regex: passed as data, never interpolated into SQL.
SIZE_SQL = r'[0-9][[:space:]‑–-]*(cm|mm|centimeters?|millimeters?)\M'


def size_question(question):
    subject = re.search(r'\b(?:mass|lesion|tumou?r|nodule)s?\b', question, re.I)
    size = re.search(r'\b(?:measurements?|dimensions?|sizes?|diameters?|how (?:large|big))\b', question, re.I)
    weight = re.search(r'\b(?:body|weight|weigh|calibration|card)\b', question, re.I)
    return bool(subject and size and not weight)


def size_history_question(question):
    return size_question(question) and bool(re.search(
        r'\b(?:different|all|various|over time|throughout|timeline)\b', question, re.I))


def dimension_keys(text):
    """Keep ordered dimensions, precision and units; normalize typography only."""
    return {(tuple(re.findall(r'\d+(?:\.\d+)?', m[0])),
             'mm' if re.search(r'mm|millimeter', m[0], re.I) else 'cm')
            for m in SIZE.finditer(text)}


def size_display(text):
    """Render observed dimensions and explicit context as precise field values.

    Like table-cell projection, this is extraction, not a generated explanation.
    Numbers, ranges and relative times come from the quotation, never defaults.
    """
    matches = [m for m in SIZE.finditer(text)
               if not re.match(r'\s*(?:wide\s+)?(?:margins?|incisions?|scars?)\b', text[m.end():], re.I)
               and not re.search(r'\b(?:margin|incision|scar)\b[^.;]{0,20}$', text[:m.start()], re.I)]
    if not matches:
        return None
    measurement = text[matches[0].start():matches[-1].end()]
    measurement = re.sub(r'(?<=\d)[-–‑](?=(?:cm|mm)\b)', ' ', measurement)
    before = text[:matches[0].start()]
    qualifier = re.search(r'\b(approximately|about|around|roughly)\s*$', before, re.I)
    if qualifier:
        measurement = qualifier[1].lower() + ' ' + measurement
    label = 'Reported size'
    for pattern, name in [
        (r'\bintraoperativ\w*\b','Intraoperative measurement'),
        (r'\bPET/CT\b','PET/CT'), (r'\bMRI\b','MRI'),
        (r'\bultrasound\b','Ultrasound'),
        (r'\bon examination\b','Examination'),
        (r'\bclinically\b','Clinical assessment'),
        (r'\babstract\b','Abstract'),
    ]:
        if re.search(pattern,text,re.I):
            label = name
            break
    time = re.search(
        r'\b(?:(?:At|Approximately|About|Around)\s+)?\d+(?:\.\d+)?\s+(?:days?|weeks?|months?|years?)'
        r'\s+(?:after|before|following|since)\s+(?:(?:his|her|their|the)\s+)?'
        r'(?:initial\s+)?(?:presentation|diagnosis|excision|surgery|treatment|admission|biopsy)\b',text,re.I)
    if time:
        label += ' (' + time[0] + ')'
    return label + ': ' + measurement + '.'


def size_excerpt(text):
    """Exclude margins/scars/etc. unless a lesion's own size is also stated."""
    if not SIZE.search(text) or not re.search(r'\b(?:mass|lesion|tumou?r|nodule)s?\b', text, re.I):
        return False
    if re.search(r'\b(?:margins?|incisions?|scars?)\b', text, re.I):
        return bool(re.search(r'\b(?:mass|lesion|tumou?r|nodule)\b.{0,50}\b(?:measur\w*|siz\w*|diameter)\b', text, re.I))
    return True


def timed_size_units(source):
    """Contiguous sentence windows retain an immediately preceding time anchor."""
    from backend.evidence import Unit
    from backend.citations import whitespace
    text = whitespace(source['text'])
    sentences = list(re.finditer(r'.+?(?:[.!?](?=\s|$)|\Z)', text, re.S))
    for i, match in enumerate(sentences):
        value = match[0].strip()
        if not size_excerpt(value):
            continue
        if i:
            previous = sentences[i-1][0].strip()
            timing = re.search(r'\b(?:\d+(?:\.\d+)?\s+(?:days?|weeks?|months?|years?)|preoperative|postoperative|presentation|admission|surgery|excision)\b', previous, re.I)
            # Do not attach another measurement's timing to this observation.
            if timing and not SIZE.search(previous):
                window = text[sentences[i-1].start():match.end()].strip()
                if len(window) <= 600:
                    value = window
        if len(value) <= 600:
            display = size_display(value)
            if display:
                yield Unit(value, source, kind='field', display=display)
