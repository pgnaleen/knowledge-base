"""Drop heading_path from processed_chunks; drop metadata_json from crawl_jobs.

Revision ID: 004
Revises: 003
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("processed_chunks", "heading_path")
    op.drop_column("crawl_jobs", "metadata_json")


def downgrade() -> None:
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

    op.add_column(
        "processed_chunks",
        sa.Column("heading_path", sa.String(1000), nullable=True),
    )
    op.add_column(
        "crawl_jobs",
        sa.Column("metadata_json", postgresql.JSON(), server_default="{}"),
    )
