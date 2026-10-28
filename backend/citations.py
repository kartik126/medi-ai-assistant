"""Strict structural/provenance validation, independent of model/runtime libraries."""
import json
import re
from copy import deepcopy

ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["status", "claims"],
    "properties": {
        "status": {"type": "string", "enum": ["answered", "insufficient_evidence"]},
        "claims": {"type": "array", "maxItems": 6, "items": {
            "type": "object", "additionalProperties": False, "required": ["text", "evidence"],
            "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": 800},
                "evidence": {"type": "array", "minItems": 1, "maxItems": 4, "items": {
                    "type": "object", "additionalProperties": False, "required": ["source_id", "quote"],
                    "properties": {"source_id": {"type": "string"}, "quote": {"type": "string", "minLength": 1, "maxLength": 600}}
                }}
            }
        }}
    }
}

REPAIR_SCHEMA = deepcopy(ANSWER_SCHEMA)
_repair_evidence = REPAIR_SCHEMA['properties']['claims']['items']['properties']['evidence']['items']
_repair_evidence['required'] = ['source_id', 'quote_id']
_repair_evidence['properties'] = {'source_id': {'type': 'string'}, 'quote_id': {'type': 'string'}}


def whitespace(text):
    return re.sub(r"\s+", " ", text).strip()


def quote_candidates(sources):
    """Server-owned contiguous excerpts for an ID-only citation repair."""
    candidates = {}
    for source in sources:
        excerpts = []
        for sentence in re.split(r'(?<=[.!?])\s+', whitespace(source['text'])):
            while len(sentence) > 600:
                boundary = sentence.rfind(' ', 0, 600)
                boundary = boundary if boundary > 0 else 600
                excerpts.append(sentence[:boundary])
                sentence = sentence[boundary:].lstrip()
            if sentence:
                excerpts.append(sentence)
        candidates[source['source_id']] = {f'Q{i+1}': text for i, text in enumerate(excerpts)}
    return candidates


def resolve_quote_ids(raw, candidates):
    """Resolve only supplied IDs; final claims still undergo full validation."""
    if not isinstance(raw, str) or len(raw) > 20000:
        raise ValueError('Output size is invalid')
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('claims'), list):
        raise ValueError('Invalid repair response')
    for claim in data['claims']:
        if not isinstance(claim, dict) or not isinstance(claim.get('evidence'), list):
            raise ValueError('Invalid repair evidence')
        resolved = []
        for item in claim['evidence']:
            if not isinstance(item, dict) or set(item) != {'source_id', 'quote_id'}:
                raise ValueError('Invalid repair evidence fields')
            sid, qid = item['source_id'], item['quote_id']
            if not isinstance(sid, str) or not isinstance(qid, str) or qid not in candidates.get(sid, {}):
                raise ValueError('Unknown repair quote ID')
            resolved.append({'source_id': sid, 'quote': candidates[sid][qid]})
        claim['evidence'] = resolved
    return json.dumps(data)


def validate_claims(raw, sources):
    if not isinstance(raw, str) or len(raw) > 20000:
        raise ValueError("Output size is invalid")
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {"status", "claims"}:
        raise ValueError("Expected status and claims only")
    if data["status"] not in ("answered", "insufficient_evidence"):
        raise ValueError("Invalid status")
    claims = data["claims"]
    if not isinstance(claims, list) or len(claims) > 6:
        raise ValueError("Invalid claims list")
    if data["status"] == "insufficient_evidence":
        if claims:
            raise ValueError("Abstention must have no claims")
        return data
    if not claims:
        raise ValueError("An answer requires claims")
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) != {"text", "evidence"}:
            raise ValueError("Invalid claim fields")
        if not isinstance(claim["text"], str) or not 1 <= len(claim["text"].strip()) <= 800:
            raise ValueError("Invalid claim text")
        evidence = claim["evidence"]
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 4:
            raise ValueError("Each claim needs evidence")
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {"source_id", "quote"}:
                raise ValueError("Invalid evidence fields")
            sid, quote = item["source_id"], item["quote"]
            if not isinstance(sid, str) or sid not in sources:
                raise ValueError("Unknown source ID")
            if not isinstance(quote, str) or not 1 <= len(quote.strip()) <= 600:
                raise ValueError("Invalid quote")
            if whitespace(quote) not in whitespace(sources[sid]["text"]):
                raise ValueError("Quote does not occur in cited source")
        # Necessary support check, not general entailment: numbers and codes
        # asserted by a claim must also occur in that claim's quoted evidence.
        quoted = ' '.join(whitespace(item['quote']) for item in evidence)
        identifiers = re.findall(r'\b[A-Z]+(?:-[A-Z0-9]+)+\b|\b\d+(?:[.\-/]\d+)*\b', claim['text'])
        for value in identifiers:
            if not re.search(r'(?<!\w)' + re.escape(value) + r'(?!\w)', quoted):
                raise ValueError('Claim number or identifier is absent from quoted evidence')
    return data
