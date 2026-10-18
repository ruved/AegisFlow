.PHONY: test lint eval format

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

eval:
	uv run pytest -q tests

format:
	uv run ruff check --fix .
	uv run ruff format .
