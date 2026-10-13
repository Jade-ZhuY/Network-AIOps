"""Start the WebUI against the existing API without putting its key in argv."""

import os
from pathlib import Path


def launch_configuration(environment: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    key_path = Path(environment.get("MINERU_API_KEY_FILE", "/run/secrets/mineru_api_key"))
    key = key_path.read_text(encoding="utf-8").strip()
    if len(key) < 32 or not key.isascii() or any(char.isspace() for char in key):
        raise ValueError("Invalid MinerU API key file")
    api_url = environment.get("MINERU_API_URL", "http://api:8000")
    if not api_url.startswith("http://api:8000") or api_url.rstrip("/") != "http://api:8000":
        raise ValueError("WebUI must connect to the deployment's existing API")
    process_environment = {**environment, "MINERU_API_KEY": key}
    command = [
        "mineru-kit",
        "webui",
        "--api-url",
        "http://api:8000",
        "--server-name",
        "0.0.0.0",
        "--server-port",
        "7860",
        "--output-dir",
        "/data/output",
        "--no-enable-example",
    ]
    return command, process_environment


def main() -> None:
    command, environment = launch_configuration(dict(os.environ))
    for name in ("home", "tmp", "output"):
        Path("/data", name).mkdir(parents=True, exist_ok=True)
    os.execvpe(command[0], command, environment)


if __name__ == "__main__":
    main()
