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
└── Blog (Index Page)
    ├── Post (Content Page)
    └── Podcast (Specialized Blog)
        └── Episode (Specialized Post)
```

### Key Models
- **Blog/Podcast**: Index pages containing settings and child posts
- **Post/Episode**: Content pages with StreamField body and media attachments
- **Audio/Video/Gallery**: Media models with user association and collection support
- **ChapterMark/Transcript**: Audio enhancements for accessibility

### Design Patterns
- **Repository Pattern**: QuerysetData, PostDetailRepository, etc. for optimized data fetching
- **Mixin Architecture**: Reusable functionality across models and views
- **Performance Focus**: Aggressive prefetching, rendition caching, bulk operations

## Development Commands

### Python/Django Commands
```bash
# Run tests
uv run pytest

# Run tests with coverage
python commands.py coverage

# Type checking
python commands.py mypy

# Build documentation
python commands.py docs

# Test against multiple Django/Wagtail versions
uv run tox

# Quick development testing (faster)
uvx tox -e fast

# Note: The development server is typically run in a separate project 
# where django-cast is installed as an editable package via:
# uv sync
```

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
# Format code with black
black .

# Sort imports
isort .

# Lint with flake8
flake8

# Run all pre-commit hooks
pre-commit run --all-files
```

## Testing

- Test framework: pytest with Django integration
- Test settings: `tests/settings.py`
- JavaScript tests: Vitest with jsdom
- Coverage requirements: Configured in `pyproject.toml`
- Run single test: `uv run python commands.py test path.to.test::TestClass::test_method`

## Code Style

- Python: Black formatter with 119 char line length
- Imports: isort with black profile, custom Django/Wagtail sections
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
5. Test with `uv run pytest`

## CLI Commands

- Run tests in multiple environments: `uv run tox`

## Commit Guidelines
- Do not bump the version number on every commit

## Memories
- Use `uv run tox` instead of `uvx tox`