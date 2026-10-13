"""Start upstream MinerU; read its bearer key from a mounted secret file."""

import os
from pathlib import Path

key = Path(os.environ["MINERU_API_KEY_FILE"]).read_text(encoding="utf-8").strip()
if len(key) < 32:
    raise RuntimeError("MinerU API key must contain at least 32 characters")
os.execvp(
    "mineru-kit",
    [
        "mineru-kit",
        "api-server",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--tier",
        "standard",
        "--concurrency",
        "1",
        "--upload-dir",
        "/data/uploads",
        "--api-key",
        key,
    ],
)
