"""URA (Urban Redevelopment Authority) crawler.

Config-driven via sources.yml → DB crawl_config.
No custom Python behavior — all logic delegated to BaseCrawler.
"""

from crawlers.base import BaseCrawler


class URASpider(BaseCrawler):
    name = "ura"
    source_name = "ura"
