"""
Table Extractor - Shared utility for formatting extracted tables.

Provides standard markdown formatting for tables extracted from both
HTML and PDF documents. This ensures structured data is represented
consistently for the chunker and language models.
"""

from config.logger import get_logger

logger = get_logger("table_extractor")


class TableExtractor:
    """Helper to convert raw 2D tabular data into Markdown tables."""

    @staticmethod
    def format_markdown_table(rows: list[list[str]]) -> str:
        """
        Convert a 2D list of strings into a Markdown formatted table.
        
        Args:
            rows: 2D list of strings, where rows[0] is typically the header.
                  Empty rows or fully empty cells are handled.
                  
        Returns:
            A string containing the Markdown table.
        """
        if not rows:
            return ""

        # Clean cells: replace newlines with spaces to avoid breaking table layout
        cleaned_rows = []
        for row in rows:
            cleaned_row = []
            for cell in row:
                cell_text = str(cell).strip() if cell is not None else ""
                cell_text = cell_text.replace("\n", " ").replace("\r", " ")
                cleaned_row.append(cell_text)
            
            # Only keep the row if it has at least one non-empty cell
            if any(cleaned_row):
                cleaned_rows.append(cleaned_row)

        if not cleaned_rows:
            return ""

        # Ensure all rows have the same number of columns (pad with empty strings)
        max_cols = max(len(row) for row in cleaned_rows)
        for row in cleaned_rows:
            while len(row) < max_cols:
                row.append("")

        # Formatting
        lines = []
        
        # Add header
        header = cleaned_rows[0]
        lines.append("| " + " | ".join(header) + " |")
        
        # Add separator
        separator = ["---"] * max_cols
        lines.append("| " + " | ".join(separator) + " |")
        
        # Add body
        for row in cleaned_rows[1:]:
            lines.append("| " + " | ".join(row) + " |")

        return "\n" + "\n".join(lines) + "\n"
