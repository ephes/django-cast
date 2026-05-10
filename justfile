# Justfile for django-cast project development

# Default recipe - show available commands
default:
    @just --list

SLOPSCOPE_PATH := env_var_or_default("SLOPSCOPE_PATH", "../slopscope")

# Install Python dependencies via uv
install:
    uv sync

# Log directory for dev server output (namespaced by repo path hash)
export CAST_LOG_DIR := "/tmp/cast-dev-" + `printf '%s' "$PWD" | md5 -q 2>/dev/null || printf '%s' "$PWD" | md5sum | head -c8`
# Dev server port (used by runserver, dev-status, dev-open)
export CAST_DEV_PORT := "8000"

# Run example app and Vite dev servers (Procfile.dev)
dev:
    uvx honcho start -f Procfile.dev

# Start dev server in a tmux session named cast-dev
dev-tmux:
    tmux new-session -d -s cast-dev 'just dev' 2>/dev/null || tmux attach -t cast-dev

# Tail a specific dev server log (django, vite-cast, vite-bs5, vite-vue)
dev-logs SERVICE="django":
    tail -f "$CAST_LOG_DIR/{{SERVICE}}.log"

# Show the dev log directory path
dev-logs-dir:
    @echo "$CAST_LOG_DIR"

# Check if dev server processes are running
dev-status:
    @echo "Log directory: $CAST_LOG_DIR"
    @if curl -sf http://localhost:{{CAST_DEV_PORT}}/cast/dev-health/ 2>/dev/null | grep -q '"status"'; then echo "Django: running (dev-health ok)"; elif curl -sf -o /dev/null -H 'Accept: text/html' http://localhost:{{CAST_DEV_PORT}}/admin/login/ 2>/dev/null; then echo "Django: running (dev-health unavailable)"; else echo "Django: not running"; fi
    @if tmux has-session -t cast-dev 2>/dev/null; then echo "tmux session: active"; else echo "tmux session: not found"; fi

# Open the dev server in the default browser
[macos]
dev-open:
    open http://localhost:{{CAST_DEV_PORT}}

[linux]
dev-open:
    xdg-open http://localhost:{{CAST_DEV_PORT}} 2>/dev/null || echo "Open http://localhost:{{CAST_DEV_PORT}} in your browser"

# Run lint, typecheck, and tests
check:
    just lint
    just typecheck
    just test

# Run the full test suite with coverage enforcement (fail if <100%)
test:
    uv run coverage run -m pytest
    uv run coverage report

# Run only fast tests (exclude tests marked as slow)
test-fast:
    uv run pytest -m "not slow"

# Run only intentionally slow tests
test-slow:
    uv run pytest -m slow

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
    python -c "from pathlib import Path; p=Path('javascript/dist/manifest.json'); txt=p.read_text() if p.exists() else None; (p.write_text(txt.rstrip('\\n')+'\\n') if txt is not None else None)"
    rm -rf javascript/dist/.vite
    rm -f src/cast/static/cast/vite/*
    cp javascript/dist/* src/cast/static/cast/vite/

# Build all shipped JS artifacts
js-build-all:
    just js-build-vite
    just js-build-comments

# Check if built JS/CSS assets are up-to-date with source
verify-assets:
    uv run python scripts/check_asset_freshness.py

# Prefetch styleguide demo data and media
styleguide-prefetch *ARGS:
    uv run python example/manage.py styleguide_prefetch {{ARGS}}

# Create/update reference site with demo content
ensure-reference-site *ARGS:
    uv run python example/manage.py ensure_reference_site {{ARGS}}

# Take a screenshot of a page (requires running dev server)
screenshot PATH *ARGS:
    uv run python scripts/playwright_utils.py screenshot {{PATH}} {{ARGS}}

# Screenshot all themes for a page
screenshot-all PATH *ARGS:
    uv run python scripts/playwright_utils.py screenshot-all {{PATH}} {{ARGS}}

# Check a page for console errors
check-page PATH *ARGS:
    uv run python scripts/playwright_utils.py check-page {{PATH}} {{ARGS}}

# Generate HTML comparison report across all themes
compare-page PATH *ARGS:
    uv run python scripts/playwright_utils.py compare-page {{PATH}} {{ARGS}}

# Count lines of code in the repository (by language + by top-level folder)
loc:
    uv run --with-editable {{SLOPSCOPE_PATH}} slopscope .
