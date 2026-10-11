from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Store naive UTC, require aware input at the Python boundary."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive timestamps are not accepted")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value else None


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "network_devices"
    device_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hostname: Mapped[str] = mapped_column(String(64), unique=True)
    device_type: Mapped[str] = mapped_column(String(32))
    management_ip: Mapped[str | None] = mapped_column(String(45))
    region: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))


class Interface(Base):
    __tablename__ = "network_interfaces"
    __table_args__ = (UniqueConstraint("device_id", "interface_name"),)
    interface_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("network_devices.device_id"))
    interface_name: Mapped[str] = mapped_column(String(64))
    admin_status: Mapped[str] = mapped_column(String(16))
    oper_status: Mapped[str] = mapped_column(String(16))


class Link(Base):
    __tablename__ = "network_links"
    link_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    src_interface_id: Mapped[int] = mapped_column(ForeignKey("network_interfaces.interface_id"))
    dst_interface_id: Mapped[int] = mapped_column(ForeignKey("network_interfaces.interface_id"))
    link_status: Mapped[str] = mapped_column(String(16))


class Alarm(Base):
    __tablename__ = "network_alarms"
    __table_args__ = (Index("idx_alarm_device_time", "device_id", "occurred_at"),)
    alarm_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("network_devices.device_id"))
    severity: Mapped[str] = mapped_column(String(16))
    alarm_type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)


class MetricSample(Base):
    __tablename__ = "network_metrics"
    __table_args__ = (Index("idx_metric_device_time", "device_id", "sample_time"),)
    metric_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("network_devices.device_id"))
    interface_id: Mapped[int | None] = mapped_column(ForeignKey("network_interfaces.interface_id"))
    sample_time: Mapped[datetime] = mapped_column(UTCDateTime)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    packet_loss_pct: Mapped[float | None] = mapped_column(Float)
    utilization_pct: Mapped[float | None] = mapped_column(Float)


class Incident(Base):
    __tablename__ = "network_incidents"
    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("network_devices.device_id"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    symptom: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)


# tenant_id is reserved for backend enforcement, not advertised to the Agent.
VIEW_COLUMNS = {
    "v_device_status": ("device_id", "hostname", "region", "status"),
    "v_alarm_events": (
        "alarm_id",
        "device_id",
        "hostname",
        "severity",
        "alarm_type",
        "description",
        "occurred_at",
    ),
    "v_interface_metrics": (
        "metric_id",
        "device_id",
        "hostname",
        "interface_name",
        "sample_time",
        "latency_ms",
        "packet_loss_pct",
        "utilization_pct",
    ),
    "v_incident_summaries": (
        "incident_id",
        "device_id",
        "hostname",
        "started_at",
        "ended_at",
        "symptom",
    ),
}
VIEW_SELECTS = {
    "v_device_status": "SELECT device_id, hostname, region, status, tenant_id FROM network_devices",
    "v_alarm_events": "SELECT a.alarm_id, d.device_id, d.hostname, a.severity, a.alarm_type, a.description, a.occurred_at, d.tenant_id FROM network_alarms a JOIN network_devices d ON a.device_id=d.device_id",
    "v_interface_metrics": "SELECT m.metric_id, d.device_id, d.hostname, i.interface_name, m.sample_time, m.latency_ms, m.packet_loss_pct, m.utilization_pct, d.tenant_id FROM network_metrics m JOIN network_devices d ON m.device_id=d.device_id LEFT JOIN network_interfaces i ON m.interface_id=i.interface_id",
    "v_incident_summaries": "SELECT n.incident_id, d.device_id, d.hostname, n.started_at, n.ended_at, n.symptom, d.tenant_id FROM network_incidents n JOIN network_devices d ON n.device_id=d.device_id",
}
