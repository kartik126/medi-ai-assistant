CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE sessions (
    session_id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    embedding_identity text,
    embedding_dimension integer CHECK (embedding_dimension > 0),
    CHECK ((embedding_identity IS NULL) = (embedding_dimension IS NULL))
);
CREATE TABLE documents (
    document_id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES sessions ON DELETE CASCADE,
    filename text NOT NULL,
    sha256 text NOT NULL,
    status text NOT NULL CHECK (status = 'ready'),
    byte_count bigint NOT NULL CHECK (byte_count > 0),
    page_count integer NOT NULL CHECK (page_count > 0),
    indexed_page_count integer NOT NULL,
    warning_pages jsonb NOT NULL DEFAULT '[]',
    UNIQUE(session_id, sha256),
    UNIQUE(session_id, document_id)
);
CREATE INDEX documents_session_idx ON documents(session_id);
CREATE TABLE pages (
    session_id uuid NOT NULL,
    document_id uuid NOT NULL,
    page_number integer NOT NULL CHECK (page_number > 0),
    text text NOT NULL,
    warning text,
    PRIMARY KEY(document_id, page_number),
    UNIQUE(session_id, document_id, page_number),
    FOREIGN KEY(session_id, document_id) REFERENCES documents(session_id, document_id) ON DELETE CASCADE
);
CREATE INDEX pages_session_idx ON pages(session_id);
CREATE TABLE chunks (
    chunk_id uuid PRIMARY KEY,
    session_id uuid NOT NULL,
    document_id uuid NOT NULL,
    page_number integer NOT NULL,
    text text NOT NULL,
    start_char integer NOT NULL CHECK (start_char >= 0),
    end_char integer NOT NULL CHECK (end_char > start_char),
    embedding_identity text NOT NULL,
    embedding vector NOT NULL,
    FOREIGN KEY(session_id, document_id, page_number) REFERENCES pages(session_id, document_id, page_number) ON DELETE CASCADE
);
CREATE INDEX chunks_session_document_idx ON chunks(session_id, document_id);
