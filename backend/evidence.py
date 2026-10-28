"""Source profiles and exact evidence units; no generated medical assertions."""
from dataclasses import dataclass, field
from collections import Counter
from difflib import get_close_matches
import math
import re
import pymupdf
from backend.citations import whitespace

STOP = set('a an the and or of for to in on from by with as at is are was were be been being it this that these those what which who how much many does do did can could should someone person according guide booklet document report plan summarize describe describes described say says stated state states provided selected supplied source sources each per about toward towards gradually work build up weekly daily goal target value amount first second both handbook handbooks fictional training example sample ask called current measured recorded patient my your filled named exact appears appear'.split())
GENERIC_TITLE = STOP | set('new type action way preventing clinical use not physical page revision laboratory service'.split())
ADMIN = re.compile(r'\b(?:birth\s*date|date of birth|age\s*:|patient\s*(?:name|id)|account information|order number|client order|ordering physician|lab director|clia|telephone|phone number|received:|reported:|collected|printed)', re.I)
BULLET = re.compile(r'^[\x83\u2022\u2713\u2714]\s*')
OPTION = re.compile(r'[_]{3,}|[\uf071\u2610\u25a1]')


def words(text):
    text = text.lower().replace('’', "'")
    # Possessive punctuation is not a content term ("patient's" -> patient,
    # never a spurious "s" match against unrelated disease names).
    text = re.sub(r"\b([a-z0-9]+)'s\b", r'\1', text)
    # Retrieval-only age anchor: quotations remain byte-for-byte source text.
    text = re.sub(r'\b\d{1,3}\s*[-–‑]?\s*years?\s*[-–‑]?\s*old\b',
                  lambda m: m[0] + ' age ', text)
    text = re.sub(r'(cd\d+)\+', r'\1 positive', text)
    text = text.replace('%', ' percent ')
    tokens = re.findall(r'[a-z][a-z0-9]*|\d+(?:\.\d+)?', text)
    normal = {'activities': 'activ', 'activity': 'activ', 'active': 'activ',
              'medications': 'medication', 'medicines': 'medication', 'medicine': 'medication',
              'drug': 'medication', 'drugs': 'medication', 'symptoms': 'symptom',
              'levels': 'level', 'goals': 'goal', 'minutes': 'minute', 'days': 'day',
              'dates': 'date', 'revisions': 'revision', 'intervals': 'interval',
              'cells': 'cell', 'percentages': 'percent', 'percentage': 'percent',
              'weeks': 'week', 'grams': 'g', 'milligrams': 'mg', 'mutations': 'mutation',
              'variants': 'variant', 'monocytes': 'monocyte', 'abilities': 'ability',
              'weekly': 'week', 'daily': 'day', 'aged': 'age',
              'located': 'location', 'involving': 'location'}
    return [normal.get(t, t) for t in tokens]


def terms(text):
    return set(words(text)) - STOP


def profile(document, text, metadata=None):
    metadata = metadata or {}
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    headline = next((line for line in lines if not re.search(r'SYNTHETIC|NOT FOR CLINICAL USE', line)), '')
    title = metadata.get('title') or headline
    title_text = ' '.join([document['filename'].rsplit('.', 1)[0], title, headline])
    aliases = set(words(title_text)) - GENERIC_TITLE
    aliases = {t for t in aliases if len(t) >= 4 and not t.isdigit()}
    author = metadata.get('author', '')
    # Metadata words are not independently treated as source names: "control"
    # in an institution name must not bind an experimental-control question.
    acronyms = re.findall(r'\b[A-Z]{3,8}\b', author)
    initials = ''.join(w[0] for w in re.findall(r'[A-Za-z]+', author) if w.lower() not in {'for', 'of', 'the', 'and'})
    if 3 <= len(initials) <= 8:
        acronyms += [initials[:n] for n in range(3, len(initials)+1)]
    aliases.update(a.lower() for a in acronyms)
    aliases.update(host.lower() for host in re.findall(r'\b([A-Za-z0-9-]+)\.(?:gov|edu)\b', text))
    record = bool(re.search(r'\breport status\b', text, re.I) and re.search(r'\bpatient\s*(?:id|name)\b', text, re.I))
    form = bool(re.search(r'\b(?:For|Patient(?: Name)?)\s*:', text, re.I) and re.search(r'Daily Medications|How much to take', text, re.I))
    return {**document, 'title': title, 'author': author, 'aliases': aliases,
            'kind': 'record' if record else ('form' if form else 'guidance'), 'profile_text': text}


