"""HDB (Housing & Development Board) crawler.

Config-driven via sources.yml → DB crawl_config.
No custom Python behavior — all logic delegated to BaseCrawler.
"""

from crawlers.base import BaseCrawler


class HDBSpider(BaseCrawler):
    name = "hdb"
    source_name = "hdb"
