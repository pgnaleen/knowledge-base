"""MAS (Monetary Authority of Singapore) crawler.

Config-driven via DB crawl_config (seeded by migration 001).
No custom Python behavior — all logic delegated to BaseCrawler.
The content_keywords_filter is configured in DB for property-related filtering.
"""

from crawlers.base import BaseCrawler


class MASSpider(BaseCrawler):
    name = "mas"
    source_name = "mas"
