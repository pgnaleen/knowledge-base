"""CPF (CPF Board) crawler.

Config-driven via DB crawl_config (seeded by migration 001).
No custom Python behavior — all logic delegated to BaseCrawler.
The playwright_wait_event is set to "networkidle" in DB config (CPF is a React SPA).
"""

from crawlers.base import BaseCrawler


class CPFSpider(BaseCrawler):
    name = "cpf"
    source_name = "cpf"
