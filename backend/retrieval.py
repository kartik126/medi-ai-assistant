"""Bounded evidence selection after database cosine ranking."""
import numpy as np
import re
from backend.errors import AppError


def retrieval_questions(question):
    """Bounded deterministic decomposition for substantial joined questions.

    Short conjunctions such as 'risks and benefits' stay together. No model,
    chat memory, or expansion beyond the user's actual words is involved.
    """
    parts = re.split(r'\s+(?:and|versus|vs\.?|as well as)\s+', question,
                     maxsplit=2, flags=re.IGNORECASE)
    independent = all(re.match(
        r'^(?:what\b|how\b|why\b|when\b|where\b|does\b|is\b|are\b|summarize\b|describe\b|compare\b|the\s+.+?\b(?:guide|booklet|plan|report|handbook)\b)',
        p, re.I) for p in parts[1:])
    if len(parts) > 1 and independent and all(len(re.findall(r'\w+', p)) >= 4 for p in parts):
        return parts
    return [question]


def instruction_override(text):
    """Narrow defense in depth; not a general prompt-injection classifier.

    Do not present explicit attempts to override assistant instructions as
    factual evidence. Quarantine the whole chunk to preserve text provenance.
    """
    return bool(re.search(r'\b(?:ignore|disregard|forget)\s+(?:all\s+)?(?:the\s+)?'
                          r'(?:previous|prior|above|earlier)\s+instructions\b',
                          text, re.IGNORECASE))


def flattened_numeric_table(text):
    """Recognize dense numeric columns whose row relationships may be lost."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    numeric = sum(bool(re.fullmatch(r'[\d\s,./%–−-]+(?:\s*(?:mg|g))?', line)) for line in lines)
    return numeric >= 12 and numeric / max(1, len(lines)) >= .25


def select_context(rows, max_chunks=6, max_chars=8000, min_similarity=-1.0, question=None):
    selected, used = [], 0
    if question:
        from backend.evidence import rank_units
        # Exact lexical anchors complement semantic ranking within the already
        # session/document-filtered pgvector candidates.
        def score(row):
            evidence = rank_units(question, [row], [])
            return evidence[0].score if evidence else -1
        rows = sorted(rows, key=score, reverse=True)
    for row in rows:
        # Dense flattened columns have lost their row relationships. Keep them
        # stored for source inspection, but do not ask the text-only model to
        # reconstruct unsupported table semantics.
        if flattened_numeric_table(row['text']):
            continue
        if instruction_override(row['text']):
            continue
        if row["similarity"] < min_similarity:
            continue
        duplicate = False
        for other in selected:
            if row["document_id"] != other["document_id"] or row["page_number"] != other["page_number"]:
                continue
            intersection = max(0, min(row["end_char"], other["end_char"]) - max(row["start_char"], other["start_char"]))
            shortest = min(row["end_char"] - row["start_char"], other["end_char"] - other["start_char"])
            if intersection / max(1, shortest) > 0.6:
                duplicate = True
        if duplicate or used + len(row["text"]) > max_chars:
            continue
        selected.append({**row, "source_id": f"S{len(selected)+1}"})
        used += len(row["text"])
        if len(selected) >= max_chunks:
            break
    return selected


def retrieve(conn, sid, document_ids, vector, identity, settings, question=None):
    rows = conn.execute("""
        SELECT c.chunk_id,c.document_id,c.page_number,c.text,c.start_char,c.end_char,d.filename,p.text AS page_text,
               1 - (c.embedding <=> %s) AS similarity
        FROM chunks c JOIN documents d ON d.document_id=c.document_id AND d.session_id=c.session_id
        JOIN pages p ON p.document_id=c.document_id AND p.session_id=c.session_id AND p.page_number=c.page_number
        WHERE c.session_id=%s AND c.document_id=ANY(%s::uuid[]) AND d.status='ready'
              AND c.embedding_identity=%s
        ORDER BY c.embedding <=> %s,c.chunk_id LIMIT %s
    """, (np.array(vector, dtype=np.float32), sid, document_ids, identity,
          np.array(vector, dtype=np.float32), settings.retrieval_candidates)).fetchall()
    if question and rows:
        # A semantic hit may end immediately before a small inline table.
        # Include bounded same-page neighbors, retaining all scope/identity
        # predicates and exact original chunks rather than inventing joins.
        neighbors = conn.execute("""
            SELECT c.chunk_id,c.document_id,c.page_number,c.text,c.start_char,c.end_char,d.filename,p.text AS page_text,
                   1 - (c.embedding <=> %s) AS similarity
            FROM chunks c JOIN documents d ON d.document_id=c.document_id AND d.session_id=c.session_id
            JOIN pages p ON p.document_id=c.document_id AND p.session_id=c.session_id AND p.page_number=c.page_number
            WHERE c.session_id=%s AND c.document_id=ANY(%s::uuid[]) AND d.status='ready'
                  AND c.embedding_identity=%s AND c.page_number=ANY(%s::int[])
            ORDER BY c.embedding <=> %s,c.chunk_id LIMIT %s
        """, (np.array(vector, dtype=np.float32), sid, document_ids, identity,
              list({r['page_number'] for r in rows}), np.array(vector, dtype=np.float32),
              min(40, settings.retrieval_candidates * 3))).fetchall()
        rows = list({r['chunk_id']: r for r in rows + neighbors}.values())
    return select_context(rows, settings.max_context_chunks, settings.max_context_chars, settings.min_similarity, question)
