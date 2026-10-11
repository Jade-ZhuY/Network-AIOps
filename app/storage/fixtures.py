"""Fixed UTC fixtures. Evaluation root causes live ONLY in tests/datasets."""

from datetime import UTC, datetime


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 10, hour, minute, tzinfo=UTC)


def demo_records() -> dict[str, list[dict]]:
    devices = [
        dict(
            device_id=i,
            hostname=f"R{i}",
            device_type="router",
            management_ip=f"192.0.2.{i}",
            region="lab",
            tenant_id="demo-tenant",
            status="up",
        )
        for i in range(1, 5)
    ]
    devices.append(
        dict(
            device_id=99,
            hostname="R99",
            device_type="router",
            management_ip="192.0.2.99",
            region="private-lab",
            tenant_id="other-tenant",
            status="down",
        )
    )
    interfaces = [
        dict(
            interface_id=i * 10 + 1,
            device_id=i,
            interface_name="eth1",
            admin_status="up",
            oper_status="up",
        )
        for i in (1, 2, 3, 4, 99)
    ]
    alarms = [
        dict(
            alarm_id=101 + j,
            device_id=2,
            severity="critical",
            alarm_type="BGP_NEIGHBOR_DOWN",
            description="BGP peer session lost (demo)",
            occurred_at=at(6, j * 15),
        )
        for j in range(3)
    ] + [
        dict(
            alarm_id=201,
            device_id=3,
            severity="major",
            alarm_type="OSPF_ADJACENCY_DOWN",
            description="OSPF adjacency remains Init (demo)",
            occurred_at=at(7),
        ),
        dict(
            alarm_id=301,
            device_id=4,
            severity="major",
            alarm_type="HIGH_UTILIZATION",
            description="Interface utilization high (demo)",
            occurred_at=at(8),
        ),
        dict(
            alarm_id=999,
            device_id=99,
            severity="critical",
            alarm_type="PRIVATE_ALARM",
            description="OTHER_TENANT_SECRET",
            occurred_at=at(6),
        ),
    ]
    metrics = []
    # Baseline, fault, recovery. 06:00–08:00 UTC = 14:00–16:00 Shanghai.
    patterns = {
        1: [(0.1, 2, 20)] * 5,
        2: [(0.1, 3, 30), (8, 60, 45), (12, 85, 48), (10, 70, 40), (0.2, 4, 32)],
        3: [(0.1, 3, 20)] * 5,
        4: [(0.1, 3, 35), (1, 35, 85), (2, 75, 96), (1.5, 90, 98), (0.1, 5, 40)],
        99: [(99, 999, 100)] * 5,
    }
    for device, samples in patterns.items():
        for j, (loss, rtt, utilization) in enumerate(samples):
            metrics.append(
                dict(
                    metric_id=device * 100 + j,
                    device_id=device,
                    interface_id=device * 10 + 1,
                    sample_time=at(5 + j),
                    latency_ms=float(rtt),
                    packet_loss_pct=float(loss),
                    utilization_pct=float(utilization),
                )
            )
    incidents = [
        dict(
            incident_id=key,
            device_id=device,
            started_at=at(hour),
            ended_at=at(9),
            symptom=symptom,
            root_cause=None,
            resolution=None,
        )
        for key, device, hour, symptom in (
            ("INC-BGP-001", 2, 6, "BGP peer flaps; interface loss increases"),
            ("INC-OSPF-002", 3, 7, "OSPF adjacency not established; interface remains up"),
            ("INC-TRAFFIC-003", 4, 8, "High utilization and RTT observed together"),
        )
    ]
    return {
        "network_devices": devices,
        "network_interfaces": interfaces,
        "network_links": [
            dict(link_id=1, src_interface_id=21, dst_interface_id=11, link_status="up"),
            dict(link_id=2, src_interface_id=31, dst_interface_id=41, link_status="up"),
        ],
        "network_alarms": alarms,
        "network_metrics": metrics,
        "network_incidents": incidents,
    }


def scoped_records(scope, records=None) -> dict[str, list[dict]]:
    records = records if records is not None else demo_records()
    ids = {
        d["device_id"]
        for d in records["network_devices"]
        if d["tenant_id"] == scope.tenant_id and d["device_id"] in scope.device_ids
    }
    interface_ids = {
        i["interface_id"] for i in records["network_interfaces"] if i["device_id"] in ids
    }
    return {
        table: [
            row
            for row in rows
            if (
                row["device_id"] in ids
                if "device_id" in row
                else row["src_interface_id"] in interface_ids
                and row["dst_interface_id"] in interface_ids
            )
        ]
        for table, rows in records.items()
    }
