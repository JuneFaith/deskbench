.PHONY: check test format

check:
	uv run ruff format --check src tests
	uv run ruff check src tests
	uv run mypy src tests

test:
	uv run pytest

format:
	uv run ruff format src tests
