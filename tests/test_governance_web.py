import shutil
import subprocess

import pytest

from app.config import ROOT


@pytest.mark.skipif(
    shutil.which("node") is None, reason="Node is needed for the isolated DOM regression"
)
def test_governance_frontend_flow_without_starting_a_server():
    result = subprocess.run(
        ["node", str(ROOT / "tests" / "web" / "governance_dom.cjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Governance DOM flow passed" in result.stdout