def load_profiles(store, sid, documents):
    with store.db.connection() as conn:
        pages = conn.execute('SELECT document_id,page_number,text FROM pages WHERE session_id=%s AND page_number<=3 ORDER BY page_number', (sid,)).fetchall()
    texts = {}
    for page in pages:
        texts.setdefault(str(page['document_id']), []).append(page['text'])
    result = []
    for doc in documents:
        metadata = {}
        path = store.directory(sid) / f"{doc['document_id']}.pdf"
        try:
            with pymupdf.open(path) as pdf:
                metadata = pdf.metadata
        except (OSError, RuntimeError):
            pass  # Extracted text remains usable when an original is missing.
        result.append(profile(doc, '\n'.join(texts.get(str(doc['document_id']), [])), metadata))
    return result


def resolve_documents(question, profiles, selected):
    q = set(words(question))
    # Alias binding is used for explicit document references, not every topic.
    explicit = bool(re.search(r'\b(?:guide|booklet|document|report|plan|handbooks?|according)\b', question, re.I))
    references = [p for p in profiles if p['aliases'] & q] if explicit else []
    named_acronyms = re.findall(r"\b([A-Z]{3,8})(?:[’']s)?\s+(?:guide|booklet|report|plan)\b", question)
    if named_acronyms:
        named = {a.lower() for a in named_acronyms}
        references = [p for p in profiles if p['aliases'] & named]
        if not references or not named <= set().union(*(p['aliases'] for p in references)):
            return set(), True
    if not references and re.search(r'\bhandbooks?\b', question, re.I):
        references = [p for p in profiles if 'handbook' in p['title'].lower()]
    wanted = {str(p['document_id']) for p in references}
    available = {str(d) for d in selected}
    if wanted:
        return wanted & available, bool(wanted - available)
    return available, False


def request_kind(question):
    q = question.lower()
    if re.search(r'\b(?:confirm\w*|exact|identified)\b', q) and re.search(r'\b(?:variant|mutation|genotype)\b', q):
        return 'variant'
    if re.search(r'\b(?:medicine|medication|drug|insulin)s?\b', q) and re.search(r'\b(?:prescribed|prescription|dose|daily|filled|named)\b', q):
        return 'medication'
    if re.search(r'\b(?:patient|my)\b', q) and re.search(r'\bname\b', q):
        return 'identity'
    if re.search(r'\bpatient\b', q) and re.search(r'\b(?:currently|current|confirmed|diagnosed)\b', q):
        return 'state'
    if re.search(r'\b(?:patient|my)\b', q) and re.search(r'\b(?:measured|current|result|weight|a1c|measurement)\b', q):
        return 'measurement'
    return 'guidance'


def patient_data_available(kind, profiles, question=''):
    if kind == 'guidance':
        return True
    text = '\n'.join(p['profile_text'] for p in profiles)
    if kind == 'medication':
        # An actual filled label/narrative is required; choices and "recommend
        # testing" are not a medication record. No drug knowledge is inferred.
        explicit = re.search(r'(?im)^(?:daily medication|current medication|prescribed medication|medication)[ \t]*:[ \t]*[A-Za-z][^\n_]+\b(?:mg|mcg|g|puffs?|tablets?|daily|twice|once)\b', text)
        table = re.search(r'Daily Medications?\s+Medicine\s+How much to take\s+When to take it\s+(.*?)\s+Before exercise', text, re.I | re.S)
        populated = table and re.search(r'[A-Za-z].*\d+\s*(?:mg|mcg|g)\b.*\b(?:daily|once|twice|morning|night)\b', table[1], re.I | re.S)
        return bool(explicit or populated)
    if kind == 'identity':
        return bool(re.search(r'(?im)^(?:For|Patient Name)[ \t]*:[ \t]*[A-Za-z][^\n_:]+$', text))
    if kind == 'variant':
        return bool(re.search(r'\b(?:c\.\d+[ACGT]>[ACGT]|p\.[A-Z][a-z]{2}\d+|variant\s*:\s*\S+)', text))
    if kind == 'state':
        return bool(re.search(r'(?im)^(?:current (?:status|zone|diagnosis)|diagnosis)[ \t]*:[ \t]*[A-Za-z][^\n_]+', text))
    records = [p for p in profiles if p['kind'] == 'record']
    if not question:
        return bool(records)
    focus = terms(question) - set('result measurement measured record report patient current according lab normal actual'.split())
    focus -= set().union(*(p['aliases'] for p in profiles)) if profiles else set()
    return any(focus & terms(line) and re.search(r'\d', line)
               and not re.search(r'\b(?:normal|reference|example|threshold|range|control)\b', line, re.I)
               for p in records for line in p['profile_text'].splitlines())


@dataclass
class Unit:
    text: str
    source: dict
    context: str = ''
    kind: str = 'sentence'
    score: float = 0.0
    part: int = 0
    parts: set = field(default_factory=set)
    display: str | None = None


