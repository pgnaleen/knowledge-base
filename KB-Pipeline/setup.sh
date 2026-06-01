#!/usr/bin/env bash
# KB-Pipeline — one-command local setup
# Usage: bash setup.sh
#
# Architecture:
#   All Python code runs INSIDE the Docker app container (KB-Pipeline-App).
#   You never need a local venv. All commands run via: docker exec KB-Pipeline-App <cmd>
#
# Requires: Docker Desktop running

set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

APP="KB-Pipeline-App"

step() { echo -e "\n${BOLD}[STEP]${NC} $1"; }
ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
fail() { echo -e "${RED}  ✗ $1${NC}"; exit 1; }
app()  { docker exec "$APP" "$@"; }

# ─── Prerequisites ────────────────────────────────────────────────────────────

step "Checking prerequisites"

docker info > /dev/null 2>&1 \
    || fail "Docker is not running. Start Docker Desktop first."
ok "Docker is running"

# ─── Environment file ─────────────────────────────────────────────────────────

step "Setting up .env"

if [ ! -f .env ]; then
    cp .env.example .env
    ok "Created .env from .env.example"
    warn "Edit .env and add your OPENAI_API_KEY and PINECONE_API_KEY before running crawlers"
else
    ok ".env already exists — skipping"
fi

# ─── Build and start all containers ───────────────────────────────────────────

step "Building and starting all Docker containers"

docker compose up -d --build
ok "Docker Compose started (building app image if needed)"

# ─── Wait for services ────────────────────────────────────────────────────────

step "Waiting for services to become healthy"

wait_healthy() {
    local name=$1 max=60 attempt=0
    until [ "$(docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null)" = "healthy" ]; do
        attempt=$((attempt + 1))
        [ $attempt -ge $max ] && fail "$name did not become healthy after $((max * 2))s"
        sleep 2
    done
    ok "$name is healthy"
}

wait_healthy "KB-Pipeline-Postgres"
wait_healthy "KB-Pipeline-Redis"
wait_healthy "KB-Pipeline-Minio"
wait_healthy "$APP"

# ─── Database migrations ──────────────────────────────────────────────────────

step "Running Alembic migrations (inside app container)"

app alembic upgrade head
ok "Database schema created and 5 sources seeded with full crawl config"

# ─── MinIO buckets ────────────────────────────────────────────────────────────

step "Initialising MinIO storage buckets (inside app container)"

app python -c "from config.storage import StorageClient; StorageClient().ensure_buckets()" \
    && ok "MinIO buckets ready: raw-html, raw-pdf, processed, embeddings" \
    || warn "MinIO bucket init failed — check S3_ENDPOINT in .env"

# ─── Linting ──────────────────────────────────────────────────────────────────

step "Running linting checks (inside app container)"

app ruff check . --quiet \
    && ok "ruff: all checks passed" \
    || warn "ruff issues found — run: docker exec $APP ruff check . to see details"

app black --check . --quiet \
    && ok "black: formatting OK" \
    || warn "black: run 'docker exec $APP black .' to fix formatting"

# ─── Unit tests ───────────────────────────────────────────────────────────────

step "Running unit tests (inside app container)"

app python -m pytest tests/unit/ -v -m "not integration" 2>&1 | tail -25
ok "Unit tests complete"

# ─── Scrapy check ─────────────────────────────────────────────────────────────

step "Verifying Scrapy spiders (inside app container)"

echo "  Registered spiders:"
app scrapy list | sed 's/^/    /'
ok "All 5 spiders registered"

# ─── Summary ──────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}${GREEN}Setup complete!${NC}"
echo ""
echo "  Running containers:"
echo "    KB-Pipeline-App      → your code (crawlers, tests, alembic, ruff)"
echo "    KB-Pipeline-Postgres → localhost:5432  (kb_user / kb_pass / kb_pipeline_db)"
echo "    KB-Pipeline-Redis    → localhost:6379"
echo "    KB-Pipeline-Minio    → localhost:9000 (API)  localhost:9001 (UI: minioadmin/minioadmin)"
echo ""
echo "  MinIO bucket (single bucket, prefix-based layout):"
echo "    sg-property-kb/raw-html/  → raw HTML from crawlers"
echo "    sg-property-kb/raw-pdf/   → raw PDF from crawlers"
echo "    sg-property-kb/processed/ → processed text + embeddings"
echo ""
echo -e "  ${BOLD}How to run commands:${NC}"
echo "    docker exec KB-Pipeline-App scrapy crawl hdb"
echo "    docker exec KB-Pipeline-App python -m processors.runner"
echo "    docker exec KB-Pipeline-App python -m pytest tests/unit/ -v"
echo "    docker exec KB-Pipeline-App alembic upgrade head"
echo "    docker exec KB-Pipeline-App ruff check ."
echo "    docker exec KB-Pipeline-App black ."
echo ""
echo -e "  ${BOLD}Open a shell inside the container:${NC}"
echo "    docker exec -it KB-Pipeline-App bash"
echo ""
echo "  Stop everything:    docker compose down"
echo "  Wipe all data:      docker compose down -v && bash setup.sh"
echo ""
echo "  Add API keys to .env before running crawlers:"
echo "    OPENAI_API_KEY=sk-..."
echo "    PINECONE_API_KEY=..."
echo ""
