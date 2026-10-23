"""Explicit fake remote results for offline tests; never used by application code."""

from pathlib import Path

from pypdf import PdfReader

from app.rag.mineru_client import MinerUError, normalize_result


def result_payload(pages=None, *, physical=True, markdown="BGP fixture"):
    if pages is None:
        pages = [
            {
                "page_idx": 0,
                "blocks": [
                    {
                        "type": "text",
                        "index": 0,
                        "bbox": [0.1, 0.1, 0.9, 0.2],
                        "content": [{"type": "text", "content": "BGP fixture"}],
                    }
                ],
            }
        ]
    middle = {
        "schema": "docvortex.middle",
        "schema_version": "2.0",
        "is_full_document": True,
        "metadata": {
            "producer": {"name": "mineru", "version": "4.0.12"},
            "document": {"page_count_kind": "physical" if physical else "logical"},
        },
        "pages": pages,
    }
    return {
        "status": "completed",
        "files": [
            {
                "status": "completed",
                "content": {
                    "markdown": markdown,
                    "middle_json": middle,
                    "structured_content": {"pages": pages, "metadata": middle["metadata"]},
                },
            }
        ],
    }


class FakeMinerUParser:
    def __init__(self, settings):
        self.settings = settings

    def parse(self, path):
        path = Path(path)
        if path.suffix.lower() == ".pdf":
            try:
                texts = [page.extract_text() or "" for page in PdfReader(path).pages]
            except Exception:
                raise MinerUError("Fake remote PDF parsing failed") from None
            pages = [
                {
                    "page_idx": idx,
                    "blocks": [
                        {"type": "text", "index": 0, "content": [{"type": "text", "content": text}]}
                    ],
                }
                for idx, text in enumerate(texts)
            ]
        else:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
            blocks, body = [], []
            for line in lines:
                if line.startswith("#") and " " in line and set(line.split(" ", 1)[0]) == {"#"}:
                    if body:
                        blocks.append(
                            {
                                "type": "text",
                                "content": [{"type": "text", "content": "\n".join(body)}],
                            }
                        )
                    body = []
                    prefix, title = line.split(" ", 1)
                    blocks.append(
                        {
                            "type": "paragraph_title",
                            "level": len(prefix),
                            "content": [{"type": "text", "content": title}],
                        }
                    )
                else:
                    body.append(line)
            if body:
                blocks.append(
                    {"type": "text", "content": [{"type": "text", "content": "\n".join(body)}]}
                )
            pages = [{"page_idx": 0, "blocks": blocks}]
        payload = result_payload(pages, physical=path.suffix.lower() == ".pdf")
        return normalize_result(
            payload,
            path,
            "fixture-sha",
            ".pdf" if path.suffix == ".pdf" else ".html",
            self.settings.mineru_expected_version,
            self.settings.parsed_document_dir,
        )