def units(source, include_admin=False):
    text = source['text']
    lines = text.splitlines(keepends=True)
    spans = []
    offset = 0
    def heading(line):
        tokens = re.findall(r'[A-Za-z]+', line)
        return (bool(tokens) and len(line) < 75 and not re.search(r'[.!?:]|\d', line)
                and not ADMIN.search(line) and sum(t[0].isupper() for t in tokens)/len(tokens) >= .6)
    prefix = source.get('page_text', '')[:source.get('start_char', 0)]
    inherited = [line.strip() for line in prefix.splitlines() if heading(line.strip())][-4:]
    parent = next((line for line in reversed(prefix.splitlines()) if re.fullmatch(r'[A-Z]+ ZONE', line)), '')
    section = ' '.join(inherited)
    for line in lines:
        clean = line.strip()
        if re.fullmatch(r'[A-Z]+ ZONE', clean):
            parent, section = clean, ''
        if clean.startswith(('\x88', '\u2610', '\u25a1')) and len(clean) < 100 and '_' not in clean:
            section = clean.lstrip('\x88\u2610\u25a1').strip()
        elif heading(clean):
            section = clean
        spans.append((offset, offset+len(line), parent + ' ' + section))
        offset += len(line)
    # Sentence units preserve contiguous source text; long/label-heavy segments
    # also have line/bullet alternatives below. No text is paraphrased here.
    for match in re.finditer(r'.+?(?:[.!?](?=\s|$)|\Z)', whitespace(text), re.S):
        value = match.group().strip()
        if 8 <= len(value) <= 600 and not OPTION.search(value) and (include_admin or not ADMIN.search(value)):
            yield Unit(value, source)
    for i, (start, end, context) in enumerate(spans):
        line = text[start:end].strip()
        if not line or (not include_admin and ADMIN.search(line)) or OPTION.search(line):
            continue
        bullet = bool(BULLET.match(line))
        stop = end
        # Rejoin wrapped bullet/prose lines, never crossing a new bullet, field,
        # heading, blank paragraph, or conditional preamble.
        for a, b, next_context in spans[i+1:]:
            next_line = text[a:b].strip()
            if not next_line or BULLET.match(next_line) or OPTION.search(next_line) or (not include_admin and ADMIN.search(next_line)):
                break
            if next_context != context or re.match(r'^(?:And,|Daily Medications|Medicine$|How much|When to|Before exercise|Peak flow:|My best)', next_line):
                break
            if re.match(r'^[A-Za-z][A-Za-z0-9 /-]{0,40}:', next_line):
                break
            if re.fullmatch(r'[A-Z][A-Z\s]+', next_line) or line.endswith(('.', '!', '?', ':')):
                break
            if len(text[start:b].strip()) > 450:
                break
            stop = b
            line = text[start:stop].strip()
            if line.endswith(('.', '!', '?')):
                break
        value = text[start:stop].strip()
        if 8 <= len(value) <= 450 and (bullet or len(spans[i][2].strip()) or re.search(r'\d', value) or re.match(r'^[A-Za-z][A-Za-z0-9 /-]{0,40}:\s*\S', value)):
            yield Unit(value, source, context.strip(), 'bullet' if bullet else 'line')
        # Simple label/value pairs are still intact in many inline tables.
        for match in re.finditer(r'[A-Za-z][A-Za-z -]{1,35}?\s+\d[\d,.]*\s*(?:mg/dL|g/dL|mmol/L|mg|mcg|g|mmHg|%)(?!\w)', text[start:end]):
            yield Unit(match.group().strip(), source, context.strip(), 'value')


