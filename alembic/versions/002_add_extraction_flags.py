"""Add needs_ocr and extraction_flags columns to raw_documents.

Revision ID: 002
Revises: 001
Create Date: 2026-05-06 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, Sequence[str], None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_documents",
        sa.Column("needs_ocr", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "raw_documents",
        sa.Column("extraction_flags", postgresql.JSON(), server_default="{}"),
    )
    op.create_index("ix_raw_documents_needs_ocr", "raw_documents", ["needs_ocr"])


def downgrade() -> None:
    op.drop_index("ix_raw_documents_needs_ocr", table_name="raw_documents")
    op.drop_column("raw_documents", "extraction_flags")
    op.drop_column("raw_documents", "needs_ocr")
