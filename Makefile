.PHONY: up down build train test test-backend test-frontend lint setup logs clean

# ── Docker ─────────────────────────────────────────────────────────
up:
	@echo "Starting PayGuard stack…"
	docker compose up -d --build
	@echo "Dashboard: http://localhost:3000"
	@echo "API:       http://localhost:8001"
	@echo "Inference: http://localhost:8000"

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

clean:
	docker compose down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -f ml/model.onnx ml/feature_map.json ml/eval_results.json

# ── Model training ─────────────────────────────────────────────────
train:
	@echo "Training PayGuard IsolationForest model…"
	python -m ml.train --seed 42
	@echo "Model saved to ml/model.onnx"
	@echo "Metrics saved to ml/eval_results.json"

# ── Testing ────────────────────────────────────────────────────────
test: test-backend test-frontend

test-backend:
	@echo "Running Python test suite…"
	python -m pytest tests/ -v --cov=. \
		--cov-report=term-missing \
		--cov-omit="*/tests/*,*/__pycache__/*" \
		-p no:warnings

test-frontend:
	@echo "Running Jest test suite…"
	cd frontend && npm test -- --coverage

# ── Lint ───────────────────────────────────────────────────────────
lint:
	@echo "Running ruff…"
	ruff check producer/ consumer/ ml/ inference/ api/ tests/
	@echo "Running mypy…"
	mypy producer/ consumer/ ml/ inference/ api/ --ignore-missing-imports
	@echo "Lint OK ✓"

# ── Git hooks setup ────────────────────────────────────────────────
setup:
	@echo "Installing git hooks…"
	chmod +x scripts/install_hooks.sh
	./scripts/install_hooks.sh
	@echo "Installing Python dependencies…"
	pip install -r requirements-dev.txt
	@echo "Installing frontend dependencies…"
	cd frontend && npm install
	@echo "Setup complete ✓"
