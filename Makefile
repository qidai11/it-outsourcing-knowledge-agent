.PHONY: sync lock lint typecheck test task0 check run

sync:
	uv sync --all-groups

lock:
	uv lock

lint:
	uv run ruff check src tests

typecheck:
	uv run mypy src

test:
	uv run pytest tests/unit/test_config.py tests/integration/api/test_health.py -v

task0:
	uv run python scripts/validate_task0.py

check: task0 lint typecheck test

run:
	uv run uvicorn project_agent.main:app --host 0.0.0.0 --port 8000 --reload
