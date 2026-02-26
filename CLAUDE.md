# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Django Cast is a blogging and podcasting package built on Django and Wagtail CMS. It provides:
- Blog post management with rich content editing via Wagtail StreamField
- Full podcast support including RSS feeds, iTunes metadata, and chapter marks
- Responsive image handling with automatic rendition generation
- Video and audio file management with transcripts
- Integrated commenting system with spam filtering
- REST API for headless CMS usage

## Architecture

### Page Hierarchy
```
HomePage
├── Blog (Index Page)
│   └── Post (Content Page)
└── Podcast (Specialized Blog)
    └── Episode (Specialized Post)
```

### Key Models
- **Blog/Podcast**: Index pages containing settings and child posts
- **Post/Episode**: Content pages with StreamField body and media attachments
- **Image/Audio/Video/Gallery**: Media models with user association and collection support
- **ChapterMark/Transcript**: Audio enhancements for accessibility

### Design Patterns
- **Repository Pattern**: QuerysetData, PostDetailRepository, etc. for optimized data fetching
- **Mixin Architecture**: Reusable functionality across models and views
- **Performance Focus**: Aggressive prefetching, rendition caching, bulk operations

## Development Commands

### Python/Django Commands
```bash
# Run tests with 100% coverage enforcement (used by `just check`)
just test  # runs: uv run coverage run -m pytest && uv run coverage report

# Run tests with coverage and open HTML report
just coverage

# Type checking
uv run mypy

# Build documentation
just docs

# Test against multiple Django/Wagtail versions
uv run tox

# Note: The development server is typically run in a separate project
# where django-cast is installed as an editable package
```
Always run `just check` (runs `just lint`, `just typecheck`, and `just test` in sequence) before delivery; all three must pass.
`just test` enforces 100% code coverage — it will fail if any line is uncovered.
Do not consider a task done until `just check` passes.

### Dev Server Commands
```bash
# Start dev server (Django + Vite dev servers)
just dev

# Start in tmux session named "cast-dev" (recommended for agents)
just dev-tmux

# Check server status
just dev-status

# Tail Django logs
just dev-logs django

# Show log directory path
just dev-logs-dir

# Open in browser
just dev-open

# Take screenshots (requires running dev server)
just screenshot /styleguide-blog/ --theme bootstrap5
just screenshot-all /styleguide-blog/
just compare-page /styleguide-blog/
just check-page /styleguide-blog/ --theme bootstrap5

# Create/update reference site
just ensure-reference-site
```

The dev server tmux session name is `cast-dev`. Logs are written to
`/tmp/cast-dev-<hash>/` where `<hash>` is derived from the repo path.
The dev server port defaults to 8000 and can be overridden via `CAST_DEV_PORT`.
For a fully custom base URL (e.g., HTTPS or a different host), set
`CAST_DEV_BASE_URL` for Playwright tooling.

### JavaScript Build Commands
```bash
cd javascript

# Development server (Vite)
npm run dev

# Production build
npm run build

# Run tests
npm test

# Run tests with coverage
npm run coverage
```

### Code Quality
```bash
# Format code and sort imports with ruff
ruff format .

# Lint with ruff
ruff check --fix .

# Run all pre-commit hooks
pre-commit run --all-files
```

## Testing

- Test framework: pytest with Django integration
- Test settings: `tests/settings.py`
- JavaScript tests: Vitest with jsdom
- Coverage requirements: Configured in `pyproject.toml` and must remain at 100% for the Python test suite.
- **IMPORTANT**: Do not deliver changes if coverage drops below 100%. Add tests for new code or adjust coverage exclusions only when justified.
- Run single test: `just test-one tests/test_file.py::TestClass::test_case`

### End-to-End Testing with Playwright

For browser-based e2e testing, use the `/playwright` skill which provides guidance on:
- Setting up pytest-playwright
- Writing e2e tests with Django's live server
- Page Object Model patterns
- Debugging and tracing

