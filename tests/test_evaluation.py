import ast
import json

from app.config import ROOT
from scripts.evaluate import evaluate


async def test_fixed_benchmark_runs_full_tools_and_context():
    result = await evaluate()
    assert result["evaluation_mode"] == "deterministic_mock_pipeline"
    assert result["counts"]["routes"] == 60
    assert result["counts"]["faults"] == 30
    assert result["counts"]["multi_turn_groups"] == 20
    assert result["counts"]["citations"] > 0
    assert result["metrics"]["route_accuracy"] >= 0.9
    assert result["metrics"]["multi_turn_resolution"] >= 0.9
    assert result["metrics"]["synthetic_root_cause_top3_hit"] >= 0.8
    assert not result["failures"]
    assert result["not_real_model_quality"]


def test_fault_variants_distinct_and_labels_outside_agent_data():
    from scripts.evaluate import varying_records

    cases = json.loads(
        (ROOT / "tests" / "datasets" / "fault_cases.json").read_text(encoding="utf-8")
    )
    samples = [varying_records(case) for case in cases]
    assert len({str(sample["network_metrics"]) for sample in samples}) == 30
    assert all(
        row["root_cause"] is None for sample in samples for row in sample["network_incidents"]
    )
    for path in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            assert not any(
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and ("tests/datasets" in node.value or "root_causes.json" in node.value)
                for node in ast.walk(call)
            )
