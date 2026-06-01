"""HDB (Housing & Development Board) crawler.

Config-driven via DB crawl_config (seeded by migration 001).
No custom Python behavior — all logic delegated to BaseCrawler.
"""

from crawlers.base import BaseCrawler


class HDBSpider(BaseCrawler):
    name = "hdb"
    source_name = "hdb"
