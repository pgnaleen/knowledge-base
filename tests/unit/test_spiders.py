"""Unit tests for individual crawler spiders."""

from unittest.mock import MagicMock

import httpx
import pytest

from crawlers.spiders.hdb_spider import HDBCrawler
from crawlers.spiders.ura_spider import URACrawler
from crawlers.spiders.iras_spider import IRASCrawler
from crawlers.spiders.mas_spider import MASCrawler
from crawlers.spiders.cpf_spider import CPFCrawler


def make_config(base_url, start_urls, allowed_domains):
    return {
        "base_url": base_url,
        "start_urls": start_urls,
        "allowed_domains": allowed_domains,
        "crawl_delay": 0.01,
    }


def make_html_response(html: str, url: str = "https://example.com") -> httpx.Response:
    """Create a mock httpx.Response with HTML content."""
    return httpx.Response(
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        text=html,
        request=httpx.Request("GET", url),
    )


def make_pdf_response(content: bytes, url: str = "https://example.com/doc.pdf") -> httpx.Response:
    return httpx.Response(
        status_code=200,
        headers={"content-type": "application/pdf"},
        content=content,
        request=httpx.Request("GET", url),
    )


# ─── HDB Spider ────────────────────────────────────────────

class TestHDBCrawler:
    def _make_crawler(self):
        config = make_config(
            "https://www.hdb.gov.sg",
            ["https://www.hdb.gov.sg/residential/buying-a-flat"],
            ["www.hdb.gov.sg"],
        )
        return HDBCrawler(config)

    def test_should_follow_residential_link(self):
        crawler = self._make_crawler()
        assert crawler.should_follow_link("https://www.hdb.gov.sg/residential/buying-a-flat/eligibility") is True

    def test_should_not_follow_careers(self):
        crawler = self._make_crawler()
        assert crawler.should_follow_link("https://www.hdb.gov.sg/careers") is False

    def test_should_not_follow_contact(self):
        crawler = self._make_crawler()
        assert crawler.should_follow_link("https://www.hdb.gov.sg/contact-us") is False

    def test_parse_html_page(self):
        crawler = self._make_crawler()
        html = """
        <html><head><title>HDB Eligibility</title></head>
        <body><main><h1>Eligibility</h1>
        <p>You must be at least 21 years old to buy an HDB flat. Singapore Citizens and
        Permanent Residents may apply for a new flat from HDB or buy a resale flat on the
        open market. Various eligibility conditions apply depending on the scheme.</p>
        </main></body></html>
        """
        response = make_html_response(html, "https://www.hdb.gov.sg/residential/buying-a-flat/eligibility")
        results = crawler.parse_page("https://www.hdb.gov.sg/residential/buying-a-flat/eligibility", response)
        assert len(results) == 1
        assert results[0].title == "HDB Eligibility"
        assert results[0].metadata["source"] == "hdb"

    def test_skip_thin_page(self):
        crawler = self._make_crawler()
        html = "<html><body><p>Hi</p></body></html>"
        response = make_html_response(html)
        results = crawler.parse_page("https://www.hdb.gov.sg/residential/buying-a-flat", response)
        assert len(results) == 0


# ─── URA Spider ────────────────────────────────────────────

class TestURACrawler:
    def _make_crawler(self):
        config = make_config(
            "https://www.ura.gov.sg",
            ["https://www.ura.gov.sg/Corporate/Property"],
            ["www.ura.gov.sg"],
        )
        return URACrawler(config)

    def test_should_follow_property(self):
        crawler = self._make_crawler()
        assert crawler.should_follow_link("https://www.ura.gov.sg/Corporate/Property/Residential") is True

    def test_should_not_follow_data(self):
        crawler = self._make_crawler()
        assert crawler.should_follow_link("https://www.ura.gov.sg/Corporate/Data/something") is False

    def test_should_follow_pdf(self):
        crawler = self._make_crawler()
        assert crawler.should_follow_link("https://www.ura.gov.sg/docs/guideline.pdf") is True


# ─── IRAS Spider ───────────────────────────────────────────