def rank_units(question, sources, profiles, part=0):
    lookup = {str(p['document_id']): p for p in profiles}
    aliases = set().union(*(p['aliases'] for p in profiles)) if profiles else set()
    named_source = re.search(r'\b(?:guide|booklet|document|report|plan|handbooks?|according)\b', question, re.I)
    q = terms(question) - (aliases if named_source else set())
    q -= {'intensity', 'moderate'} if 'symptom' in q else set()
    include_admin = bool(re.search(r'\b(?:age|birth|name|identity|identifier|date)\b', question, re.I))
    all_units = list(unit for source in sources for unit in units(source, include_admin))
    vocabulary = set().union(*(terms(u.text+' '+u.context) for u in all_units)) if all_units else set()
    for term in list(q):
        if term not in vocabulary and len(term) >= 4:
            match = get_close_matches(term, vocabulary, n=1, cutoff=.82)
            if match:
                q.add(match[0])
    frequencies = Counter(term for unit in all_units for term in terms(unit.text+' '+unit.context))
    weights = {term: math.log(2 + len(all_units)/(1+frequencies[term])) for term in q}
    ranked = []
    zone = re.search(r'\b(\w+)[ -]zone\b', question, re.I)
    # "Mass" is also a lesion/topic noun. Its presence alone does not make a
    # question quantitative (e.g. "where was the mass located?").
    quantity = bool(re.search(r'\b(?:how much|amount|levels?|goals?|targets?|duration|number|mfi|percentage|intervals?|revision dates?)\b', question, re.I))
    if zone:
        q.update(terms(zone[0]))
        weights.update({t: math.log(2 + len(all_units)/(1+frequencies[t])) for t in terms(zone[0])})
    for unit in all_units:
        if request_kind(question) == 'measurement' and re.search(r'\b(?:reference|normal|example|threshold|range)\b', unit.text, re.I):
            continue
        body = terms(unit.text)
        context = terms(unit.context)
        # Wrapped prose lines can start/end halfway through neighboring
        # sentences and duplicate a complete sentence candidate. Retain line
        # alternatives for labels/tables/thresholds, not clipped paragraphs.
        endings = re.findall(r'[.!?](?:\s|$)', unit.text)
        if (unit.kind == 'line' and endings
                and (len(endings) > 1 or unit.text[0].islower() or unit.text[-1] not in '.!?')
                and not re.match(r'^[A-Za-z][A-Za-z0-9 /-]{0,40}:', unit.text)):
            continue
        if not q & body and not q & context:
            continue
        # Evidence that does not mention a requested meal cannot supply its
        # total. Dense tables remain excluded by the retriever.
        meals = q & {'breakfast', 'lunch', 'dinner'}
        if meals:
            # Flattened meal columns do not preserve a trustworthy subtotal
            # relation. Only an explicitly labelled textual total is eligible.
            day = re.search(r'\bday\s+\d+\b', question, re.I)
            if not meals <= body or not re.search(r'\btotal\s+(?:sodium|for)\b', unit.text, re.I) or (day and day[0].lower() not in whitespace(unit.text).lower()):
                continue
        if quantity and not re.search(r'(?:\d[\d,.]*\s*(?:%|percent|mg\b|mcg\b|g\b|grams?\b|minutes?\b|days?\b|weeks?\b)|\bMFI\s*=\s*\d|\b\d{4}-\d{2}-\d{2}\b)', unit.text, re.I):
            continue
        if quantity and 'activ' in q and not re.search(r'\d[\d,.]*\s*(?:minutes?|hours?)\b', unit.text, re.I):
            continue
        if re.search(r'\bsymptoms?\b', question, re.I) and zone:
            if unit.kind != 'bullet' or not re.search(r'\b' + re.escape(zone[1]) + r' ZONE\b', unit.context, re.I):
                continue
        if ADMIN.search(unit.text) and not re.search(r'\b(?:age|birth|name|identity|identifier|date)\b', question, re.I):
            continue
        # Topic headings are useful context but not standalone answers.
        if unit.kind == 'line' and not re.search(r'\d|[.!?:]', unit.text) and len(words(unit.text)) < 5:
            continue
        unit.score = sum(weights[t] for t in q & body) + .75 * sum(weights[t] for t in q & context)
        unit.score /= 1 + len(unit.text)/500
        if unit.kind == 'value':
            # Drop a preceding cell's trailing prose, retaining the exact
            # contiguous requested label/value substring.
            label_focus = q - {'level', 'day', 'week', 'goal', 'nutrient', 'studies', 'number', 'total'}
            labels = [m for m in re.finditer(r'[A-Za-z]+', unit.text) if m.group().lower() in label_focus]
            if labels:
                unit.text = unit.text[labels[-1].start():]
            else:
                continue
            if re.search(r'\b(?:of|either|or|and|by|for|to|at)\b', unit.text, re.I):
                continue
            unit.score *= 3
        if unit.kind == 'bullet':
            unit.score *= 1.15
        unit.part = part
        unit.parts = {part}
        ranked.append(unit)
    # Prefer precise excerpts to a containing paragraph with the same focus.
    ranked.sort(key=lambda u: (-u.score, len(u.text)))
    seen = set()
    result = []
    for unit in ranked:
        key = (str(unit.source['document_id']), unit.source['page_number'], whitespace(unit.text))
        if key not in seen:
            seen.add(key)
            result.append(unit)
    if result:
        # Relative lexical focus within already-retrieved evidence, not a
        # claimed probability of answerability or a universal cosine floor.
        floor = result[0].score * .45
        result = [u for u in result if u.score >= floor
                  or (u.kind == 'bullet' and
                      (len(terms(u.context) & q) >= 2 or
                       (zone and re.search(r'\b' + re.escape(zone[1]) + r' ZONE\b', u.context, re.I))))]
    return result
