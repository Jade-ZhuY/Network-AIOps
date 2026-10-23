CREATE TABLE IF NOT EXISTS aiops_metric_governance (
    owner_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    scope_hash TEXT NOT NULL,
    document JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(owner_id, tenant_id, scope_hash)
);