class TestIRASCrawler:
    def _make_crawler(self):
        config = make_config(
            "https://www.iras.gov.sg",
            ["https://www.iras.gov.sg/taxes/stamp-duty"],
            ["www.iras.gov.sg"],
        )
        return IRASCrawler(config)

    def test_should_follow_stamp_duty(self):
        crawler = self._make_crawler()
        assert crawler.should_follow_link("https://www.iras.gov.sg/taxes/stamp-duty/for-property") is True

    def test_parse_page_with_tables(self):
        crawler = self._make_crawler()
        html = """
        <html><head><title>BSD Rates</title></head>
        <body><main>
            <h1>Buyer's Stamp Duty Rates</h1>
            <p>BSD rates for property purchases.</p>
            <table>
                <thead><tr><th>Purchase Price</th><th>Rate</th></tr></thead>
                <tbody>
                    <tr><td>First $180,000</td><td>1%</td></tr>
                    <tr><td>Next $180,000</td><td>2%</td></tr>
                </tbody>
            </table>
        </main></body></html>
        """
        response = make_html_response(html, "https://www.iras.gov.sg/taxes/stamp-duty")
        results = crawler.parse_page("https://www.iras.gov.sg/taxes/stamp-duty", response)
        assert len(results) == 1
        assert results[0].metadata["has_rate_tables"] is True
        assert len(results[0].metadata["tables"]) == 1
        assert "BSD" in results[0].metadata["tax_types"]


# ─── MAS Spider ────────────────────────────────────────────

class TestMASCrawler:
    def _make_crawler(self):
        config = make_config(
            "https://www.mas.gov.sg",
            ["https://www.mas.gov.sg/regulation"],
            ["www.mas.gov.sg"],
        )
        return MASCrawler(config)

    def test_should_follow_regulation(self):
        crawler = self._make_crawler()
        assert crawler.should_follow_link("https://www.mas.gov.sg/regulation/guidelines") is True

    def test_should_not_follow_fintech(self):
        crawler = self._make_crawler()
        assert crawler.should_follow_link("https://www.mas.gov.sg/fintech") is False

    def test_is_property_related(self):
        crawler = self._make_crawler()
        assert crawler._is_property_related("TDSR framework for housing loans") is True
        assert crawler._is_property_related("Insurance regulations update") is False

    def test_skips_non_property_content(self):
        crawler = self._make_crawler()
        html = """
        <html><head><title>Insurance Updates</title></head>
        <body><main><h1>Insurance Updates</h1><p>New insurance regulations have been released for the financial sector.</p></main></body></html>
        """
        response = make_html_response(html, "https://www.mas.gov.sg/regulation/insurance")
        results = crawler.parse_page("https://www.mas.gov.sg/regulation/insurance", response)
        assert len(results) == 0


# ─── CPF Spider ────────────────────────────────────────────

class TestCPFCrawler:
    def _make_crawler(self):
        config = make_config(
            "https://www.cpf.gov.sg",
            ["https://www.cpf.gov.sg/member/home-ownership"],
            ["www.cpf.gov.sg"],
        )
        return CPFCrawler(config)

    def test_should_follow_home_ownership(self):
        crawler = self._make_crawler()
        assert crawler.should_follow_link("https://www.cpf.gov.sg/member/home-ownership/using-cpf") is True

    def test_should_not_follow_healthcare(self):
        crawler = self._make_crawler()
        assert crawler.should_follow_link("https://www.cpf.gov.sg/member/healthcare") is False

    def test_parse_page_extracts_property_types(self):
        crawler = self._make_crawler()
        html = """
        <html><head><title>CPF for HDB</title></head>
        <body><main>
            <h1>Using CPF for HDB Flat</h1>
            <p>Singapore Citizens can use their CPF Ordinary Account to buy an HDB flat.
            Permanent Residents may also use CPF for private property purchases.</p>
        </main></body></html>
        """
        response = make_html_response(html, "https://www.cpf.gov.sg/member/home-ownership/using-cpf")
        results = crawler.parse_page("https://www.cpf.gov.sg/member/home-ownership/using-cpf", response)
        assert len(results) == 1
        assert "hdb" in results[0].metadata["property_types"]
        assert "private" in results[0].metadata["property_types"]
        assert "SC" in results[0].metadata["citizenship_types"]
        assert "PR" in results[0].metadata["citizenship_types"]
