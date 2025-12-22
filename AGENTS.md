# Repository Guidelines

## Project Structure & Module Organization
- `src/cast/`: Django/Wagtail app for blogging and podcasting with models, views, API, blocks, feeds, and templates.
- `tests/`: Pytest suite using `tests.settings` (set via `DJANGO_SETTINGS_MODULE`); mirrors app modules and holds fixtures.
- `docs/`: Sphinx documentation (`just docs` builds HTML).
- `javascript/`: Vite-based frontend with npm scripts for dev/build/test.
- `example/`: Example Django project for development.

## Build, Test, and Development Commands
- List commands: `just --list` (or plain `just`).
- Install deps: `uv sync` (or `just install`).
- Run tests: `uv run pytest` (or `just test`); target specific tests with `just test-one tests/test_file.py::TestClass::test_case`.
- Type checks: `uv run mypy` (or `just typecheck`).
- Lint/format: `just lint` runs `ruff check --fix .` and `ruff format .` (line length 119).
- Coverage: `just coverage` runs tests with coverage and opens HTML report.
- Full matrix: `just tox` for multi-environment testing.
- Docs preview: `just docs` to rebuild Sphinx and open HTML locally.
- Pre-commit hooks: `just pre-commit` or `pre-commit run --all-files`.
- Always run `just typecheck` (or `uv run mypy`) after code changes; treat it as a required check.
- Always run `just lint` and `just typecheck` before delivery; both must pass.

## Coding Style & Naming Conventions
- Python 3.11+ with 4-space indentation; prefer explicit typing—public functions and classes should be type-annotated.
- Imports and formatting follow Ruff (`E,W,F,I,B,UP,DJ`); avoid unused symbols and dead code.
- Modules/files use `snake_case`, classes `PascalCase`, functions/methods `snake_case`, Django settings/constants `UPPER_SNAKE_CASE`.
- Keep Django/Wagtail app boundaries clean: models in `models/`, API in `api/`, templates in `templates/cast/`.

## Testing Guidelines
- New behaviors need Pytest coverage under `tests/` with `test_*.py`; mirror module paths for discoverability.
- Tests run with coverage (`--cov-config=pyproject.toml`).
- Maintain 100% test coverage for the Python test suite.
- For regression proofs, add focused tests near the bug; prefer fixtures over inline setup to avoid duplication.
- Use `pytest -k "keyword"` or `just test-one path::node` for fast iteration.

## Commit & Pull Request Guidelines
- Commit messages: short, imperative subjects; keep each commit scoped to a single logical change.
- Do not bump version numbers on every commit.
- Before opening a PR, run `just test`, `just typecheck`, and `just lint`.
- Update docs when adding features or changing behavior.
- When preparing a release, add a new file under `docs/releases/` and link it in `docs/releases/index.rst`.

## Build System
- Uses `uv_build` backend (NOT hatchling) with src layout (`src/cast/`).
- All imports reference `cast` (not `src.cast`).

## Important Notes
- Generated artifacts: avoid editing `docs/_build/`, `htmlcov/`, and built assets under `src/cast/static/` (edit sources in `javascript/` instead).
- Main branch is `develop`.
- Documentation at https://django-cast.readthedocs.io/
- Source at https://github.com/ephes/django-cast
