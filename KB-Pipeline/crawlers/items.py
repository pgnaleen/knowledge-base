import scrapy


class CrawlItem(scrapy.Item):
    url = scrapy.Field()
    source_code = scrapy.Field()
    content_type = scrapy.Field()  # "html" or "pdf"
    raw_html = scrapy.Field()
    raw_pdf = scrapy.Field()
    raw_text = scrapy.Field()         # normalized extracted text (set by S3Pipeline)
    content_hash = scrapy.Field()     # sha256 of raw_text (set by S3Pipeline)
    s3_path = scrapy.Field()          # single S3 key (set by S3Pipeline)
    extraction_flags = scrapy.Field() # warnings, word_count, is_empty, needs_ocr (set by S3Pipeline)
    needs_ocr = scrapy.Field()        # True if scanned PDF detected (set by S3Pipeline)
