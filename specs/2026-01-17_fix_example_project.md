# Fix example project

Issue: #196

## Background
- The example app is currently not working and blocks visual testing.
- We need a reliable, repeatable way to inspect themes and components in a real Django/Wagtail app.

## Goals
- Make the example project runnable with minimal setup.
- Ensure it can render django-cast pages (styleguide once available).
- Document the exact steps to run it locally.

## Current behavior
- Example app status is unknown or broken; needs verification and repair.

## Proposed direction
- Audit the example project (settings, urls, migrations, dependencies).
- Ensure the example app uses local `cast` templates and static assets.
- Add or fix demo data so the UI has meaningful content (reuse `src/cast/devdata.py` helpers).
- Enable `CAST_ENABLE_STYLEGUIDE` by default in the example app settings.
- Document a quickstart command sequence in the example project README or docs.
- Decide whether to keep or recreate `example/db.sqlite3` (prefer clean rebuild).

## Implementation notes (draft)
- Verify the example app can run with `uv run python example/manage.py runserver`.
- Provide fixtures or a simple management command to load demo content (lean on `src/cast/devdata.py`).
- Ensure static/media settings are correct for local development.
- Vite: `example/example_site/settings/dev.py` sets `DJANGO_VITE["cast"]["dev_mode"] = True`,
  so document running `npm run dev` in `javascript/` or provide a simpler path for local testing
  (e.g., set `dev_mode = False` for a no-Vite fallback).
- Static assets: document when `collectstatic` is required vs dev server usage.
- Bootstrap5 theme: document how to install or point to `../cast-bootstrap5` so the default theme renders.
  - Clarify whether styleguide templates must exist in `../cast-bootstrap5` or only in built-in themes initially.
  - Suggested install step: `uv pip install -e ../cast-bootstrap5`.
- Consider a `Procfile.dev` + `just dev` shortcut to run Django + Vite servers together.

## Testing
- Manual: run the example app and open the homepage and a blog post (styleguide once available).
