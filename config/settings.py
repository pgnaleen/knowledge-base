"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://kb_user:kb_pass@localhost:5432/kb_pipeline_db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # S3 / MinIO
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "kb-pipeline"
    s3_region: str = "us-east-1"

    # OpenAI
    openai_api_key: str = ""

    # Pinecone
    pinecone_api_key: str = ""
    pinecone_index: str = "kb-pipeline"
    pinecone_environment: str = "us-east-1"

    # Crawler
    crawl_delay: float = 2.0
    crawl_user_agent: str = "KB-BOT/1.0"
    crawl_respect_robots_txt: bool = True
    crawl_max_retries: int = 3

    # Logging
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
