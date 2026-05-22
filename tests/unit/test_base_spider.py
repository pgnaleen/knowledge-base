from crawlers.base import BaseCrawler
from crawlers.items import CrawlItem


class TestSpider(BaseCrawler):
    name = "test"
    source_name = "test"
    source_config = {
        "start_urls": ["http://www.example.com"],
        "allowed_domains": ["www.example.com"],
        "js_rendering": False,
        "target_prefixes": [],
        "skip_prefixes": [],
        "blocked_subdomains": [],
        "min_content_length": 100,
        "content_selectors": [],
        "content_keywords_filter": None,
    }


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
    spider = TestSpider()
    html = """
    <html>
        <body>
            <nav>Nav content</nav>
            <main>Main content here</main>
            <footer>Footer content</footer>
        </body>
    </html>
    """
    content = spider.extract_main_content(html)
    assert "Main content here" in content
    assert "Footer content" not in content


def test_extract_main_content_uses_content_selectors():
    spider = TestSpider()
    spider.source_config["content_selectors"] = ["div.hdb-content"]
    html = """
    <html>
        <body>
            <main>Ignored content</main>
            <div class="hdb-content">Selected content</div>
        </body>
    </html>
    """
    content = spider.extract_main_content(html)
    assert "Selected content" in content
    assert "Ignored content" not in content


def test_should_follow_link_respects_target_prefixes():
    spider = TestSpider()
    spider.source_config["target_prefixes"] = ["/buying-a-flat", "/renting"]
    assert spider.should_follow_link("http://www.example.com/buying-a-flat/page", ["www.example.com"])
    assert spider.should_follow_link("http://www.example.com/renting/page", ["www.example.com"])
    assert not spider.should_follow_link("http://www.example.com/other/page", ["www.example.com"])


def test_should_follow_link_respects_skip_prefixes():
    spider = TestSpider()
    spider.source_config["skip_prefixes"] = ["/feedback", "/careers"]
    assert not spider.should_follow_link("http://www.example.com/feedback", ["www.example.com"])
    assert not spider.should_follow_link("http://www.example.com/careers/page", ["www.example.com"])
    assert spider.should_follow_link("http://www.example.com/page", ["www.example.com"])


def test_should_follow_link_respects_blocked_subdomains():
    spider = TestSpider()
    spider.source_config["blocked_subdomains"] = ["assets.example.com"]
    assert not spider.should_follow_link("http://assets.example.com/file.js", ["www.example.com", "assets.example.com"])
    assert spider.should_follow_link("http://www.example.com/page", ["www.example.com"])


def test_extract_title_from_title_tag():
    html = "<html><head><title>Page Title</title></head></html>"
    title = BaseCrawler.extract_title(html)
    assert title == "Page Title"


def test_extract_title_fallback_to_h1():
    html = "<html><body><h1>Heading Title</h1></body></html>"
    title = BaseCrawler.extract_title(html)
    assert title == "Heading Title"


def test_content_keywords_filter():
    spider = TestSpider()
    spider.source_config["content_keywords_filter"] = ["property", "mortgage"]

    # Test with matching content
    html_matching = "<html><body>Property-related content about mortgages</body></html>"
    content = spider.extract_main_content(html_matching)
    assert len(content) > 0

    # The keyword filter is applied in parse_document, not extract_main_content
    # This test just ensures extract works as expected


def test_min_content_length():
    spider = TestSpider()
    spider.source_config["min_content_length"] = 100

    # Short content should be filtered by parse_document (not extract_main_content)
    html_short = "<html><body>Short</body></html>"
    content = spider.extract_main_content(html_short)
    assert len(content) < 100
