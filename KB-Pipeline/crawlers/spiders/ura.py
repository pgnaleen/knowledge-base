"""URA (Urban Redevelopment Authority) crawler.

Config-driven via DB crawl_config (seeded by migration 001).
No custom Python behavior — all logic delegated to BaseCrawler.
"""

from crawlers.base import BaseCrawler


class URASpider(BaseCrawler):
    name = "ura"
    source_name = "ura"
