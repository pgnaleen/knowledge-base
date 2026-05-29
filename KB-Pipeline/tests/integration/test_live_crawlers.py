import pytest

from crawlers.spiders.cpf import CPFSpider
from crawlers.spiders.hdb import HDBSpider
from crawlers.spiders.iras import IRASSpider
from crawlers.spiders.mas import MASSpider
from crawlers.spiders.ura import URASpider


@pytest.mark.integration
def test_hdb_spider_has_start_urls():
    spider = HDBSpider()
    urls = spider.get_start_urls()
    assert len(urls) > 0
    assert all(url.startswith("http") for url in urls)


@pytest.mark.integration
def test_ura_spider_has_start_urls():
    spider = URASpider()
    urls = spider.get_start_urls()
    assert len(urls) > 0


@pytest.mark.integration
def test_iras_spider_has_start_urls():
    spider = IRASSpider()
    urls = spider.get_start_urls()
    assert len(urls) > 0


@pytest.mark.integration
def test_mas_spider_has_start_urls():
    spider = MASSpider()
    urls = spider.get_start_urls()
    assert len(urls) > 0


@pytest.mark.integration
def test_cpf_spider_has_start_urls():
    spider = CPFSpider()
    urls = spider.get_start_urls()
    assert len(urls) > 0
