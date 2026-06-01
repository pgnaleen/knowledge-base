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

    # Pre-seed the 5 government sources with full crawl configuration
    op.execute(
        """
        INSERT INTO sources (id, name, code, base_url, crawl_config, is_active, created_at, updated_at)
        VALUES
            ('550e8400-e29b-41d4-a716-446655440001'::uuid, 'Housing & Development Board', 'hdb', 'https://www.hdb.gov.sg',
             '{"start_urls": ["https://www.hdb.gov.sg/buying-a-flat", "https://www.hdb.gov.sg/managing-my-home", "https://www.hdb.gov.sg/renting-a-flat"], "allowed_domains": ["www.hdb.gov.sg", "hdb.gov.sg"], "content_types": ["eligibility", "schemes", "grants", "resale_rules", "bto_info"], "js_rendering": true, "crawl_delay": 2.0, "estimated_pages": 300, "respect_robots_txt": true, "target_prefixes": ["/buying-a-flat", "/managing-my-home", "/renting-a-flat"], "skip_prefixes": ["/feedback", "/careers", "/eservices", "/news", "/publications", "/corporate", "/my-nice-home-gallery", "/home-gallery", "/virtual-tour"], "blocked_subdomains": ["assets.hdb.gov.sg"], "playwright_wait_event": "domcontentloaded", "min_content_length": 100, "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "content_selectors": ["main#main-content", "div.hdb-content", "main", "article"], "content_keywords_filter": null, "tag_config": {"property_type": {"HDB": ["hdb flat", "hdb"], "private": ["private residential", "condominium", "condo"], "EC": ["executive condominium", "ec "], "commercial": ["commercial property", "industrial"]}, "citizenship": {"SC": ["singapore citizen"], "PR": ["permanent resident", "pr"], "foreigner": ["foreigner", "non-resident", "non-citizen"]}, "topic": {"stamp_duty": ["stamp duty", "absd", "bsd", "ssd"], "ltv": ["loan-to-value", "ltv"], "tdsr": ["tdsr", "total debt servicing"], "msr": ["msr", "mortgage servicing ratio"], "housing_grant": ["ehg", "phg", "family grant", "proximity housing grant"], "eligibility": ["eligibility"], "first_time_buyer": ["first-time", "first time"], "cooling_measure": ["cooling measure"], "property_tax": ["property tax"], "rental": ["rental", "rent"]}}, "schedule": {"full": "0 2 * * 0", "incremental": "0 6 * * *"}}'::jsonb,
             true, NOW(), NOW()),
            ('550e8400-e29b-41d4-a716-446655440002'::uuid, 'Urban Redevelopment Authority', 'ura', 'https://www.ura.gov.sg',
             '{"start_urls": ["https://www.ura.gov.sg/Corporate/Property", "https://www.ura.gov.sg/Corporate/Guidelines"], "allowed_domains": ["www.ura.gov.sg", "ura.gov.sg"], "content_types": ["property_guidelines", "development_rules", "private_property_regulations"], "js_rendering": false, "crawl_delay": 2.0, "estimated_pages": 250, "respect_robots_txt": false, "target_prefixes": ["/Corporate/Property", "/Corporate/Guidelines"], "skip_prefixes": ["/maps", "/space", "/corporate/data"], "blocked_subdomains": [], "playwright_wait_event": "domcontentloaded", "min_content_length": 100, "user_agent": null, "content_selectors": ["div.mainWrap", "div.fullbody-wrapper", "div.text-cms-col", "main", "article"], "content_keywords_filter": null, "tag_config": {"property_type": {"private": ["private residential", "private property", "condominium", "landed residential"], "commercial": ["commercial property", "industrial"]}, "citizenship": {"SC": ["singapore citizen"], "PR": ["permanent resident"], "foreigner": ["foreigner", "non-resident"]}, "topic": {"stamp_duty": ["stamp duty", "absd", "bsd"], "property_tax": ["property tax"], "eligibility": ["eligibility"], "development": ["development", "planning", "guideline"]}}, "schedule": {"full": "0 2 * * 0", "incremental": "0 6 * * *"}}'::jsonb,
             true, NOW(), NOW()),
            ('550e8400-e29b-41d4-a716-446655440003'::uuid, 'Inland Revenue Authority of Singapore', 'iras', 'https://www.iras.gov.sg',
             '{"start_urls": ["https://www.iras.gov.sg/taxes/stamp-duty", "https://www.iras.gov.sg/taxes/property-tax"], "allowed_domains": ["www.iras.gov.sg", "iras.gov.sg"], "content_types": ["stamp_duty", "property_tax", "tax_rates", "reliefs"], "js_rendering": false, "crawl_delay": 2.0, "estimated_pages": 120, "respect_robots_txt": false, "target_prefixes": ["/taxes/stamp-duty", "/taxes/property-tax"], "skip_prefixes": [], "blocked_subdomains": [], "playwright_wait_event": "domcontentloaded", "min_content_length": 100, "user_agent": null, "content_selectors": ["div.sfContentBlock", "article.content", "main", "article"], "content_keywords_filter": null, "tag_config": {"property_type": {"all": []}, "citizenship": {"SC": ["singapore citizen"], "PR": ["permanent resident"]}, "topic": {"stamp_duty": ["stamp duty", "absd", "bsd", "ssd", "additional buyer", "seller stamp duty"], "property_tax": ["property tax", "annual value"], "ltv": ["loan-to-value", "ltv"], "eligibility": ["eligibility", "relief"]}}, "schedule": {"full": "0 2 * * 0", "incremental": "0 6 * * *"}}'::jsonb,
             true, NOW(), NOW()),
            ('550e8400-e29b-41d4-a716-446655440004'::uuid, 'Monetary Authority of Singapore', 'mas', 'https://www.mas.gov.sg',
             '{"start_urls": ["https://www.mas.gov.sg/regulations-and-financial-stability", "https://www.mas.gov.sg/news"], "allowed_domains": ["www.mas.gov.sg", "mas.gov.sg"], "content_types": ["loan_limits", "tdsr", "ltv", "mortgage_regulations"], "js_rendering": true, "crawl_delay": 3.0, "estimated_pages": 80, "respect_robots_txt": true, "target_prefixes": ["/regulation/regulations-and-guidance", "/news"], "skip_prefixes": ["/terms-of-use", "/privacy", "/about-mas", "/careers", "/contact", "/statistics", "/data-and-statistics", "/publications/statistics", "/investor-alert", "/complaints"], "blocked_subdomains": ["eservices.mas.gov.sg"], "playwright_wait_event": "domcontentloaded", "min_content_length": 100, "user_agent": null, "content_selectors": ["div.mas-content", "div#content", "main", "article"], "content_keywords_filter": ["property", "mortgage", "loan-to-value", "ltv", "tdsr", "total debt servicing", "housing loan", "residential property"], "tag_config": {"property_type": {"residential": ["residential property", "housing loan"], "commercial": ["commercial property"]}, "citizenship": {"all": []}, "topic": {"ltv": ["loan-to-value", "ltv"], "tdsr": ["tdsr", "total debt servicing"], "msr": ["msr", "mortgage servicing ratio"], "mortgage": ["mortgage", "housing loan", "residential property"], "eligibility": ["eligibility", "criterion"]}}, "schedule": {"full": "0 2 * * 0", "incremental": "0 6 * * *"}}'::jsonb,
             true, NOW(), NOW()),
            ('550e8400-e29b-41d4-a716-446655440005'::uuid, 'CPF Board', 'cpf', 'https://www.cpf.gov.sg',
             '{"start_urls": ["https://www.cpf.gov.sg/member/home-ownership"], "allowed_domains": ["www.cpf.gov.sg", "cpf.gov.sg"], "content_types": ["housing_scheme", "withdrawal_limits", "accrued_interest"], "js_rendering": true, "crawl_delay": 2.0, "estimated_pages": 150, "respect_robots_txt": true, "target_prefixes": ["/member/home-ownership"], "skip_prefixes": ["/member/healthcare", "/member/retirement", "/member/account-services", "/employer"], "blocked_subdomains": [], "playwright_wait_event": "networkidle", "min_content_length": 100, "user_agent": null, "content_selectors": ["div#cpf-content", "main", "article"], "content_keywords_filter": null, "tag_config": {"property_type": {"HDB": ["hdb flat", "hdb"], "private": ["private residential", "condominium", "private property"], "EC": ["executive condominium", "ec "]}, "citizenship": {"SC": ["singapore citizen"], "PR": ["permanent resident"]}, "topic": {"housing_grant": ["enhanced housing grant", "ehg", "family grant", "housing grant"], "housing_scheme": ["housing scheme", "cpf housing"], "cpf_withdrawal": ["cpf withdrawal", "ordinary account", "accrued interest"], "first_time_buyer": ["first-time", "first time", "first timer"], "eligibility": ["eligibility", "eligible"], "protection_scheme": ["home protection scheme", "hps"], "second_property": ["second property"]}}, "schedule": {"full": "0 2 * * 0", "incremental": "0 6 * * *"}}'::jsonb,
             true, NOW(), NOW())
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
    op.execute("UPDATE sources SET crawl_config = '{}'::jsonb WHERE code IN ('hdb','ura','iras','mas','cpf')")
    op.drop_table("sources")
    op.execute("DROP TYPE IF EXISTS crawl_job_status")
    op.execute("DROP TYPE IF EXISTS crawl_job_type")
    op.execute("DROP TYPE IF EXISTS document_status")
    op.execute("DROP EXTENSION IF EXISTS vector")
