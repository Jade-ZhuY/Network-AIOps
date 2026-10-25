CREATE TABLE monitor (
  id VARCHAR(36) PRIMARY KEY,
  owner_id VARCHAR(80) NOT NULL,
  tenant_id VARCHAR(80) NOT NULL,
  name VARCHAR(100) NOT NULL,
  type VARCHAR(32) NOT NULL,
  hostname VARCHAR(64) NOT NULL,
  labels VARCHAR(1000) NOT NULL,
  description VARCHAR(500) NOT NULL,
  status VARCHAR(16) NOT NULL CHECK (status IN ('UP','DOWN','UNKNOWN')),
  version BIGINT NOT NULL DEFAULT 0,
  deleted BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  KEY ix_monitor_owner_updated (owner_id,tenant_id,deleted,updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
ALTER TABLE audit_events ADD COLUMN resource_id VARCHAR(48) NULL;
