"""
Processor Runner - Entry point for the Week 2 processing pipeline.

Usage:
    python -m processors.runner                      # process all pending docs
    python -m processors.runner --source cpf         # only CPF docs
    python -m processors.runner --source iras --limit 20   # first 20 IRAS docs
    python -m processors.runner --no-embed           # chunk only, skip embeddings
"""

import argparse
import sys

from config.logger import get_logger
from processors.pipeline import ProcessingPipeline

logger = get_logger("processor_runner")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process raw crawled documents into chunks and embeddings."
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Source code to process (hdb, ura, iras, mas, cpf). "
             "Omit to process all sources.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of documents to process in this run.",
    )
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip embedding generation (chunk and save only). "
             "Useful for testing without an OpenAI API key.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    embed = not args.no_embed

    if embed:
        from config.settings import settings
        key = settings.openai_api_key
        if not key or key == "sk-your-key-here":
            print(
                "\n[!] WARNING: OPENAI_API_KEY is not set in your .env file.\n"
                "   Embeddings will be skipped automatically.\n"
                "   To generate embeddings, add your real key and re-run.\n"
            )
            embed = False

    print(f"\n{'='*55}")
    print(f"  Processing Pipeline")
    print(f"  Source  : {args.source or 'ALL'}")
    print(f"  Limit   : {args.limit or 'unlimited'}")
    print(f"  Embed   : {embed}")
    print(f"{'='*55}\n")

    pipeline = ProcessingPipeline(embed=embed)

    try:
        stats = pipeline.process_pending(
            source_code=args.source,
            limit=args.limit,
            embed=embed,
        )
    except Exception as e:
        logger.error("pipeline_crashed", error=str(e))
        print(f"\n[X] Pipeline failed: {e}")
        sys.exit(1)

    print(f"\n{'='*55}")
    print(f"  Results")
    print(f"  Documents processed : {stats['processed']}")
    print(f"  Chunks created      : {stats['chunks_created']}")
    print(f"  Documents skipped   : {stats['skipped']}")
    print(f"  Documents failed    : {stats['failed']}")
    print(f"{'='*55}\n")

    if stats["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
