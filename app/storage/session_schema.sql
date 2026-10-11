CREATE TABLE IF NOT EXISTS aiops_sessions (
    session_id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    scope_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    timezone TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS aiops_sessions_owner ON aiops_sessions(owner_id, tenant_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS aiops_requests (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES aiops_sessions(session_id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,
    message TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    status TEXT NOT NULL DEFAULT 'running',
    response JSONB,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS aiops_requests_session ON aiops_requests(session_id, started_at);
ALTER TABLE aiops_requests ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai';
CREATE TABLE IF NOT EXISTS aiops_documents (
    doc_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    access_scope JSONB NOT NULL,
    status TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
