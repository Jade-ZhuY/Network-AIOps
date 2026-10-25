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
  created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE INDEX ix_monitor_owner_updated ON monitor(owner_id,tenant_id,deleted,updated_at);
ALTER TABLE audit_events ADD COLUMN resource_id VARCHAR(48) NULL;
-- Test-only fixtures mirroring scripts/init_mysql.sql so read-only metric
-- queries run against the H2 schema; production MySQL owns these tables itself.
CREATE TABLE network_devices (
  device_id INTEGER NOT NULL PRIMARY KEY,
  hostname VARCHAR(64) NOT NULL,
  device_type VARCHAR(32) NOT NULL,
  region VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  UNIQUE (hostname)
);
CREATE TABLE network_interfaces (
  interface_id INTEGER NOT NULL PRIMARY KEY,
  device_id INTEGER NOT NULL,
  interface_name VARCHAR(64) NOT NULL
);
CREATE TABLE network_metrics (
  metric_id INTEGER NOT NULL PRIMARY KEY,
  device_id INTEGER NOT NULL,
  interface_id INTEGER,
  sample_time TIMESTAMP NOT NULL,
  latency_ms DOUBLE,
  packet_loss_pct DOUBLE,
  utilization_pct DOUBLE
);
