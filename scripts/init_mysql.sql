-- Generated from app/storage/models.py; MySQL 8, UTC timestamps.
-- Run in a dedicated development BUSINESS database; no checkpoint tables.
SET time_zone = '+00:00';

CREATE TABLE network_devices (
	device_id INTEGER NOT NULL AUTO_INCREMENT, 
	hostname VARCHAR(64) NOT NULL, 
	device_type VARCHAR(32) NOT NULL, 
	management_ip VARCHAR(45), 
	region VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (device_id), 
	UNIQUE (hostname)
);

CREATE INDEX ix_network_devices_tenant_id ON network_devices (tenant_id);

CREATE TABLE network_alarms (
	alarm_id INTEGER NOT NULL AUTO_INCREMENT, 
	device_id INTEGER NOT NULL, 
	severity VARCHAR(16) NOT NULL, 
	alarm_type VARCHAR(64) NOT NULL, 
	description TEXT NOT NULL, 
	occurred_at DATETIME NOT NULL, 
	PRIMARY KEY (alarm_id), 
	FOREIGN KEY(device_id) REFERENCES network_devices (device_id)
);

CREATE INDEX idx_alarm_device_time ON network_alarms (device_id, occurred_at);

CREATE TABLE network_incidents (
	incident_id VARCHAR(64) NOT NULL, 
	device_id INTEGER NOT NULL, 
	started_at DATETIME NOT NULL, 
	ended_at DATETIME, 
	symptom TEXT NOT NULL, 
	root_cause TEXT, 
	resolution TEXT, 
	PRIMARY KEY (incident_id), 
	FOREIGN KEY(device_id) REFERENCES network_devices (device_id)
);

CREATE TABLE network_interfaces (
	interface_id INTEGER NOT NULL AUTO_INCREMENT, 
	device_id INTEGER NOT NULL, 
	interface_name VARCHAR(64) NOT NULL, 
	admin_status VARCHAR(16) NOT NULL, 
	oper_status VARCHAR(16) NOT NULL, 
	PRIMARY KEY (interface_id), 
	UNIQUE (device_id, interface_name), 
	FOREIGN KEY(device_id) REFERENCES network_devices (device_id)
);

CREATE TABLE network_links (
	link_id INTEGER NOT NULL AUTO_INCREMENT, 
	src_interface_id INTEGER NOT NULL, 
	dst_interface_id INTEGER NOT NULL, 
	link_status VARCHAR(16) NOT NULL, 
	PRIMARY KEY (link_id), 
	FOREIGN KEY(src_interface_id) REFERENCES network_interfaces (interface_id), 
	FOREIGN KEY(dst_interface_id) REFERENCES network_interfaces (interface_id)
);

CREATE TABLE network_metrics (
	metric_id INTEGER NOT NULL AUTO_INCREMENT, 
	device_id INTEGER NOT NULL, 
	interface_id INTEGER, 
	sample_time DATETIME NOT NULL, 
	latency_ms FLOAT, 
	packet_loss_pct FLOAT, 
	utilization_pct FLOAT, 
	PRIMARY KEY (metric_id), 
	FOREIGN KEY(device_id) REFERENCES network_devices (device_id), 
	FOREIGN KEY(interface_id) REFERENCES network_interfaces (interface_id)
);

CREATE INDEX idx_metric_device_time ON network_metrics (device_id, sample_time);

CREATE SQL SECURITY DEFINER VIEW v_interface_status AS SELECT d.device_id,d.hostname,i.interface_id,i.interface_name,i.admin_status,i.oper_status,d.tenant_id FROM network_interfaces i JOIN network_devices d ON i.device_id=d.device_id;

CREATE SQL SECURITY DEFINER VIEW v_link_status AS SELECT d.device_id,d.hostname,a.interface_name,e.device_id AS peer_device_id,e.hostname AS peer_hostname,b.interface_name AS peer_interface_name,l.link_id,l.link_status,d.tenant_id,e.tenant_id AS peer_tenant_id FROM network_links l JOIN network_interfaces a ON l.src_interface_id=a.interface_id JOIN network_interfaces b ON l.dst_interface_id=b.interface_id JOIN network_devices d ON a.device_id=d.device_id JOIN network_devices e ON b.device_id=e.device_id;

CREATE SQL SECURITY DEFINER VIEW v_device_status AS SELECT device_id, hostname, region, status, tenant_id FROM network_devices;

CREATE SQL SECURITY DEFINER VIEW v_alarm_events AS SELECT a.alarm_id, d.device_id, d.hostname, a.severity, a.alarm_type, a.description, a.occurred_at, d.tenant_id FROM network_alarms a JOIN network_devices d ON a.device_id=d.device_id;

CREATE SQL SECURITY DEFINER VIEW v_interface_metrics AS SELECT m.metric_id, d.device_id, d.hostname, i.interface_name, m.sample_time, m.latency_ms, m.packet_loss_pct, m.utilization_pct, d.tenant_id FROM network_metrics m JOIN network_devices d ON m.device_id=d.device_id LEFT JOIN network_interfaces i ON m.interface_id=i.interface_id;

CREATE SQL SECURITY DEFINER VIEW v_incident_summaries AS SELECT n.incident_id, d.device_id, d.hostname, n.started_at, n.ended_at, n.symptom, d.tenant_id FROM network_incidents n JOIN network_devices d ON n.device_id=d.device_id;

-- Provision a netops_ro account separately with SELECT on these six views ONLY.
-- No base-table privileges, no root_cause/resolution field in views.
-- Credentials are not stored here.
