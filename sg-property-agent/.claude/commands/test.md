# test
Run pytest with coverage report for the backend

1. Install dev deps: `pip install -r backend/requirements-dev.txt`
2. Run tests: `cd backend && pytest tests/ -v --cov=. --cov-report=term-missing`
3. Report will show line-by-line coverage gaps
4. Focus on Phase 0-2 tests first (concurrency, async, schemas, health checks)
