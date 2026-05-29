"""Initial schema with all tables, pgvector support, and source seeds.

Revision ID: 001
Revises:
Create Date: 2026-05-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create sources table
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("crawl_config", postgresql.JSON(), server_default="{}"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Create raw_documents table
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
    op.create_unique_constraint(
        "uq_raw_documents_source_url",
        "raw_documents",
        ["source_id", "url"],
    )
    op.create_index("ix_raw_documents_source_url", "raw_documents", ["source_id", "url"])
    op.create_index("ix_raw_documents_content_hash", "raw_documents", ["content_hash"])
    op.create_index("ix_raw_documents_status", "raw_documents", ["status"])

    # Create processed_chunks table
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
        sa.Column("heading_path", sa.String(1000)),
        sa.Column("token_count", sa.Integer()),
        sa.Column("embedding_id", sa.String(100)),
        sa.Column("metadata_json", postgresql.JSON(), server_default="{}"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    # Add vector column using raw SQL (pgvector extension required)
    op.execute("ALTER TABLE processed_chunks ADD COLUMN embedding vector(3072)")
    # Create HNSW index on embedding column using halfvec cast
    # (vector type is limited to 2000 dims for HNSW due to PG 8KB page size;
    #  halfvec supports up to 4000 dims with negligible accuracy loss)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_processed_chunks_embedding_hnsw "
        "ON processed_chunks USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops) "
        "WITH (ef_construction = 128, m = 16)"
    )
    op.create_index("ix_processed_chunks_document", "processed_chunks", ["document_id"])
    op.create_index("ix_processed_chunks_embedding_id", "processed_chunks", ["embedding_id"])

    # Create crawl_jobs table
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

    # Pre-seed the 5 government sources
    op.execute(
        """
        INSERT INTO sources (id, name, code, base_url, is_active, created_at, updated_at)
        VALUES
            ('550e8400-e29b-41d4-a716-446655440001'::uuid, 'Housing & Development Board', 'hdb', 'https://www.hdb.gov.sg', true, NOW(), NOW()),
            ('550e8400-e29b-41d4-a716-446655440002'::uuid, 'Urban Redevelopment Authority', 'ura', 'https://www.ura.gov.sg', true, NOW(), NOW()),
            ('550e8400-e29b-41d4-a716-446655440003'::uuid, 'Inland Revenue Authority of Singapore', 'iras', 'https://www.iras.gov.sg', true, NOW(), NOW()),
            ('550e8400-e29b-41d4-a716-446655440004'::uuid, 'Monetary Authority of Singapore', 'mas', 'https://www.mas.gov.sg', true, NOW(), NOW()),
            ('550e8400-e29b-41d4-a716-446655440005'::uuid, 'CPF Board', 'cpf', 'https://www.cpf.gov.sg', true, NOW(), NOW())
        """
    )


def downgrade() -> None:
    op.drop_index("ix_crawl_jobs_source_status")
    op.drop_table("crawl_jobs")
    op.drop_index("ix_processed_chunks_embedding_id")
    op.drop_index("ix_processed_chunks_embedding_hnsw", table_name="processed_chunks")
    op.drop_index("ix_processed_chunks_document")
    op.drop_table("processed_chunks")
    op.drop_index("ix_raw_documents_status")
    op.drop_index("ix_raw_documents_content_hash")
    op.drop_index("ix_raw_documents_source_url")
    op.drop_constraint("uq_raw_documents_source_url", "raw_documents", type_="unique")
    op.drop_table("raw_documents")
    op.drop_table("sources")
    op.execute("DROP TYPE IF EXISTS crawl_job_status")
    op.execute("DROP TYPE IF EXISTS crawl_job_type")
    op.execute("DROP TYPE IF EXISTS document_status")
    op.execute("DROP EXTENSION IF EXISTS vector")
