"""LangChain title hierarchy -> parent length windows -> overlapping child windows."""

import hashlib
import json
from importlib.metadata import version

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.config import Settings
from app.rag.document_types import ChunkedDocuments, ParsedDocument, validate_documents
from app.security.redaction import redact_sensitive_text

CHUNKER_VERSION = "langchain-document-parent-child-token-v2"
HEADERS = [("#" * level, f"H{level}") for level in range(1, 7)]
HEADING_TYPES = {"doc_title", "paragraph_title", "chapter_title", "heading", "title"}
SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ". ", "; ", " ", ""]


def chunker_config(settings):
    return {
        "version": CHUNKER_VERSION,
        "package_version": version("langchain-text-splitters"),
        "parent_size": settings.rag_parent_chunk_size,
        "parent_overlap": settings.rag_parent_chunk_overlap,
        "child_size": settings.rag_child_chunk_size,
        "child_overlap": settings.rag_child_chunk_overlap,
        "length_unit": "tokens",
        "token_encoding": settings.rag_token_encoding,
        "headers": HEADERS,
        "separators": SEPARATORS,
        "page_boundary": True,
        "keep_separator": "end",
    }


def _identity(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:20]


def _length_splitter(size, overlap, encoding):
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=encoding,
        disallowed_special=(),
        chunk_size=size,
        chunk_overlap=overlap,
        separators=SEPARATORS,
        keep_separator="end",
        add_start_index=False,
        strip_whitespace=False,
    )


def _page_outline(page, active_headers):
    # Only actual MinerU heading blocks become Markdown headings. Carry context
    # onto the next page without joining different physical pages into one chunk.
    parts = ["#" * level + " " + title for level, title in sorted(active_headers.items())]
    blocks = {}
    for position, block in enumerate(page.blocks):
        text = redact_sensitive_text(block.text).strip()
        if not text:
            continue
        if block.block_type in HEADING_TYPES:
            level = min(6, max(1, block.level or (1 if block.block_type == "doc_title" else 2)))
            for stale in [key for key in active_headers if key >= level]:
                del active_headers[stale]
            title = " ".join(text.splitlines())
            active_headers[level] = title
            parts.append("#" * level + " " + title)
        else:
            # Feed only block references to the header splitter, then restore the
            # actual body. This preserves code indentation/HTML and prevents a
            # literal '# comment' in a text block from becoming a false heading.
            marker = f"AIOPS_BLOCK_P{page.page_idx}_B{position}"
            blocks[marker] = (text, block.block_id)
            parts.append(marker)
    return "\n\n".join(parts), blocks


def chunk_parsed_document(
    document: ParsedDocument, metadata: dict, *, settings=None
) -> ChunkedDocuments:
    settings = settings or Settings()
    config = chunker_config(settings)
    if (
        config["child_size"] < 50
        or config["child_size"] > config["parent_size"]
        or not 0 <= config["child_overlap"] < config["child_size"]
        or not 0 <= config["parent_overlap"] < config["parent_size"]
    ):
        raise ValueError("Invalid parent/child chunk dimensions")
    semantic_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=HEADERS, strip_headers=True)
    parent_splitter = _length_splitter(
        config["parent_size"], config["parent_overlap"], config["token_encoding"]
    )
    child_splitter = _length_splitter(
        config["child_size"], config["child_overlap"], config["token_encoding"]
    )
    children, parents, active_headers = [], [], {}
    for page in document.pages:
        outline, blocks = _page_outline(page, active_headers)
        sections = semantic_splitter.split_text(outline)
        for section_index, section in enumerate(sections):
            body, block_ids = [], []
            for marker in section.page_content.split():
                if marker not in blocks:
                    raise ValueError("LangChain header block mapping mismatch")
                text, block_id = blocks[marker]
                block_ids.append(block_id)
                body.append(text)
            section = Document(page_content="\n\n".join(body), metadata=section.metadata)
            path = tuple(
                section.metadata[name] for _, name in HEADERS if section.metadata.get(name)
            )
            common = [
                CHUNKER_VERSION,
                config,
                document.parser,
                metadata["doc_id"],
                page.page_idx,
                section_index,
                path,
            ]
            section.metadata.update(
                {
                    "doc_id": metadata["doc_id"],
                    "title": redact_sensitive_text(metadata["title"]),
                    "section": path[-1] if path else None,
                    "section_path": list(path),
                    "page": page.page_number,
                    "source": document.source,
                    "document_version": metadata["version"],
                    "updated_at": metadata["updated_at"],
                    "access_scope": sorted(set(metadata["access_scope"])),
                    "parser": document.parser,
                    "chunker_version": CHUNKER_VERSION,
                    "section_block_ids": block_ids,
                }
            )
            parent_documents = parent_splitter.split_documents([section])
            for parent_index, parent in enumerate(parent_documents):
                if not parent.page_content.strip():
                    continue
                parent_id = (
                    metadata["doc_id"]
                    + ":parent-"
                    + _identity([common, parent_index, parent.page_content])
                )
                parent.id = parent_id
                parent.metadata["chunk_type"] = "parent"
                parent.metadata["parent_index"] = parent_index
                parents.append(parent)
                child_documents = child_splitter.split_documents([parent])
                for child_index, child in enumerate(child_documents):
                    if not child.page_content.strip():
                        continue
                    child_id = (
                        metadata["doc_id"]
                        + ":child-"
                        + _identity([common, parent_index, child_index, child.page_content])
                    )
                    child.id = child_id
                    child.metadata.update(
                        {
                            "chunk_type": "child",
                            "parent_id": parent_id,
                            "child_index": child_index,
                        }
                    )
                    children.append(child)
    result = {"parents": parents, "children": children}
    validate_documents(result)
    return result
