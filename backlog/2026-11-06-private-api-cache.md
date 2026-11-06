# Private API response caching

Status: implemented (2026-11-06), scout round 49 bundle B15.

Reverified all three findings on develop at 2a97cd81, after the earlier worker's
quickstart/media-test integration. Round 48 has no django-cast bundle.

Implemented in the listed order:

1. `cast-owner-media-api-cache-revalidation`: owner-filtered audio/video lists,
   details and handled errors now send private/no-store and credential Vary.
2. `cast-editor-api-private-cache-boundary`: EditorAPIView applies the same
   policy to every response, including structured errors and rendered previews.
3. `cast-comment-training-corpus-no-store`: the staff-only corpus and handled
   denials apply that policy without changing public comment display.

A small shared DRF base applies Django's public cache-header helpers after
response finalization. Authentication, scopes, owner/collection/page permissions,
and public Podlove/transcript caching retain their existing rules.

`tests/api/private_cache_test.py` enables Django's full-site cache middleware.
Synthetic bearer credentials are resolved against current test-user state;
owner responses cannot survive credential revocation or cross owner boundaries.
Draft/parent responses recheck Wagtail admin permission, and a synthetic corpus
cannot be served after staff removal or session invalidation. All nine original
regressions fail against the pre-fix source and pass with the policy.
No media probes, real services or personal data are needed by these tests.

Read-only consumer check: the available homepage and python-podcast workspace
snapshots configure file-based production caches. Homepage's full-site cache
middleware is commented out; python-podcast's base settings do not enable it.
The regression stack deliberately enables that middleware, independent of
consumer configuration. No consumer checkout or running service was changed.

Adoption requires consumers to update the package and deploy in their normal
workflow. No deployment, release or tag is part of this change.
