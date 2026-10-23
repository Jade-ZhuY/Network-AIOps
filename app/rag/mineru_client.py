"""MinerU 4.x V1 adapter: no legacy parsing fallback and no local inference."""

import hashlib
import html
import io
import json
import math
import mimetypes
import os
import re
import shutil
import threading
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urljoin, urlsplit

import httpx
from markdown_it import MarkdownIt

from app.config import ROOT
from app.rag.document_types import ParsedBlock, ParsedDocument, ParsedPage

SUPPORTED_SUFFIXES = frozenset(
    {
        ".pdf",
        ".md",
        ".txt",
        ".html",
        ".htm",
        ".docx",
        ".pptx",
        ".xlsx",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }
)
NATIVE_SUFFIXES = frozenset({".md", ".txt", ".html", ".htm", ".docx", ".pptx", ".xlsx"})
ADAPTER_VERSION = "mineru-v1-adapter-1:md-html-1"
_locks = {}
_locks_guard = threading.Lock()


class MinerUError(RuntimeError):
    """Only credential-free error descriptions cross the API boundary."""


def sha(value: bytes):
    return hashlib.sha256(value).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def same_origin_url(base, value):
    if not isinstance(value, str) or not value:
        raise MinerUError("MinerU task URL is missing")
    url = urljoin(base.rstrip("/") + "/", value)

    def origin(text):
        parts = urlsplit(text)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.fragment
        ):
            raise MinerUError("Invalid MinerU task URL")
        return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)

    if origin(base) != origin(url):
        raise MinerUError("Cross-origin MinerU task URL rejected")
    return url


def read_api_key(settings):
    key = settings.mineru_api_key.get_secret_value().strip()
    if not key and settings.mineru_api_key_file:
        path = settings.mineru_api_key_file
        if not path.is_absolute():
            path = ROOT / path
        try:
            key = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            raise MinerUError("MinerU credential file is missing or unreadable") from None
        if "\n" in key or key.startswith("MINERU_API_"):
            from dotenv import dotenv_values

            key = (dotenv_values(stream=io.StringIO(key)).get("MINERU_API_KEY") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.+/=-]{32,512}", key):
        raise MinerUError("Configure a valid MINERU_API_KEY or MINERU_API_KEY_FILE")
    return key


def namespace_dir(source, settings):
    root = settings.parsed_document_dir.resolve()
    target = (root / sha(str(Path(source).resolve()).encode())).resolve()
    if target.parent != root:
        raise MinerUError("Parsed artifact path leaves configured directory")
    return target


def purge_parsed_artifacts(source, settings):
    # Check the absolute resolved target before recursive deletion on Windows.
    target = namespace_dir(source, settings)
    if target.exists():
        shutil.rmtree(target)


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(value)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def object_value(value, name):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise MinerUError(f"Invalid MinerU {name} JSON") from None
    if not isinstance(value, dict):
        raise MinerUError(f"Missing MinerU {name} object")
    return value


