"""IRAS (Inland Revenue Authority of Singapore) crawler.

Config-driven via sources.yml → DB crawl_config.
No custom Python behavior — all logic delegated to BaseCrawler.
"""

from crawlers.base import BaseCrawler


class IRASSpider(BaseCrawler):
    name = "iras"
    source_name = "iras"
