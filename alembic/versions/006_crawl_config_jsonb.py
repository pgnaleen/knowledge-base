"""Migrate crawl_config from JSON to JSONB with GIN indexing.

Revision ID: 006
Revises: 005
Create Date: 2026-05-19 00:00:00.000000

JSON → JSONB is safe, in-place, preserves all data.
JSONB enables operator queries (@>, ?, ?) and better compression.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Cast JSON → JSONB in-place. Safe operation.
    op.execute(
        sa.text(
            "ALTER TABLE sources ALTER COLUMN crawl_config TYPE JSONB USING crawl_config::JSONB"
        )
    )

    # Add GIN index for operator queries (GenericSpider will use @> filters).
    op.create_index(
        "ix_sources_crawl_config_gin",
        "sources",
        ["crawl_config"],
        postgresql_using="GIN",
    )


def downgrade() -> None:
    # Remove GIN index.
    op.drop_index("ix_sources_crawl_config_gin", table_name="sources")

    # Cast JSONB → JSON (reverse).
    op.execute(
        sa.text(
            "ALTER TABLE sources ALTER COLUMN crawl_config TYPE JSON USING crawl_config::JSON"
        )
    )
