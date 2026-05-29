"""Consolidate to single S3 bucket: add s3_path, drop s3_html_key/s3_pdf_key/metadata_json/last_modified.

Revision ID: 003
Revises: 002
Create Date: 2026-05-06 00:00:00.000000

Migration strategy:
  - Add s3_path (nullable) and content_type columns.
  - Backfill s3_path from existing s3_html_key / s3_pdf_key with the new prefix.
    Old keys were stored WITHOUT bucket prefix (e.g. "hdb/2026-05-06/abc.html").
    New keys include the folder prefix   (e.g. "raw-html/hdb/2026-05-06/abc.html").
  - Drop the old columns.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, Sequence[str], None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns
    op.add_column("raw_documents", sa.Column("s3_path", sa.String(500), nullable=True))
    op.add_column("raw_documents", sa.Column("content_type", sa.String(20), nullable=True))

    # Backfill s3_path from old split keys, adding the folder prefix
    op.execute(
        """
        UPDATE raw_documents
        SET
            s3_path = CASE
                WHEN s3_html_key IS NOT NULL THEN 'raw-html/' || s3_html_key
                WHEN s3_pdf_key  IS NOT NULL THEN 'raw-pdf/'  || s3_pdf_key
                ELSE NULL
            END,
            content_type = CASE
                WHEN s3_html_key IS NOT NULL THEN 'html'
                WHEN s3_pdf_key  IS NOT NULL THEN 'pdf'
                ELSE NULL
            END
        """
    )

    # Drop the old columns
    op.drop_column("raw_documents", "s3_html_key")
    op.drop_column("raw_documents", "s3_pdf_key")
    op.drop_column("raw_documents", "metadata_json")
    op.drop_column("raw_documents", "last_modified")


def downgrade() -> None:
    op.add_column("raw_documents", sa.Column("last_modified", sa.DateTime(), nullable=True))
    op.add_column("raw_documents", sa.Column("metadata_json", sa.dialects.postgresql.JSON(), server_default="{}"))
    op.add_column("raw_documents", sa.Column("s3_pdf_key", sa.String(500), nullable=True))
    op.add_column("raw_documents", sa.Column("s3_html_key", sa.String(500), nullable=True))

    # Restore old keys by stripping the prefix
    op.execute(
        """
        UPDATE raw_documents
        SET
            s3_html_key = CASE WHEN s3_path LIKE 'raw-html/%' THEN substr(s3_path, 9) ELSE NULL END,
            s3_pdf_key  = CASE WHEN s3_path LIKE 'raw-pdf/%'  THEN substr(s3_path, 8) ELSE NULL END
        """
    )

    op.drop_column("raw_documents", "content_type")
    op.drop_column("raw_documents", "s3_path")
