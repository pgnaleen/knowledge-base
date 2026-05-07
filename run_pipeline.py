"""End-to-end pipeline runner: crawl → extract/chunk → embed.

Usage:
    # Run all 3 stages for all 5 sources
    python run_pipeline.py

    # Run specific sources
    python run_pipeline.py hdb iras

    # Skip crawling (process + embed already-pending documents)
    python run_pipeline.py --process-only

    # Skip crawling and processing (embed already-chunked documents)
    python run_pipeline.py --embed-only

    # Crawl only (no processing or embedding)
    python run_pipeline.py --crawl-only

    # Crawl + process, skip embedding
    python run_pipeline.py --skip-embed
"""

import sys

from config.logger import get_logger
from config.settings import settings

logger = get_logger("pipeline")


def main():
    args = sys.argv[1:]

    crawl_only = "--crawl-only" in args
    process_only = "--process-only" in args
    embed_only = "--embed-only" in args
    skip_embed = "--skip-embed" in args
    source_codes = [a for a in args if not a.startswith("--")] or None

    do_crawl = not process_only and not embed_only
    do_process = not crawl_only and not embed_only
    do_embed = not crawl_only and not skip_embed

    logger.info(
        "pipeline_starting",
        sources=source_codes or "all",
        crawl=do_crawl,
        process=do_process,
        embed=do_embed,
    )

    # ── Stage 1: Crawl ────────────────────────────────────────────────────────
    if do_crawl:
        from crawlers.runner import run_crawlers

        logger.info("stage_crawl_start", sources=source_codes or "all")
        run_crawlers(source_codes=source_codes)
        logger.info("stage_crawl_complete")

    # ── Stage 2: Extract → Chunk → Validate → Save ────────────────────────────
    if do_process:
        from processors.runner import process_pending_documents

        logger.info("stage_process_start")
        process_pending_documents()
        logger.info("stage_process_complete")

    # ── Stage 3: Embed → Pinecone / pgvector ──────────────────────────────────
    if do_embed:
        from embedders.pipeline import EmbeddingPipeline

        logger.info("stage_embed_start")
        pipeline = EmbeddingPipeline(
            openai_api_key=settings.openai_api_key or None,
            pinecone_api_key=settings.pinecone_api_key or None,
            pinecone_index=settings.pinecone_index or None,
        )
        for code in (source_codes or [None]):
            stats = pipeline.embed_chunks(source_code=code)
            logger.info("stage_embed_source_complete", source=code or "all", embedded=stats)
        logger.info("stage_embed_complete")

    logger.info("pipeline_complete")


if __name__ == "__main__":
    main()
