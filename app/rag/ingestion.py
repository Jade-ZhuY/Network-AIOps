import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str | None
    page: int | None
    source: str
    document_version: str
    updated_at: str
    access_scope: tuple[str, ...]
    text: str
    parser: str


def parse_document(path: Path, metadata: dict, chunk_size=700, overlap=100) -> list[Chunk]:
    if chunk_size < 50 or not 0 <= overlap < chunk_size:
        raise ValueError("Invalid chunk dimensions")
    if path.suffix.lower() == ".pdf":
        pieces = [
            (None, i + 1, page.extract_text() or "") for i, page in enumerate(PdfReader(path).pages)
        ]
        parser = "pypdf"
    elif path.suffix.lower() in (".md", ".txt"):
        content = path.read_text(encoding="utf-8-sig")
        pieces = []
        section = None
        lines = []
        for line in content.splitlines():
            if re.match(r"^#{1,6}\s+", line):
                if lines:
                    pieces.append((section, None, "\n".join(lines)))
                section = re.sub(r"^#{1,6}\s+", "", line).strip()
                lines = []
            else:
                lines.append(line)
        if lines:
            pieces.append((section, None, "\n".join(lines)))
        parser = "markdown" if path.suffix.lower() == ".md" else "text"
    else:
        raise ValueError("Supported document formats: Markdown, UTF-8 text, PDF")
    chunks = []
    for section, page, content in pieces:
        content = content.strip()
        if not content:
            continue
        for start in range(0, len(content), chunk_size - overlap):
            text = content[start : start + chunk_size]
            identity = f"{metadata['doc_id']}:{section}:{page}:{start}:{text}"
            chunks.append(
                Chunk(
                    chunk_id=f"{metadata['doc_id']}:{hashlib.sha256(identity.encode()).hexdigest()[:16]}",
                    doc_id=metadata["doc_id"],
                    title=metadata["title"],
                    section=section,
                    page=page,
                    source=str(path.resolve()),
                    document_version=metadata["version"],
                    updated_at=metadata["updated_at"],
                    access_scope=tuple(metadata["access_scope"]),
                    text=text,
                    parser=parser,
                )
            )
            if start + chunk_size >= len(content):
                break
    return chunks


def load_documents(directory: Path):
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    chunks = []
    for filename, item in metadata.items():
        path = (directory / filename).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("Document path leaves knowledge directory")
        chunks.extend(parse_document(path, item))
    return chunks
