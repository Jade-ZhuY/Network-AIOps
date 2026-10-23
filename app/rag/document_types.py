"""MinerU input types and a native LangChain Document output contract."""

from dataclasses import dataclass
from typing import TypedDict

from langchain_core.documents import Document


@dataclass(frozen=True)
class ParsedBlock:
    block_id: str
    block_type: str
    text: str
    page_idx: int
    page_number: int | None
    bbox: tuple[float, ...] | None
    level: int | None
    raw: dict


@dataclass(frozen=True)
class ParsedPage:
    page_idx: int
    page_number: int | None
    blocks: tuple[ParsedBlock, ...]


@dataclass(frozen=True)
class ParsedDocument:
    source: str
    source_sha256: str
    source_suffix: str
    submitted_suffix: str
    parser_version: str
    markdown: str
    middle_json: dict
    structured_content: dict
    pages: tuple[ParsedPage, ...]
    artifacts_dir: str

    @property
    def parser(self):
        return f"mineru:{self.parser_version}"


class ChunkedDocuments(TypedDict):
    """A plain dict of two native Document lists, with no legacy Chunk wrapper."""

    parents: list[Document]
    children: list[Document]


def validate_parent_child(parent: Document, child: Document):
    if parent.metadata.get("chunk_type") != "parent" or child.metadata.get("chunk_type") != "child":
        raise ValueError("Expected parent and child Documents")
    if not parent.id or child.metadata.get("parent_id") != parent.id:
        raise ValueError("Invalid parent document link")
    for key in (
        "doc_id",
        "access_scope",
        "section_path",
        "page",
        "source",
        "parser",
        "document_version",
        "chunker_version",
    ):
        if child.metadata.get(key) != parent.metadata.get(key):
            raise ValueError(f"Parent/child metadata mismatch: {key}")
    if not child.page_content.strip() or child.page_content not in parent.page_content:
        raise ValueError("Child text is not present in its parent document")


def validate_documents(documents: ChunkedDocuments) -> dict[str, Document]:
    if not isinstance(documents, dict) or set(documents) != {"parents", "children"}:
        raise ValueError("Expected {'parents': list[Document], 'children': list[Document]}")
    parents, ids = {}, set()
    for kind, values in documents.items():
        if not isinstance(values, list):
            raise ValueError("Document collections must be lists")
        for document in values:
            if not isinstance(document, Document) or not document.id or document.id in ids:
                raise ValueError("Expected native Documents with unique IDs")
            if (
                document.metadata.get("chunk_type")
                != {"parents": "parent", "children": "child"}[kind]
            ):
                raise ValueError("Document kind does not match its collection")
            ids.add(document.id)
            if kind == "parents":
                parents[document.id] = document
    for child in documents["children"]:
        parent = parents.get(child.metadata.get("parent_id"))
        if parent is None:
            raise ValueError("Missing parent document")
        validate_parent_child(parent, child)
    return parents
