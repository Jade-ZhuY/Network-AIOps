"""MinerU-only parsing followed by LangChain hierarchical parent/child splitting."""

import json
from pathlib import Path

from app.config import Settings
from app.rag.chunking import chunk_parsed_document
from app.rag.document_types import ChunkedDocuments, ParsedDocument
from app.rag.mineru_client import SUPPORTED_SUFFIXES, MinerUParser

__all__ = [
    "ChunkedDocuments",
    "ParsedDocument",
    "load_documents",
    "parse_document",
    "parse_source",
]


def parse_source(path: Path, settings=None, *, parser=None) -> ParsedDocument:
    if Path(path).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("Unsupported document format for MinerU")
    return (parser or MinerUParser(settings or Settings())).parse(path)


def parse_document(path: Path, metadata: dict, *, settings=None, parser=None) -> ChunkedDocuments:
    settings = settings or Settings()
    document = parse_source(path, settings, parser=parser)
    return chunk_parsed_document(document, metadata, settings=settings)


def load_documents(directory: Path, settings=None) -> ChunkedDocuments:
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    settings = settings or Settings()
    parser = MinerUParser(settings)
    chunks, parents = [], []
    for filename, item in metadata.items():
        path = (directory / filename).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("Document path leaves knowledge directory")
        result = parse_document(path, item, settings=settings, parser=parser)
        chunks.extend(result["children"])
        parents.extend(result["parents"])
    return {"parents": parents, "children": chunks}
