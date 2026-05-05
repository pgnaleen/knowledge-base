import scrapy


class CrawlItem(scrapy.Item):
    url = scrapy.Field()
    source_code = scrapy.Field()
    content_type = scrapy.Field()
    raw_html = scrapy.Field()
    raw_text = scrapy.Field()
    raw_pdf = scrapy.Field()
    content_hash = scrapy.Field()
    s3_html_key = scrapy.Field()
    s3_pdf_key = scrapy.Field()
    last_modified = scrapy.Field()
    metadata_json = scrapy.Field()
