CREATE TABLE tickets (
  id VARCHAR(36) PRIMARY KEY,
  owner_id VARCHAR(80) NOT NULL,
  tenant_id VARCHAR(80) NOT NULL,
  title VARCHAR(100) NOT NULL,
  device VARCHAR(64) NOT NULL,
  description VARCHAR(4000) NOT NULL,
  priority VARCHAR(16) NOT NULL CHECK (priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  status VARCHAR(20) NOT NULL CHECK (status IN ('OPEN','IN_PROGRESS','RESOLVED','CLOSED')),
  analysis_status VARCHAR(20) NOT NULL CHECK (analysis_status IN ('NOT_STARTED','RUNNING','SUCCEEDED','FAILED')),
  agent_session_id VARCHAR(64),
  version BIGINT NOT NULL DEFAULT 0,
  deleted BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  KEY ix_ticket_owner_updated (owner_id,tenant_id,deleted,updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE ticket_analyses (
  id VARCHAR(36) PRIMARY KEY,
  ticket_id VARCHAR(36) NOT NULL,
  status VARCHAR(16) NOT NULL CHECK (status IN ('RUNNING','SUCCEEDED','FAILED')),
  request_id VARCHAR(64),
  response_json LONGTEXT,
  error_code VARCHAR(64),
  started_at DATETIME(6) NOT NULL,
  completed_at DATETIME(6),
  KEY ix_analysis_ticket (ticket_id,started_at),
  CONSTRAINT fk_ticket_analyses_ticket FOREIGN KEY (ticket_id) REFERENCES tickets(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE audit_events (
  id VARCHAR(36) PRIMARY KEY,
  owner_id VARCHAR(80) NOT NULL,
  tenant_id VARCHAR(80) NOT NULL,
  action VARCHAR(80) NOT NULL,
  ticket_id VARCHAR(36),
  trace_id VARCHAR(64) NOT NULL,
  outcome VARCHAR(24) NOT NULL,
  note VARCHAR(1200),
  created_at DATETIME(6) NOT NULL,
  KEY ix_audit_owner (owner_id,tenant_id,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
