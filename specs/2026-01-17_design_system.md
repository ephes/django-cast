# Design system + styleguide

## Background
- We need a systematic frontend update for django-cast.
- Themes are shared across sites, but there are multiple ones (bootstrap4, bootstrap5 default, plain).
- The bootstrap5 theme lives in `../cast-bootstrap5` (external but default/primary, not optional).
- Most UI is template markup; a few JS components exist (gallery, podlove player).

## Goals
- Provide a design-system styleguide route that renders all UI elements.
- Make theme switching explicit and easy inside the styleguide.
- Keep markup aligned with real templates to avoid drift.
- Enable the styleguide via `CAST_ENABLE_STYLEGUIDE` (always on for the example app).

## Non-goals
- Rewriting all frontend behavior in JS.
- Final visual redesign decisions (this spec focuses on scaffolding and workflow).

## Proposed direction
- Add a styleguide Django view + URL in `cast` that can render by theme (not a Wagtail Page).
- Use per-theme templates: `cast/<theme>/styleguide/` for component pages.
- Compose the styleguide from the same partials used by real templates.
- Provide explicit theme switching UI within the styleguide (override the template base dir).
- Include JS-driven components (gallery, podlove player) in the styleguide using demo data.

## Dependencies
- Fix and validate the example app so it can be used for visual testing.
  - See: `specs/2026-01-17_fix_example_project.md`
- Ensure `../cast-bootstrap5` is available in the dev environment because it is the default theme.
  - If unavailable, define a graceful fallback (e.g., bootstrap4) or a clear error message.

## Implementation notes (draft)
- Add `CAST_ENABLE_STYLEGUIDE` setting and guard the route accordingly.
- Provide a theme switcher UI on the styleguide page (e.g., select element or buttons).
- Use existing theme selection logic where possible (avoid duplicating rules), e.g. session-based switching in
  `views/theme.py`.
- Default URL path: `/styleguide/` (respecting any prefix used when including `cast` URLs).
- Demo data should come from existing helpers in `src/cast/devdata.py` where possible.
- Keep styleguide markup in sync by reusing the same partials as production templates.

## Component inventory (initial)
- Typography (headings, paragraphs, lists, code blocks)
- Buttons and links (primary, secondary, disabled)
- Post cards / list items
- Pagination controls
- Gallery grid + modal
- Audio player (Podlove)
- Video player
- Transcript display
- Comments section
- Forms (theme selector, search/filter)
- Error pages (400, 403, 404, 500)

## Testing
- Manual: open the styleguide for each theme and verify components render correctly.
- Add a light smoke test that the styleguide view renders without errors.
