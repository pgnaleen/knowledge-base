from crawlers.base import BaseCrawler
from crawlers.items import CrawlItem


class TestSpider(BaseCrawler):
    name = "test"
    source_name = "hdb"
    source_config = {
        "js_rendering": False,
        "allowed_domains": ["www.example.com"],
    }

    def get_start_urls(self):
        return ["http://www.example.com"]

    def parse_document(self, response):
        item = CrawlItem()
        item["url"] = response.url
        item["source_code"] = self.source_name
        item["content_type"] = "html"
        item["raw_html"] = response.body
        item["raw_text"] = "Test content"
        item["content_hash"] = "abc123"
        yield item


def test_should_follow_link_skips_assets():
    spider = TestSpider()
    assert not spider.should_follow_link("http://www.example.com/style.css", ["www.example.com"])
    assert not spider.should_follow_link("http://www.example.com/script.js", ["www.example.com"])
    assert not spider.should_follow_link("http://www.example.com/image.png", ["www.example.com"])


def test_should_follow_link_respects_domains():
    spider = TestSpider()
    assert not spider.should_follow_link("http://www.other.com/page", ["www.example.com"])
    assert spider.should_follow_link("http://www.example.com/page", ["www.example.com"])


def test_should_follow_link_respects_scheme():
    spider = TestSpider()
    assert not spider.should_follow_link("ftp://www.example.com/file", ["www.example.com"])
    assert spider.should_follow_link("https://www.example.com/page", ["www.example.com"])


def test_extract_main_content():
    html = """
    <html>
        <body>
            <nav>Nav content</nav>
            <main>Main content here</main>
            <footer>Footer content</footer>
        </body>
    </html>
    """
    content = BaseCrawler.extract_main_content(html)
    assert "Main content here" in content
    assert "Footer content" not in content


def test_extract_title_from_title_tag():
    html = "<html><head><title>Page Title</title></head></html>"
    title = BaseCrawler.extract_title(html)
    assert title == "Page Title"


def test_extract_title_fallback_to_h1():
    html = "<html><body><h1>Heading Title</h1></body></html>"
    title = BaseCrawler.extract_title(html)
    assert title == "Heading Title"
