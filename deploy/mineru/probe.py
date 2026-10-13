"""Authenticated V1 smoke test; accepts only same-origin task/result URLs."""

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx


def same_origin_url(base, value):
    url = urljoin(base.rstrip("/") + "/", value)
    a, b = urlsplit(base), urlsplit(url)

    def origin(parsed):
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("Invalid task URL")
        return (
            parsed.scheme,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )

    if origin(a) != origin(b):
        raise ValueError("Unexpected cross-origin task URL")
    return url


def read_key(path):
    content = path.read_text(encoding="utf-8").strip()
    if "\n" in content or content.startswith("MINERU_API_"):
        values = dict(line.split("=", 1) for line in content.splitlines() if "=" in line)
        content = values.get("MINERU_API_KEY", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.+/=-]{32,512}", content):
        # Fail before constructing an HTTP header: transport exceptions can echo it.
        raise ValueError("Invalid MinerU key file format")
    return content


def main(args):
    key = read_key(args.token_file)
    headers = {"Authorization": "Bearer " + key}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=660) as client:
        health = client.get("/v1/health")
        health.raise_for_status()
        denied = client.post("/v1/uploads", headers={"Authorization": ""}, json={})
        assert denied.status_code in (401, 403), "Upload API must require authentication"
        started = time.monotonic()
        with args.input.open("rb") as stream:
            response = client.post(
                "/v1/file_parse",
                params={
                    "tier": "standard",
                    "ocr_mode": "ocr",
                    "wait_timeout": 600,
                    "output_formats": ["markdown", "middle_json", "structured_content"],
                },
                files={"files": (args.input.name, stream, "application/pdf")},
            )
        response.raise_for_status()
        payload = response.json()
        if response.status_code == 202:
            status_url = same_origin_url(args.base_url, payload["status_url"])
            result_url = same_origin_url(args.base_url, payload["result_url"])
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                status = client.get(status_url)
                status.raise_for_status()
                state = status.json().get("status")
                if state in {"completed", "partial", "failed", "canceled"}:
                    break
                time.sleep(2)
            else:
                raise TimeoutError("MinerU task polling budget exhausted")
            result = client.get(result_url)
            result.raise_for_status()
            payload = result.json()
        files = payload.get("files", [])
        if payload.get("status") in {"partial", "failed", "canceled"}:
            raise RuntimeError("MinerU parsing did not complete successfully")
        assert files and all(f.get("status") == "completed" for f in files), "File parsing failed"
        content = json.dumps([f.get("content", {}) for f in files], ensure_ascii=False)
        assert "BGP" in content and "6.06" in content and "R3" in content, "Missing fixture text"
        middle = files[0].get("content", {}).get("middle_json")
        if isinstance(middle, str):
            middle = json.loads(middle)
        assert isinstance(middle, dict) and len(middle.get("pages", [])) == 2, (
            "Missing structured PDF page data"
        )
        report = {
            "authenticated_health": health.status_code,
            "unauthenticated_upload": denied.status_code,
            "tier": "standard",
            "file_count": len(files),
            "all_files_completed": True,
            "fixture_markers_preserved": True,
            "structured_page_count": len(middle["pages"]),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "content_characters": len(content),
        }
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        args.output.with_suffix(".result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token-file", type=Path, default=Path("/run/secrets/mineru_api_key"))
    parser.add_argument("--input", type=Path, default=Path("/data/results/smoke.pdf"))
    parser.add_argument("--output", type=Path, default=Path("/data/results/smoke.json"))
    main(parser.parse_args())
