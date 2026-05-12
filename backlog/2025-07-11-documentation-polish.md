# Documentation Polish Pass

## Background

An older documentation checklist tracked a broad restructuring effort. Much of
that work has already landed: architecture docs, API/reference docs, content docs,
media docs, feature docs, operations docs, and release notes now exist.

The remaining value is not the original checklist itself, but a final consistency
pass over the current documentation tree.

## Scope

- Check `docs/index.rst` for a clear navigation structure.
- Verify content moved into `docs/content/`, `docs/media/`, `docs/features/`, `docs/reference/`, and
  `docs/operations/` is discoverable.
- Confirm old cross-references still resolve.
- Build docs and fix warnings.
- Remove or rewrite stale docs language that still describes older project structure.
- Add missing examples only where docs are hard to follow without them.

## Done When

- `just docs` builds without warnings caused by django-cast docs.
- The main docs sections are easy to scan from `docs/index.rst`.
- Any remaining documentation ideas are represented as focused backlog items, not as a broad stale checklist.
