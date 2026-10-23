"""Parse only: persist MinerU artifacts before deciding on a structural Chunker."""

import argparse
import json
from collections import Counter
from pathlib import Path

from app.config import Settings
from app.rag.mineru_client import MinerUParser


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    client = MinerUParser(Settings())
    result = client.parse(args.input)
    print(
        json.dumps(
            {
                "parser": result.parser,
                "source": result.source,
                "source_sha256": result.source_sha256,
                "page_count": len(result.pages),
                "block_types": dict(
                    Counter(block.block_type for page in result.pages for block in page.blocks)
                ),
                "cache_hit": client.last_cache_hit,
                "artifacts_dir": result.artifacts_dir,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
