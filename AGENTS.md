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
- Run tests: `just test` (runs `uv run coverage run -m pytest` and `uv run coverage report`, and fails if coverage is below 100%); target specific tests with `just test-one tests/test_file.py::TestClass::test_case`.
- Type checks: `uv run mypy` (or `just typecheck`).
- Lint/format: `just lint` runs `ruff check --fix .` and `ruff format .` (line length 119).
- Coverage: `just coverage` runs tests with coverage and opens HTML report.
- Full matrix: `just tox` for multi-environment testing.
- Docs preview: `just docs` to rebuild Sphinx and open HTML locally.
- Pre-commit hooks: `just pre-commit` or `pre-commit run --all-files`.
- Run `just check` before delivery; it runs `just lint`, `just typecheck`, and `just test` in sequence and all three must pass. Because `just test` enforces `fail_under = 100`, `just check` fails if coverage drops below 100%.
- Do not consider a task done until `just check` passes.

## Coding Style & Naming Conventions
- Python 3.11+ with 4-space indentation; prefer explicit typing—public functions and classes should be type-annotated.
- Imports and formatting follow Ruff (`E,W,F,I,B,UP,DJ`); avoid unused symbols and dead code.
- Modules/files use `snake_case`, classes `PascalCase`, functions/methods `snake_case`, Django settings/constants `UPPER_SNAKE_CASE`.
- Keep Django/Wagtail app boundaries clean: models in `models/`, API in `api/`, templates in `templates/cast/`.

## Testing Guidelines
- New behaviors need Pytest coverage under `tests/` with `test_*.py`; mirror module paths for discoverability.
- Tests run with coverage via `uv run coverage run -m pytest` and `uv run coverage report`; `fail_under = 100` is configured in `pyproject.toml`.
- Maintain 100% test coverage for the Python test suite.
- Do not deliver changes if coverage drops below 100%; add tests or adjust coverage exclusions only when justified.
- For regression proofs, add focused tests near the bug; prefer fixtures over inline setup to avoid duplication.
- Use `pytest -k "keyword"` or `just test-one path::node` for fast iteration.

## Commit & Pull Request Guidelines
- This repository uses **trunk-based development**: `develop` is the trunk. Integrate work in small, frequent commits to `develop`—either directly or via short-lived branches that fast-forward back into it. Avoid long-lived feature branches that drift from the trunk.
- Commit messages: short, imperative subjects; keep each commit scoped to a single logical change.
- Do not bump version numbers on every commit.
- Before opening a PR, run `just check` (lint, typecheck, and tests).
- Before committing, verify whether documentation and release notes need updates; update `docs/` or `docs/releases/` when behavior changes.
- Update docs when adding features or changing behavior.
- When preparing a release, add a new file under `docs/releases/` and link it in `docs/releases/index.rst`.
- For ongoing changes, update `docs/releases/<current-version>.rst`, where `<current-version>` matches `pyproject.toml` and is the first entry in `docs/releases/index.rst`; do not create a new release notes file until the version is bumped.

## Releasing
- See `docs/release.rst` for the full release process (checks, JS build, tox, merge, GitHub release, PyPI publish).

## Build System
- Uses `uv_build` backend (NOT hatchling) with src layout (`src/cast/`).
- All imports reference `cast` (not `src.cast`).

## Important Notes
- Generated artifacts: avoid editing `docs/_build/`, `htmlcov/`, and built assets under `src/cast/static/` (edit sources in `javascript/` instead).
- Main branch is `develop`.
- Documentation at https://django-cast.readthedocs.io/
- Source at https://github.com/ephes/django-cast
- Local planning lives in `BACKLOG.md`; larger feature notes live in `backlog/` and should be linked from
  `BACKLOG.md`.
- Before committing, bring `BACKLOG.md` and linked `backlog/` notes up to date with the current repo state:
  remove completed items from active sections and mark retained planning notes as implemented or historical.
### Theme Repos (provide templates that extend django-cast)
- `../cast-bootstrap5` — Bootstrap 5 theme: templates in `cast_bootstrap5/templates/cast/bootstrap5/`
- `../cast-vue` — Vue.js theme: templates in `cast_vue/templates/cast/vue/`

### Consumer Sites (use django-cast as a dependency)
- `../homepage` — Production homepage site
- `../python-podcast` — Python podcast site

### When to Check Sibling Repos

**Always check theme repos** when changing:
- Template context variables (context processors, `get_context()` methods)
- Template block names or structure in base/core templates
- Feed URLs, view URLs, or URL naming
- CSS class names or HTML structure used in templates
- StreamField block rendering

**Always check consumer sites** when changing:
- Settings or configuration (new required settings, changed defaults)
- Model fields, migrations, or database schema
- Package dependencies or version requirements
- Management commands or CLI interfaces

### How to Check
1. Read the relevant templates/code in sibling repos to understand current usage
2. Make corresponding changes in sibling repos if needed
3. Note any sibling repo changes needed in the commit message or PR description

## Skills
- `playwright-smoke-tests` (in `~/.codex/skills/playwright-smoke-tests`): Run staging/local Playwright smoke checks for filters/list pages after deploys.
- Playwright e2e patterns: `.claude/skills/playwright/SKILL.md` (repository-local).
