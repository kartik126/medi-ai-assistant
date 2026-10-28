import hashlib
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
import numpy as np
from psycopg.types.json import Jsonb
from backend.chunking import chunk_page
from backend.errors import AppError
from backend.pdf_service import extract_pdf
from backend.document_service import prepare_document


class Store:
    def __init__(self, db, settings, models):
        self.db, self.settings, self.models = db, settings, models
        self.root = settings.data_dir.resolve() / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, sid):
        return self.root / str(UUID(str(sid)))

    def session(self, conn, sid):
        row = conn.execute("SELECT * FROM sessions WHERE session_id=%s", (sid,)).fetchone()
        if not row:
            raise AppError("session_not_found", "Session unavailable. Start a new session.", 404)
        return row

    def create(self):
        sid = uuid4()
        with self.db.connection() as conn:
            conn.execute("INSERT INTO sessions(session_id) VALUES (%s)", (sid,))
        return sid

    def documents(self, sid):
        with self.db.connection() as conn:
            self.session(conn, sid)
            return conn.execute("SELECT * FROM documents WHERE session_id=%s ORDER BY filename,document_id", (sid,)).fetchall()

    def document(self, sid, did):
        with self.db.connection() as conn:
            self.session(conn, sid)
            row = conn.execute("SELECT * FROM documents WHERE session_id=%s AND document_id=%s", (sid, did)).fetchone()
        if not row:
            raise AppError("document_not_found", "Document unavailable in this session.", 404)
        return row

    def page(self, sid, did, number):
        self.document(sid, did)
        with self.db.connection() as conn:
            row = conn.execute("SELECT page_number,text,warning FROM pages WHERE session_id=%s AND document_id=%s AND page_number=%s", (sid, did, number)).fetchone()
        if not row:
            raise AppError("page_not_found", "Physical page unavailable.", 404)
        return row

    def ingest(self, sid, filename, content):
        digest = hashlib.sha256(content).hexdigest()
        settings = self.settings
        with self.db.session_lock(sid) as conn:
            session = self.session(conn, sid)
            existing = conn.execute("SELECT * FROM documents WHERE session_id=%s AND sha256=%s", (sid, digest)).fetchone()
            if existing:
                return {**existing, "duplicate": True}
            stats = conn.execute("SELECT count(*) AS files,coalesce(sum(byte_count),0) AS bytes,coalesce(sum(page_count),0) AS pages FROM documents WHERE session_id=%s", (sid,)).fetchone()
            if stats["files"] >= settings.max_files:
                raise AppError("file_limit", f"A session supports {settings.max_files} documents.", 413)
            if len(content) > settings.max_file_mb * 1024**2 or len(content) + stats["bytes"] > settings.max_total_mb * 1024**2:
                raise AppError("size_limit", "Document exceeds the file or aggregate session size limit.", 413)
            rendered = prepare_document(content, filename, settings)
            if Path(filename).suffix.lower() != '.pdf':
                word_ids = conn.execute("SELECT document_id FROM documents WHERE session_id=%s AND lower(filename) ~ '\\.(doc|docx)$'", (sid,)).fetchall()
                derived_bytes = sum(p.stat().st_size for row in word_ids
                                    if (p := self.directory(sid) / f"{row['document_id']}.pdf").exists())
                if derived_bytes + len(rendered) > settings.max_total_mb * 1024**2:
                    raise AppError('converted_size_limit', 'Converted PDFs exceed the session size limit.', 413)
            pages = extract_pdf(rendered, 'rendered.pdf', settings.max_total_pages - stats["pages"])
            chunks = []
            for page in pages:
                if not any(c.isalnum() for c in page.text):
                    continue
                for chunk in chunk_page(page.text, settings.chunk_target_chars, settings.chunk_overlap_chars, settings.chunk_max_chars):
                    chunks.append({"chunk_id": uuid4(), "page_number": page.page_number, "text": chunk.text,
                                   "start_char": chunk.start_char, "end_char": chunk.end_char})
            if not chunks:
                raise AppError("no_text", "No indexable text found.")
            with self.models.serialized():
                identity = self.models.identity()
                if session["embedding_identity"] and session["embedding_identity"] != identity:
                    raise AppError("embedding_mismatch", "Embedding configuration changed. Clear and re-ingest the session.", 409)
                vectors = []
                for offset in range(0, len(chunks), settings.embedding_batch_size):
                    vectors.extend(self.models.embed([c["text"] for c in chunks[offset:offset + settings.embedding_batch_size]]))
                if self.models.identity() != identity:
                    raise AppError("embedding_changed", "Embedding model changed during ingestion. Retry.", 409)
            dim = len(vectors[0])
            if any(len(v) != dim for v in vectors) or (session["embedding_dimension"] and session["embedding_dimension"] != dim):
                raise AppError("embedding_mismatch", "Embedding dimensions changed. Clear and re-ingest the session.", 409)
            did = uuid4()
            directory = self.directory(sid)
            directory.mkdir(exist_ok=True)
            staged, final = directory / f"{did}.part", directory / f"{did}.pdf"
            extension = Path(filename).suffix.lower()
            original = directory / f'{did}{extension}' if extension != '.pdf' else None
            original_staged = directory / f'{did}.original.part'
            warnings = [{"page_number": p.page_number, "warning": p.warning} for p in pages if p.warning]
            try:
                staged.write_bytes(rendered)
                if original:
                    original_staged.write_bytes(content)
                with conn.transaction():
                    self.session(conn, sid)
                    conn.execute("UPDATE sessions SET embedding_identity=%s, embedding_dimension=%s,updated_at=now() WHERE session_id=%s", (identity, dim, sid))
                    conn.execute("INSERT INTO documents(document_id,session_id,filename,sha256,status,byte_count,page_count,indexed_page_count,warning_pages) VALUES (%s,%s,%s,%s,'ready',%s,%s,%s,%s)",
                                 (did, sid, filename, digest, len(content), len(pages), len({c['page_number'] for c in chunks}), Jsonb(warnings)))
                    with conn.cursor() as cur:
                        cur.executemany("INSERT INTO pages(session_id,document_id,page_number,text,warning) VALUES (%s,%s,%s,%s,%s)", [(sid, did, p.page_number, p.text, p.warning) for p in pages])
                        cur.executemany("INSERT INTO chunks(chunk_id,session_id,document_id,page_number,text,start_char,end_char,embedding_identity,embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                        [(c["chunk_id"], sid, did, c["page_number"], c["text"], c["start_char"], c["end_char"], identity, np.array(v, dtype=np.float32)) for c, v in zip(chunks, vectors)])
                    staged.replace(final)
                    if original:
                        original_staged.replace(original)
            except Exception:
                staged.unlink(missing_ok=True)
                final.unlink(missing_ok=True)
                original_staged.unlink(missing_ok=True)
                if original:
                    original.unlink(missing_ok=True)
                raise
            return conn.execute("SELECT * FROM documents WHERE session_id=%s AND document_id=%s", (sid, did)).fetchone()

    def delete(self, sid):
        with self.db.session_lock(sid) as conn:
            self.session(conn, sid)
            conn.execute("DELETE FROM sessions WHERE session_id=%s", (sid,))
            directory = self.directory(sid)
            if directory.exists():
                shutil.rmtree(directory)

    def cleanup(self):
        # Advisory locks prevent cleanup from racing ingestion/reads/chat.
        with self.db.connection() as conn:
            old = conn.execute("SELECT session_id FROM sessions WHERE updated_at < now() - (%s * interval '1 hour')", (self.settings.session_ttl_hours,)).fetchall()
        for row in old:
            try:
                sid = row["session_id"]
                with self.db.session_lock(sid) as conn:
                    expired = conn.execute("SELECT 1 FROM sessions WHERE session_id=%s AND updated_at < now() - (%s * interval '1 hour')", (sid, self.settings.session_ttl_hours)).fetchone()
                    if not expired:
                        continue
                    conn.execute("DELETE FROM sessions WHERE session_id=%s", (sid,))
                    directory = self.directory(sid)
                    if directory.exists():
                        shutil.rmtree(directory)
            except AppError:
                continue
        # Reconcile orphan files only while holding the corresponding session lock.
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            try:
                sid = UUID(directory.name)
            except ValueError:
                continue
            try:
                with self.db.session_lock(sid) as conn:
                    exists = conn.execute("SELECT 1 FROM sessions WHERE session_id=%s", (sid,)).fetchone()
                    if not exists:
                        shutil.rmtree(directory)
                        continue
                    ids = {str(r["document_id"]) for r in conn.execute("SELECT document_id FROM documents WHERE session_id=%s", (sid,)).fetchall()}
                    for path in directory.iterdir():
                        try:
                            generated_word = path.suffix in {'.doc', '.docx'} and str(UUID(path.stem)) == path.stem
                        except ValueError:
                            generated_word = False
                        if path.is_file() and (path.suffix == ".part" or ((path.suffix == '.pdf' or generated_word) and path.stem not in ids)):
                            path.unlink()
            except AppError:
                continue
