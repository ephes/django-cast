# Justfile for django-cast project development

# Default recipe - show available commands
default:
    @just --list

# Install Python dependencies via uv
install:
    uv sync

# Run the full test suite
test:
    uv run pytest

# Run a specific test (pass path or node id)
test-one TARGET:
    uv run pytest {{TARGET}} -v

# Run type checks with mypy
typecheck:
    uv run mypy

# Run linting and formatting with ruff
lint:
    uv run ruff check --fix .
    uv run ruff format .

# Run tests with coverage and open HTML report
[macos]
coverage:
    uv run coverage run -m pytest
    uv run coverage html
    open htmlcov/index.html

[linux]
coverage:
    uv run coverage run -m pytest
    uv run coverage html
    xdg-open htmlcov/index.html 2>/dev/null || echo "Open htmlcov/index.html in your browser"

# Build documentation and open in browser
[macos]
docs:
    rm -f docs/cast.api.rst docs/cast.migrations.rst docs/cast.rst docs/cast.templatetags.rst docs/modules.rst
    uv run make -C docs clean
    uv run make -C docs html
    open docs/_build/html/index.html

[linux]
docs:
    rm -f docs/cast.api.rst docs/cast.migrations.rst docs/cast.rst docs/cast.templatetags.rst docs/modules.rst
    uv run make -C docs clean
    uv run make -C docs html
    xdg-open docs/_build/html/index.html 2>/dev/null || echo "Open docs/_build/html/index.html in your browser"

# Run all pre-commit hooks
pre-commit:
    uv run pre-commit run --all-files

# Run tox for multi-environment testing
tox:
    uv run tox

# Run JavaScript tests (Vitest)
js-test:
    cd javascript && npm test

# Run JavaScript tests in watch mode
js-test-watch:
    cd javascript && npm run test:watch

# Run JavaScript tests with coverage
js-coverage:
    cd javascript && npm run coverage

# Build shipped comment JS at src/cast/static/fluent_comments/js/ajaxcomments.js
js-build-comments:
    cd javascript && npm run build:comments

# Build Vite assets and copy to src/cast/static/cast/vite/
js-build-vite:
    cd javascript && npm run build
    rm -f javascript/dist/manifest.json
    sh -c 'test -f javascript/dist/.vite/manifest.json && mv javascript/dist/.vite/manifest.json javascript/dist/manifest.json || true'
    rm -rf javascript/dist/.vite
    rm -f src/cast/static/cast/vite/*
    cp javascript/dist/* src/cast/static/cast/vite/

# Build all shipped JS artifacts
js-build-all:
    just js-build-vite
    just js-build-comments