def block_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(block_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("content", "text", "html", "latex"):
            if key in value:
                return block_text(value[key])
        return "\n".join(
            block_text(value[key])
            for key in ("children", "blocks", "caption", "body")
            if key in value
        )
    return ""


def normalize_result(
    payload, source, source_sha, submitted_suffix, expected_version, artifacts_dir
):
    if not isinstance(payload, dict):
        raise MinerUError("Invalid MinerU result object")
    files = payload.get("files")
    if (
        payload.get("status") != "completed"
        or not isinstance(files, list)
        or len(files) != 1
        or not isinstance(files[0], dict)
        or files[0].get("status") != "completed"
    ):
        raise MinerUError("MinerU job did not complete successfully")
    content = object_value(files[0].get("content"), "file content")
    middle = object_value(content.get("middle_json"), "middle_json")
    structured = object_value(content.get("structured_content"), "structured_content")
    markdown = content.get("markdown")
    if not isinstance(markdown, str):
        raise MinerUError("Missing MinerU markdown result")
    if (
        middle.get("schema") != "docvortex.middle"
        or middle.get("schema_version") != "2.0"
        or middle.get("is_full_document") is not True
    ):
        raise MinerUError("Unsupported or incomplete MinerU document schema")
    metadata = object_value(middle.get("metadata"), "metadata")
    producer = object_value(metadata.get("producer"), "producer")
    properties = object_value(metadata.get("document", {}), "document properties")
    if producer.get("name") != "mineru" or producer.get("version") != expected_version:
        raise MinerUError(
            "MinerU producer version mismatch; verify schema before changing expected version"
        )
    physical_pdf = (
        source.suffix.lower() == ".pdf" and properties.get("page_count_kind") == "physical"
    )
    raw_pages = middle.get("pages")
    if not isinstance(raw_pages, list):
        raise MinerUError("Missing MinerU page structure")
    pages, seen = [], set()
    for page in raw_pages:
        if not isinstance(page, dict):
            raise MinerUError("Invalid MinerU page object")
        idx = page.get("page_idx")
        if (
            type(idx) is not int
            or idx < 0
            or idx in seen
            or not isinstance(page.get("blocks"), list)
        ):
            raise MinerUError("Invalid MinerU page locator")
        seen.add(idx)
        number = idx + 1 if physical_pdf else None
        blocks = []
        for position, raw in enumerate(page["blocks"]):
            if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
                raise MinerUError("Invalid MinerU block structure")
            bbox = raw.get("bbox")
            if bbox is not None and (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or not all(type(v) in {float, int} and math.isfinite(v) for v in bbox)
            ):
                raise MinerUError("Invalid MinerU block bounding box")
            level = raw.get("level")
            if level is not None and (type(level) is not int or level < 0):
                raise MinerUError("Invalid MinerU heading level")
            blocks.append(
                ParsedBlock(
                    f"p{idx}:b{position}",
                    raw["type"],
                    block_text(raw).strip(),
                    idx,
                    number,
                    tuple(bbox) if bbox is not None else None,
                    level,
                    raw,
                )
            )
        pages.append(ParsedPage(idx, number, tuple(blocks)))
    return ParsedDocument(
        str(source.resolve()),
        source_sha,
        source.suffix.lower(),
        submitted_suffix,
        producer["version"],
        markdown,
        middle,
        structured,
        tuple(pages),
        str(artifacts_dir),
    )


class MinerUParser:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.base_url = settings.mineru_api_url.strip().rstrip("/")
        same_origin_url(self.base_url, "/v1/health")
        parts = urlsplit(self.base_url)
        if parts.query or parts.path not in {"", "/"}:
            raise MinerUError("MINERU_API_URL must be a service root before /v1")
        self.key = read_api_key(settings)
        self.transport = transport
        self.last_cache_hit = False

    def _prepare(self, path, data):
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError("Unsupported document format for MinerU")
        if suffix in {".md", ".txt"}:
            text = data.decode("utf-8-sig")
            body = (
                MarkdownIt("commonmark", {"html": False}).enable("table").render(text)
                if suffix == ".md"
                else f"<pre>{html.escape(text)}</pre>"
            )
            data = (
                "<!doctype html><html><head><meta charset='utf-8'></head><body>"
                + body
                + "</body></html>"
            ).encode()
            return path.stem + ".html", data, ".html", "flash"
        return (
            path.name,
            data,
            suffix,
            "flash" if suffix in NATIVE_SUFFIXES else self.settings.mineru_tier,
        )

    def _request(self, client, method, url, deadline, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MinerUError("MinerU parsing deadline exceeded")
        try:
            with client.stream(
                method,
                url,
                timeout=httpx.Timeout(min(60, remaining), connect=min(10, remaining)),
                **kwargs,
            ) as response:
                if response.status_code not in {200, 202}:
                    raise MinerUError(f"MinerU HTTP status {response.status_code}")
                body = bytearray()
                for part in response.iter_bytes():
                    body.extend(part)
                    if len(body) > self.settings.mineru_max_response_bytes:
                        raise MinerUError("MinerU response exceeds configured size limit")
                    if time.monotonic() > deadline:
                        raise MinerUError("MinerU parsing deadline exceeded")
                try:
                    payload = json.loads(body)
                except ValueError:
                    raise MinerUError("MinerU returned invalid JSON") from None
                if not isinstance(payload, dict):
                    raise MinerUError("MinerU returned an invalid response object")
                return response.status_code, payload
        except httpx.HTTPError:
            raise MinerUError("MinerU transport request failed") from None

    def parse(self, path, *, cache_only=False):
        path = Path(path).resolve()
        data = path.read_bytes()
        filename, submitted, suffix, tier = self._prepare(path, data)
        fingerprint = {
            "source_sha256": sha(data),
            "source_suffix": path.suffix.lower(),
            "submitted_suffix": suffix,
            "adapter": ADAPTER_VERSION,
            "api_url": self.base_url,
            "version": self.settings.mineru_expected_version,
            "tier": tier,
            "ocr_mode": self.settings.mineru_ocr_mode,
        }
        directory = namespace_dir(path, self.settings) / sha(json_bytes(fingerprint))
        with _locks_guard:
            lock = _locks.setdefault(str(directory), threading.Lock())
        with lock:
            self.last_cache_hit = False
            try:
                manifest = json.loads((directory / "manifest.json").read_bytes())
                if manifest["fingerprint"] != fingerprint:
                    raise ValueError("Cache fingerprint mismatch")
                for name in (
                    "response.json",
                    "middle_json.json",
                    "structured_content.json",
                    "document.md",
                ):
                    if sha((directory / name).read_bytes()) != manifest["artifacts"][name]:
                        raise ValueError("Cache checksum mismatch")
                payload = json.loads((directory / "response.json").read_bytes())
                document = normalize_result(
                    payload,
                    path,
                    sha(data),
                    suffix,
                    self.settings.mineru_expected_version,
                    directory,
                )
                self.last_cache_hit = True
                return document
            except (OSError, ValueError, KeyError, TypeError, MinerUError):
                pass  # Missing/invalid MinerU cache is reparsed remotely, never by a legacy parser.
            if cache_only:
                raise MinerUError(
                    "No valid MinerU cache for this source; cache-only parsing made no remote request"
                )
            deadline = time.monotonic() + self.settings.mineru_parse_timeout_seconds
            with httpx.Client(
                base_url=self.base_url,
                headers={"Authorization": "Bearer " + self.key},
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                code, payload = self._request(
                    client,
                    "POST",
                    "/v1/file_parse",
                    deadline,
                    params={
                        "tier": tier,
                        "ocr_mode": self.settings.mineru_ocr_mode,
                        "wait_timeout": min(
                            30, max(1, int(self.settings.mineru_parse_timeout_seconds / 2))
                        ),
                        "output_formats": ["markdown", "middle_json", "structured_content"],
                    },
                    files={
                        "files": (
                            filename,
                            submitted,
                            mimetypes.guess_type(filename)[0] or "application/octet-stream",
                        )
                    },
                )
                if code == 202:
                    status_url = same_origin_url(self.base_url, payload.get("status_url"))
                    result_url = same_origin_url(self.base_url, payload.get("result_url"))
                    atomic_write(directory / "pending.json", json_bytes(payload))
                    while True:
                        _, status = self._request(client, "GET", status_url, deadline)
                        state = status.get("status")
                        if state in {"completed", "partial", "failed", "canceled"}:
                            break
                        if state not in {"queued", "running"}:
                            raise MinerUError("MinerU returned an unknown task status")
                        time.sleep(
                            min(
                                self.settings.mineru_poll_interval_seconds,
                                max(0, deadline - time.monotonic()),
                            )
                        )
                    _, payload = self._request(client, "GET", result_url, deadline)
            atomic_write(directory / "response.json", json_bytes(payload))
            document = normalize_result(
                payload, path, sha(data), suffix, self.settings.mineru_expected_version, directory
            )
            artifacts = {
                "response.json": json_bytes(payload),
                "middle_json.json": json_bytes(document.middle_json),
                "structured_content.json": json_bytes(document.structured_content),
                "document.md": document.markdown.encode(),
            }
            for name, value in artifacts.items():
                atomic_write(directory / name, value)
            atomic_write(
                directory / "manifest.json",
                json_bytes(
                    {
                        "fingerprint": fingerprint,
                        "source": str(path),
                        "artifacts": {name: sha(value) for name, value in artifacts.items()},
                    }
                ),
            )
            (directory / "pending.json").unlink(missing_ok=True)
            return document
