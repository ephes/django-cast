# Repository Read-Model Cleanup Experiment

## Summary

Do not add `django-mantle` to django-cast yet. The useful idea is narrower:
extract selected read-side business logic into local typed shapes while keeping
the existing repository contexts and template-facing model-like objects.

The current repository layer already handles project-specific Wagtail behavior
that Mantle does not provide directly: `Page.specific`, `StreamField`, image
renditions, rich-text link priming, request/site-aware URLs, theme compatibility,
and aggregate lookup maps.

## Recommended First Slice

Create an experiment branch such as:

```text
experiment/repository-readmodels
```

Keep existing public/template contracts intact and avoid adding a new dependency.

Suggested steps:

1. Extract repeated media lookup rebuild logic from `src/cast/models/repository/contexts.py` into a shared helper.
2. Add explicit `TypedDict` definitions for cacheable dict boundaries between `builders.py` and `contexts.py`.
3. Add small local `attrs` read shapes only where they clarify pure read-side logic, such as cover fallback or
   comment enablement.
4. Keep current repository queries and template-facing model-like objects.
5. Preserve zero-query render behavior and assert that with focused tests.
6. Audit the Wagtail API serializer path for `.specific` / blog lookup N+1 behavior outside the repository layer.

## Success Criteria

- Zero-query render invariants stay intact.
- Cache-boundary typing catches missing keys or shape mismatches earlier.
- Any adapter layer needed for template compatibility stays small.
- Tests become clearer than the current manual snapshot setup.

Stop or limit the experiment if query counts get worse, the adapter layer grows
large, Wagtail reconstruction dominates the work, or typed shapes encourage
misleading immutability around mutable repository state.

## Mantle Decision

Revisit `django-mantle` only if local typed-shape work proves a concrete need for
query-backed projections that the current repository layer does not provide.
