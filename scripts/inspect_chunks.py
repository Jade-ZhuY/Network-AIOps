"""Export both levels from the configured MinerU + LangChain splitting pipeline."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.config import ROOT, Settings
from app.rag.chunking import chunk_parsed_document, chunker_config
from app.rag.ingestion import parse_source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "langchain-chunks.json")
    args = parser.parse_args()
    settings = Settings()
    document = parse_source(args.input, settings)
    metadata = {
        "doc_id": "inspect-" + args.input.stem,
        "title": args.input.stem,
        "version": "inspection",
        "updated_at": datetime.fromtimestamp(args.input.stat().st_mtime, UTC).isoformat(),
        "access_scope": ["inspection"],
    }
    chunks = chunk_parsed_document(document, metadata, settings=settings)
    result = {
        "parameters": chunker_config(settings),
        "source": document.source,
        "parser": document.parser,
        "parent_count": len(chunks["parents"]),
        "child_count": len(chunks["children"]),
        "parents": [parent.model_dump(mode="json") for parent in chunks["parents"]],
        "children": [child.model_dump(mode="json") for child in chunks["children"]],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "parent_count": result["parent_count"],
                "child_count": result["child_count"],
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
