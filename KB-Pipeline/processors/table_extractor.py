"""Table extraction from HTML and PDF content."""

import io
from typing import Any

from bs4 import Tag

from config.logger import get_logger
from processors.models import ExtractedTable

logger = get_logger("table_extractor")


class TableExtractor:
    """Extracts structured tables from HTML nodes and PDF bytes.

    HTML tables are parsed via BeautifulSoup. PDF tables use pdfplumber's
    `extract_tables()`. Both return a list of `ExtractedTable` objects that
    can be serialised to Markdown via `to_markdown()`.
    """

    def extract_from_html(self, node: Any) -> list[ExtractedTable]:
        """Extract all tables from a BeautifulSoup content node."""
        if node is None:
            return []

        results: list[ExtractedTable] = []
        for table_index, table_tag in enumerate(node.find_all("table")):
            extracted = self._parse_html_table(table_tag)
            if extracted is not None:
                results.append(extracted)
                logger.debug(
                    "table.found_html_detail",
                    index=table_index,
                    caption=extracted.caption or "untitled",
                    rows=len(extracted.rows),
                    cols=len(extracted.headers),
                )

        logger.info("table.found_html", count=len(results))
        return results

    def extract_from_pdf(self, pdf_bytes: bytes) -> list[ExtractedTable]:
        """Extract all tables from a PDF using pdfplumber."""
        if not pdf_bytes:
            return []

        import pdfplumber

        results: list[ExtractedTable] = []
        table_index = 0
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page_index, page in enumerate(pdf.pages):
                    page_number = page_index + 1
                    raw_tables = page.extract_tables() or []
                    for raw in raw_tables:
                        extracted = self._parse_pdf_table(raw, page_number)
                        if extracted is not None:
                            results.append(extracted)
                            logger.debug(
                                "table.found_pdf_detail",
                                index=table_index,
                                page=page_number,
                                rows=len(extracted.rows),
                                cols=len(extracted.headers),
                            )
                            table_index += 1
        except Exception as exc:
            logger.warning("table_extractor.pdf_failed", error=str(exc))

        logger.info("table.found_pdf", count=len(results))
        return results

    @staticmethod
    def to_markdown(table: ExtractedTable) -> str:
        """Serialise an ExtractedTable to GitHub-flavoured Markdown."""
        if not table.rows and not table.headers:
            return ""

        def escape(cell: str) -> str:
            return cell.replace("|", "\\|").replace("\n", " ")

        col_count = (
            len(table.headers)
            if table.headers
            else max((len(r) for r in table.rows), default=0)
        )
        if col_count == 0:
            return ""

        headers = (
            table.headers
            if table.headers
            else [f"Col {i + 1}" for i in range(col_count)]
        )
        if len(headers) < col_count:
            headers = headers + [""] * (col_count - len(headers))

        lines: list[str] = []
        if table.caption:
            lines.append(f"**Table: {escape(table.caption)}**")
        lines.append("| " + " | ".join(escape(h) for h in headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in table.rows:
            padded = list(row) + [""] * (col_count - len(row))
            lines.append("| " + " | ".join(escape(str(c)) for c in padded) + " |")

        return "\n".join(lines)

    def _parse_html_table(self, table_tag: Tag) -> ExtractedTable | None:
        caption = ""
        caption_tag = table_tag.find("caption")
        if caption_tag:
            caption = caption_tag.get_text(strip=True)

        source_tag = self._table_source_tag(table_tag)
        headers: list[str] = []
        rows: list[list[str]] = []

        thead = table_tag.find("thead")
        tbody = table_tag.find("tbody")

        if thead:
            first_row = thead.find("tr")
            if first_row:
                headers = [
                    td.get_text(separator=" ", strip=True)
                    for td in first_row.find_all(["th", "td"])
                ]
            data_rows_parent = tbody if tbody else table_tag
            for tr in data_rows_parent.find_all("tr"):
                row = [
                    td.get_text(separator=" ", strip=True)
                    for td in tr.find_all(["td", "th"])
                ]
                if any(cell for cell in row):
                    rows.append(row)
        else:
            all_rows = (tbody if tbody else table_tag).find_all("tr")
            if not all_rows:
                return None
            first_tr = all_rows[0]
            first_cells = first_tr.find_all(["th", "td"])
            if first_cells and all(c.name == "th" for c in first_cells):
                headers = [c.get_text(separator=" ", strip=True) for c in first_cells]
                data_rows = all_rows[1:]
            else:
                data_rows = all_rows

            for tr in data_rows:
                row = [
                    td.get_text(separator=" ", strip=True)
                    for td in tr.find_all(["td", "th"])
                ]
                if any(cell for cell in row):
                    rows.append(row)

        if not rows and not headers:
            return None
        if all(not cell for row in rows for cell in row):
            return None

        return ExtractedTable(
            headers=headers,
            rows=rows,
            caption=caption,
            page_number=0,
            source_tag=source_tag,
        )

    @staticmethod
    def _parse_pdf_table(
        raw: list[list[str | None]], page_number: int
    ) -> ExtractedTable | None:
        if not raw:
            return None

        def clean(cell: str | None) -> str:
            if cell is None:
                return ""
            return str(cell).replace("\n", " ").strip()

        cleaned = [[clean(c) for c in row] for row in raw]
        if all(not cell for row in cleaned for cell in row):
            return None

        headers = cleaned[0] if cleaned else []
        rows = cleaned[1:] if len(cleaned) > 1 else []
        if not rows and headers:
            rows = [headers]
            headers = []

        return ExtractedTable(
            headers=headers,
            rows=rows,
            caption="",
            page_number=page_number,
            source_tag="",
        )

    @staticmethod
    def _table_source_tag(table_tag: Tag) -> str:
        tag_id = table_tag.get("id", "")
        if tag_id:
            return f"table#{tag_id}"
        classes = table_tag.get("class") or []
        if classes:
            return f"table.{classes[0]}"
        return "table"
