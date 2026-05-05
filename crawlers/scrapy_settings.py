from config.settings import settings

BOT_NAME = "kb_pipeline"
SPIDER_MODULES = ["crawlers.spiders"]
NEWSPIDER_MODULE = "crawlers.spiders"

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}

CONCURRENT_REQUESTS = 16
CONCURRENT_REQUESTS_PER_DOMAIN = 4
DOWNLOAD_DELAY = settings.crawl_delay
RANDOMIZE_DOWNLOAD_DELAY = True

ROBOTSTXT_OBEY = settings.crawl_respect_robots_txt
USER_AGENT = settings.crawl_user_agent

RETRY_ENABLED = True
RETRY_TIMES = settings.crawl_max_retries
RETRY_HTTP_CODES = [429, 500, 502, 503, 504]

PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True, "args": ["--no-sandbox"]}
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 60_000
PLAYWRIGHT_MAX_PAGES_IN_PARALLEL = 4

ITEM_PIPELINES = {
    "crawlers.pipelines.S3Pipeline": 100,
    "crawlers.pipelines.PostgresPipeline": 200,
}

LOG_LEVEL = settings.log_level
FEED_EXPORT_ENCODING = "utf-8"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TELNETCONSOLE_ENABLED = False
