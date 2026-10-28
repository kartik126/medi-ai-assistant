from contextlib import contextmanager
import hashlib
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector
from backend.errors import AppError

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def migrate(url):
    with psycopg.connect(url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(940471)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            sql = path.read_text()
            digest = hashlib.sha256(sql.encode()).hexdigest()
            row = conn.execute("SELECT sha256 FROM schema_migrations WHERE name=%s", (path.name,)).fetchone()
            if row:
                if row[0] != digest:
                    raise RuntimeError(f"Applied migration changed: {path.name}")
                continue
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations(name,sha256) VALUES (%s,%s)", (path.name, digest))


class Database:
    def __init__(self, url):
        self.pool = ConnectionPool(url, min_size=0, max_size=4, timeout=5,
                                   kwargs={"autocommit": True, "row_factory": dict_row, "connect_timeout": 3},
                                   configure=register_vector, open=False)

    def open(self):
        self.pool.open()

    def close(self):
        self.pool.close()

    @contextmanager
    def connection(self):
        with self.pool.connection() as conn:
            yield conn

    @contextmanager
    def session_lock(self, sid):
        key = int.from_bytes(hashlib.sha256(str(sid).encode()).digest()[:8], "big", signed=True)
        with self.connection() as conn:
            locked = conn.execute("SELECT pg_try_advisory_lock(%s) AS locked", (key,)).fetchone()["locked"]
            if not locked:
                raise AppError("session_busy", "This session is busy. Please retry shortly.", 409)
            try:
                yield conn
            finally:
                conn.execute("SELECT pg_advisory_unlock(%s)", (key,))

    def readiness(self):
        with self.connection() as conn:
            ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
            rows = conn.execute("SELECT name,sha256 FROM schema_migrations").fetchall()
            applied = {r["name"]: r["sha256"] for r in rows}
            ready = all(applied.get(p.name) == hashlib.sha256(p.read_bytes()).hexdigest() for p in MIGRATIONS.glob("*.sql"))
            return {"ready": bool(ext and ready), "pgvector_version": ext["extversion"] if ext else None}
