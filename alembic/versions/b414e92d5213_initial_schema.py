"""initial schema

Revision ID: b414e92d5213
Revises:
Create Date: 2026-04-19 23:48:44.608579

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b414e92d5213"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("crawl_config", postgresql.JSON(), server_default="{}"),
        sa.Column("is_active", sa.Integer(), server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "raw_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id"),
            nullable=False,
        ),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(50), server_default="text/html"),
        sa.Column("title", sa.String(500)),
        sa.Column("raw_html", sa.Text()),
        sa.Column("raw_text", sa.Text()),
        sa.Column("s3_html_key", sa.String(500)),
        sa.Column("s3_pdf_key", sa.String(500)),
        sa.Column("last_modified", sa.DateTime()),
        sa.Column("crawled_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column(
            "status",
            sa.Enum("pending", "processed", "failed", "deleted", name="document_status"),
            server_default="pending",
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column("metadata_json", postgresql.JSON(), server_default="{}"),
    )
    op.create_index("ix_raw_documents_source_url", "raw_documents", ["source_id", "url"])
    op.create_index("ix_raw_documents_content_hash", "raw_documents", ["content_hash"])
    op.create_index("ix_raw_documents_status", "raw_documents", ["status"])

    op.create_table(
        "processed_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw_documents.id"),
            nullable=False,
        ),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("total_chunks", sa.Integer()),
        sa.Column("heading_path", sa.String(1000)),
        sa.Column("token_count", sa.Integer()),
        sa.Column("embedding_id", sa.String(100)),
        sa.Column("metadata_json", postgresql.JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_processed_chunks_document", "processed_chunks", ["document_id"])
    op.create_index("ix_processed_chunks_embedding", "processed_chunks", ["embedding_id"])

    op.create_table(
        "crawl_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id"),
            nullable=False,
        ),
        sa.Column(
            "job_type",
            sa.Enum("full", "incremental", name="crawl_job_type"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("running", "completed", "failed", name="crawl_job_status"),
            server_default="running",
        ),
        sa.Column("pages_found", sa.Integer(), server_default="0"),
        sa.Column("pages_new", sa.Integer(), server_default="0"),
        sa.Column("pages_changed", sa.Integer(), server_default="0"),
        sa.Column("pages_deleted", sa.Integer(), server_default="0"),
        sa.Column("pages_errored", sa.Integer(), server_default="0"),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("error_message", sa.Text()),
        sa.Column("metadata_json", postgresql.JSON(), server_default="{}"),
    )
    op.create_index("ix_crawl_jobs_source_status", "crawl_jobs", ["source_id", "status"])


def downgrade() -> None:
    op.drop_table("crawl_jobs")
    op.drop_table("processed_chunks")
    op.drop_table("raw_documents")
    op.drop_table("sources")
    op.execute("DROP TYPE IF EXISTS crawl_job_status")
    op.execute("DROP TYPE IF EXISTS crawl_job_type")
    op.execute("DROP TYPE IF EXISTS document_status")
