import json
import os
import urllib.request
from pathlib import Path

key = Path(os.environ["MINERU_API_KEY_FILE"]).read_text(encoding="utf-8").strip()
request = urllib.request.Request(
    "http://127.0.0.1:8000/v1/health",
    headers={"Authorization": f"Bearer {key}"},
)
with urllib.request.urlopen(request, timeout=10) as response:
    data = json.load(response)
if not isinstance(data, dict):
    raise RuntimeError("Unexpected MinerU health response")
