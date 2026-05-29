import pytest

from crawlers.spiders.cpf import CPFSpider
from crawlers.spiders.hdb import HDBSpider
from crawlers.spiders.iras import IRASSpider
from crawlers.spiders.mas import MASSpider
from crawlers.spiders.ura import URASpider


@pytest.fixture
def hdb_spider():
    return HDBSpider()


@pytest.fixture
def ura_spider():
    return URASpider()


def test_hdb_spider_exists():
    spider = HDBSpider()
    assert spider.name == "hdb"
    assert spider.source_name == "hdb"


def test_hdb_spider_skips_feedback_links(hdb_spider):
    assert not hdb_spider.should_follow_link(
        "https://www.hdb.gov.sg/feedback/form", ["www.hdb.gov.sg"]
    )


def test_hdb_spider_allows_pdf_links(hdb_spider):
    assert hdb_spider.should_follow_link(
        "https://www.hdb.gov.sg/documents/guide.pdf", ["www.hdb.gov.sg"]
    )


def test_ura_spider_exists():
    spider = URASpider()
    assert spider.name == "ura"
    assert spider.source_name == "ura"


def test_ura_spider_allows_property_section(ura_spider):
    assert ura_spider.should_follow_link(
        "https://www.ura.gov.sg/Corporate/Property/Details", ["www.ura.gov.sg"]
    )


def test_ura_spider_skips_maps(ura_spider):
    assert not ura_spider.should_follow_link("https://www.ura.gov.sg/maps/page", ["www.ura.gov.sg"])


def test_iras_spider_exists():
    spider = IRASSpider()
    assert spider.name == "iras"
    assert spider.source_name == "iras"


def test_mas_spider_exists():
    spider = MASSpider()
    assert spider.name == "mas"
    assert spider.source_name == "mas"


def test_cpf_spider_exists():
    spider = CPFSpider()
    assert spider.name == "cpf"
    assert spider.source_name == "cpf"


def test_cpf_spider_allows_home_ownership():
    cpf_spider = CPFSpider()
    assert cpf_spider.should_follow_link(
        "https://www.cpf.gov.sg/member/home-ownership/details", ["www.cpf.gov.sg"]
    )


def test_cpf_spider_skips_healthcare():
    cpf_spider = CPFSpider()
    assert not cpf_spider.should_follow_link(
        "https://www.cpf.gov.sg/member/healthcare/page", ["www.cpf.gov.sg"]
    )