See [.claude/skills/playwright/SKILL.md](.claude/skills/playwright/SKILL.md) for detailed usage.

## Code Style

- Python: Ruff formatter with 119 char line length
- Imports: Ruff import sorting (black-compatible)
- Templates: djhtml formatting
- Pre-commit hooks enforce all styling rules

## Build System

This project uses the **uv_build** backend (NOT hatchling). The configuration is in pyproject.toml:
- Build backend: `uv_build`
- Source layout: `src/cast/` directory structure
- Module configuration: `module-root = "src"` and `module-name = "cast"`

**IMPORTANT**: Always use `uv_build` as the build backend. Do not switch to hatchling or other backends.

## Src Layout Considerations

Since the project uses src layout (`src/cast/`), the following applies:
- Tox configuration includes `PYTHONPATH={toxinidir}/src` to find the cast module
- All imports reference `cast` (not `src.cast`)
- Package is installed in editable mode with `uv pip install -e .`

## Important Files and Locations

- Main app code: `src/cast/` (uses src layout)
- Models: `src/cast/models/`
- API endpoints: `src/cast/api/`
- Wagtail blocks: `src/cast/blocks.py`
- Feed generation: `src/cast/feeds.py`
- JavaScript source: `javascript/src/`
- Tests: `tests/`
- Specs: `specs/` — **local-only, listed in `.gitignore`; NEVER commit or `git add -f` spec files**
- Example project: `example/`

## Working with Media

Cast handles multiple media types:
- Images: Automatic responsive renditions via Wagtail
- Audio: MP3, M4A, OGA, OPUS with duration and chapter support
- Video: User-uploaded video files
- Galleries: Collections of images

Media is stored using Django's file storage and organized by Wagtail collections.

## API Development

The REST API uses Django REST Framework with Wagtail API v2:
- Standard endpoints in `cast/api/`
- Wagtail page API for content
- Custom serializers for media types
- Repository pattern for efficient data loading

## StreamField Content

Posts use StreamField with two sections:
- `overview`: Summary content
- `detail`: Full article content

Both support: heading, paragraph, code, image, gallery, embed, video, audio blocks.

## Database Migrations

When modifying models:
1. Make changes to model files
2. Run `uv run manage.py makemigrations`
3. Review generated migration
4. Run `uv run manage.py migrate`
5. Test with `just test`

## CLI Commands

- Run tests in multiple environments: `uv run tox`

## Commit Guidelines
- **IMPORTANT**: Do not commit unless explicitly asked to. Never auto-commit after completing a task.
- Do not bump the version number on every commit
- Before committing, check whether documentation or release notes need updates; update `docs/` or `docs/releases/` when behavior changes.

## Releasing

See [docs/release.rst](docs/release.rst) for the full release process (checks, JS build, tox, merge, GitHub release, PyPI publish).

## Version Bumping

When bumping the version number for a new release:
1. Update version in `pyproject.toml` (version = "X.Y.Z")
2. Update version in `docs/conf.py` (release = "X.Y.Z")
3. Update version in `src/cast/__init__.py` (__version__ = "X.Y.Z")
4. Update version reference in `README.md` (Documentation for [current version X.Y.Z])
5. Ensure `docs/releases/X.Y.Z.rst` exists; if it already exists, keep using it.
6. Link the release notes in `docs/releases/index.rst`
7. During ongoing work, only update `docs/releases/<current-version>.rst`, where `<current-version>` matches `pyproject.toml` and is the first entry in `docs/releases/index.rst`; do not create additional release files.

## Related Sibling Repositories

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

**Note:** django-cast is an OSS package. Do not add dev orchestration scripts
or runtime tooling for consumer sites (homepage, python-podcast) inside this
repo. Cross-repo local dev orchestration belongs in user-level tooling
(e.g., global Codex skills, dotfiles), not in the library itself.

## Memories
- Use `uv run tox` instead of `uvx tox`
