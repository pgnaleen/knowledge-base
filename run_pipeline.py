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

    # Crawl only with Scrapy settings (e.g. page limit for testing)
    python run_pipeline.py --crawl-only -S CLOSESPIDER_PAGECOUNT=10
    python run_pipeline.py hdb --crawl-only -S CLOSESPIDER_PAGECOUNT=10

    # Crawl + process, skip embedding
    python run_pipeline.py --skip-embed
"""

import sys
import uuid

import structlog

# Force unbuffered stdout/stderr so logs appear immediately in Docker
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from config.logger import get_logger
from config.settings import settings

logger = get_logger("pipeline")


def _banner(title: str) -> None:
    """Print a visual stage separator banner."""
    pad = "═" * ((56 - len(title) - 2) // 2)
    print(f"\n{pad} {title} {pad}\n", flush=True)


def _print_crawl_summary(summary: list[dict]) -> None:
    """Print a formatted per-source crawl summary table."""
    if not summary:
        print("\n(no crawl data — sources may not be seeded in DB)\n", flush=True)
        return

    cols = ["source", "pages_found", "pages_new", "pages_changed", "pages_deleted", "pages_errored"]
    headers = ["Source", "Found", "New", "Updated", "Deleted", "Errored"]

    widths = [
        max(len(h), max(len(str(row[c])) for row in summary))
        for h, c in zip(headers, cols)
    ]

    def _row(values: list) -> str:
        return "  ".join(str(v).ljust(w) for v, w in zip(values, widths))

    divider = "─" * (sum(widths) + 2 * (len(widths) - 1))
    title = "CRAWL SUMMARY"
    print(f"\n{'═' * len(divider)}", flush=True)
    print(f"{title:^{len(divider)}}", flush=True)
    print(divider, flush=True)
    print(_row(headers), flush=True)
    print(divider, flush=True)
    for row in summary:
        print(_row([row[c] for c in cols]), flush=True)
    print(divider, flush=True)
    totals = [sum(row[c] for row in summary) for c in cols[1:]]
    print(_row(["TOTAL"] + totals), flush=True)
    print(f"{'═' * len(divider)}\n", flush=True)


def _print_process_summary(summary: list[dict]) -> None:
    """Print a formatted per-source process summary table."""
    if not summary:
        print("\n(no documents processed)\n", flush=True)
        return

    cols    = ["source", "docs", "chunks", "dropped", "avg_chunks", "failed"]
    headers = ["Source", "Docs", "Chunks", "Dropped", "Avg/Doc", "Failed"]

    widths = [
        max(len(h), max(len(str(row[c])) for row in summary))
        for h, c in zip(headers, cols)
    ]

    def _row(values: list) -> str:
        return "  ".join(str(v).ljust(w) for v, w in zip(values, widths))

    divider = "─" * (sum(widths) + 2 * (len(widths) - 1))
    title = "PROCESS SUMMARY"
    print(f"\n{'═' * len(divider)}", flush=True)
    print(f"{title:^{len(divider)}}", flush=True)
    print(divider, flush=True)
    print(_row(headers), flush=True)
    print(divider, flush=True)
    for row in summary:
        print(_row([row[c] for c in cols]), flush=True)
    print(divider, flush=True)
    totals_docs    = sum(r["docs"]    for r in summary)
    totals_chunks  = sum(r["chunks"]  for r in summary)
    totals_dropped = sum(r["dropped"] for r in summary)
    totals_failed  = sum(r["failed"]  for r in summary)
    avg_total      = round(totals_chunks / totals_docs, 1) if totals_docs else 0
    print(_row(["TOTAL", totals_docs, totals_chunks, totals_dropped, avg_total, totals_failed]), flush=True)
    print(f"{'═' * len(divider)}\n", flush=True)


def _parse_scrapy_settings(args: list[str]) -> tuple[dict, list[str]]:
    """Extract -S KEY=VALUE pairs from args; return (settings_dict, remaining_args)."""
    scrapy_settings: dict = {}
    remaining: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "-S" and i + 1 < len(args):
            key, _, value = args[i + 1].partition("=")
            scrapy_settings[key] = value
            i += 2
        elif args[i].startswith("-S") and "=" in args[i]:
            # handle -SKEY=VALUE form
            pair = args[i][2:]
            key, _, value = pair.partition("=")
            scrapy_settings[key] = value
            i += 1
        else:
            remaining.append(args[i])
            i += 1
    return scrapy_settings, remaining


def main():
    run_id = str(uuid.uuid4())[:8]
    structlog.contextvars.bind_contextvars(run_id=run_id)

    args = sys.argv[1:]

    scrapy_settings, args = _parse_scrapy_settings(args)

    crawl_only = "--crawl-only" in args
    process_only = "--process-only" in args
    embed_only = "--embed-only" in args
    skip_embed = "--skip-embed" in args
    purge_vectors = "--purge-vectors" in args
    source_codes = [a for a in args if not a.startswith("--")] or None

    do_crawl = not process_only and not embed_only and not purge_vectors
    do_process = not crawl_only and not embed_only and not purge_vectors
    do_embed = not crawl_only and not skip_embed and not purge_vectors

    logger.info(
        "pipeline.started",
        sources=source_codes or "all",
        crawl=do_crawl,
        process=do_process,
        embed=do_embed,
        purge=purge_vectors,
    )

    # ── Purge vectors (standalone destructive operation) ──────────────────────
    if purge_vectors:
        from embedders.pipeline import EmbeddingPipeline
        _banner("PURGE PINECONE VECTORS")
        pipeline = EmbeddingPipeline(
            openai_api_key=settings.openai_api_key or None,
            pinecone_api_key=settings.pinecone_api_key or None,
            pinecone_index=settings.pinecone_index or None,
        )
        pipeline.purge_vectors(source_codes=source_codes)
        logger.info("pipeline.done")
        return

    # ── Stage 1: Crawl ────────────────────────────────────────────────────────
    if do_crawl:
        from crawlers.runner import run_crawlers

        _banner("STAGE 1: CRAWL")
        logger.info("stage.crawl_started", sources=source_codes or "all")
        crawl_summary = run_crawlers(source_codes=source_codes, scrapy_settings=scrapy_settings)
        logger.info("stage.crawl_done")
        _print_crawl_summary(crawl_summary)

    # ── Post-crawl cleanup: delete vectors for removed pages ──────────────────
    if do_crawl:
        from embedders.pipeline import EmbeddingPipeline
        _cleanup = EmbeddingPipeline(
            openai_api_key=settings.openai_api_key or None,
            pinecone_api_key=settings.pinecone_api_key or None,
            pinecone_index=settings.pinecone_index or None,
        )
        cleaned = _cleanup.cleanup_deleted_documents(source_codes=source_codes)
        if cleaned:
            logger.info("stage.cleanup_done", docs_cleaned=cleaned)

    # ── Stage 2: Extract → Chunk → Validate → Save ────────────────────────────
    if do_process:
        from processors.runner import process_pending_documents

        _banner("STAGE 2: PROCESS")
        logger.info("stage.process_started")
        process_summary = process_pending_documents(source_codes=source_codes)
        logger.info("stage.process_done")
        _print_process_summary(process_summary)

    # ── Stage 3: Embed → Pinecone / pgvector ──────────────────────────────────
    if do_embed:
        from embedders.pipeline import EmbeddingPipeline

        _banner("STAGE 3: EMBED")
        logger.info("stage.embed_started")
        pipeline = EmbeddingPipeline(
            openai_api_key=settings.openai_api_key or None,
            pinecone_api_key=settings.pinecone_api_key or None,
            pinecone_index=settings.pinecone_index or None,
        )
        for code in (source_codes or [None]):
            stats = pipeline.embed_chunks(source_code=code)
            logger.info("stage.embed_source_done", source=code or "all", embedded=stats)
        logger.info("stage.embed_done")

    logger.info("pipeline.done")


if __name__ == "__main__":
    main()
