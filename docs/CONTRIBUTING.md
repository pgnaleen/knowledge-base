# Contributing to the Knowledge Base Pipeline

## Branch Strategy

- `master` — production-ready code; no direct commits
- Feature branches: `feature/<short-description>` (e.g., `feature/playwright-hdb`)
- Bug fixes: `fix/<issue-description>`
- Create a PR from your branch into `master`

## Development Setup

### Prerequisites

- Python 3.11+
- Docker and Docker Compose (for PostgreSQL, Redis, MinIO)

### First-time Setup

```bash
# 1. Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # Linux/macOS
.venv\Scripts\activate             # Windows

# 2. Install all dependencies including dev tools
pip install -e ".[dev]"

# 3. Install Playwright browser (required for HDB and CPF crawlers)
playwright install chromium

# 4. Copy environment template
cp .env.example .env
# Edit .env if needed (defaults work for local Docker Compose)

# 5. Start infrastructure services
docker compose up -d postgres redis minio minio-init

# 6. Run database migrations
alembic upgrade head
```

### Running the Crawlers

```bash
# Run a single crawler
python -m crawlers.runner hdb

# Run all crawlers
python -m crawlers.runner
```

### Running Tests

```bash
# Unit tests only (fast, no infrastructure required)
pytest -m "not integration"

# Integration tests (requires docker compose up)
pytest -m integration

# All tests with coverage
pytest -m ""
```

### Code Quality

```bash
ruff check .          # Linting
black .               # Format code
black --check .       # Check formatting without modifying
```

## S3 Path Conventions

| Content Type   | Key Pattern                                      |
|----------------|--------------------------------------------------|
| Raw HTML       | `raw-html/{source}/{YYYY-MM-DD}/{url_hash}.html` |
| Raw PDF        | `raw-pdf/{source}/{YYYY-MM-DD}/{url_hash}.pdf`   |
| Processed Text | `processed/{source}/{YYYY-MM-DD}/{url_hash}.txt` |
| Embeddings     | `embeddings/{batch_id}/embeddings.json`           |

## Adding a New Spider

1. Create `crawlers/spiders/{source}_spider.py` extending `BaseCrawler`
2. Add source definition to `config/sources.yml`
3. Register the class in `crawlers/runner.py` `CRAWLER_MAP`
4. Add unit tests in `tests/unit/test_spiders.py`
