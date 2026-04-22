.PHONY: run dev test lint typecheck migrate upgrade

# --- Run ---
run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# --- Tests ---
test:
	pytest -v --cov=app --cov-report=term-missing

test-fast:
	pytest -v -x

# --- Code quality ---
lint:
	ruff check app/ tests/
	ruff format --check app/ tests/

lint-fix:
	ruff check --fix app/ tests/
	ruff format app/ tests/

typecheck:
	mypy app/

# --- DB ---
migrate:
	alembic revision --autogenerate -m "$(msg)"

upgrade:
	alembic upgrade head

downgrade:
	alembic downgrade -1

# --- Fernet key ---
gen-key:
	python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
