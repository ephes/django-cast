# Production deployment review: homepage and Python Podcast

Date: 2026-10-17

Status: Read-only external review of `https://wersdoerfer.de/` and
`https://python-podcast.de/`, plus inspection of the current clean consumer
repositories. No critical or high-severity deployment issue was found. One
shared proxy-policy follow-up remains open in `BACKLOG.md`.

## Version evidence

The current `main` branches of `../homepage` and `../python-podcast` both pin
django-cast commit `704a60aa10b568d5697a716cf30b3fb82860f16c` in `uv.lock`.
That is the commit covered by the 2026-10-14 application security review; the
only later django-cast commit at review time added backlog text. Public HTTP
responses do not expose a reliable package revision, so the lockfiles establish
the intended deployment version rather than proving the bytes currently
running on either host.

## Positive observations

- Plain HTTP redirects permanently to HTTPS on both domains.
- TLS 1.0 and 1.1 handshakes are rejected; TLS 1.2 and 1.3 succeed. Both hosts
  presented valid Let's Encrypt certificates expiring on 2026-11-30.
- The edge rejects an unrelated `Host` value. The applications' production
  settings also use explicit `ALLOWED_HOSTS` lists.
- `CAST_ENABLE_DEV_TOOLS` is not enabled: the styleguide, components,
  theme-compare, and dev-health routes return ordinary 404 responses on both
  deployments. The development-only `/400/` and `/500/` routes also return the
  normal 404 page, with no debug traceback.
- Wagtail login responses are private and non-cacheable. CSRF cookies observed
  on public and login responses use `Secure`, `HttpOnly`, and `SameSite=Lax`.
- Responses include HSTS, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: same-origin`, and `Cross-Origin-Opener-Policy: same-origin`.
  An untrusted test `Origin` received no permissive CORS response header.
- Podcast audio is served through CloudFront with byte-range support. The live
  player transcript endpoint has the expected public 30-second cache policy and
  ETag from the recent response-cache hardening.
- `pip-audit==2.10.1` reported no known vulnerabilities among the registry-pinned
  runtime packages exported from either consumer lockfile. `pip-audit` cannot
  audit VCS requirements; those were kept separate rather than reported as
  clean. The django-cast VCS pin had already passed its package audit and source
  review. This review did not independently audit the other first-party VCS
  packages.

## Follow-up

Both live sites return:

```text
Strict-Transport-Security: max-age=15552000; includeSubDomains; preload
```

The 180-day policy provides HSTS, but it does not meet the one-year browser
preload requirement. The consumer deployment docs already state that the
`preload` token should be removed from the shared ops-library
`wagtail_deploy` Traefik template until the owner has checked every subdomain,
raised both Traefik and Django to 31,536,000 seconds, and chosen to submit the
domains for preloading. Apply one of those two documented policies so the edge
and Django fallback agree.

Traefik also emits `X-Frame-Options: SAMEORIGIN`, overriding the consumers'
`X_FRAME_OPTIONS = "DENY"`. Same-origin framing may be intentional for Wagtail
preview. Confirm that requirement and document the edge override; otherwise use
the stricter application policy consistently.

No Content Security Policy or Permissions Policy was observed. Their absence is
not a demonstrated vulnerability in this review, and django-cast themes and
author content need a compatibility design before adopting a CSP. They are not
separate backlog findings here.

## Limits

This was a bounded, non-intrusive review of public GET responses and local
configuration. It did not attempt authentication, submit forms, fuzz endpoints,
test rate-limit exhaustion, inspect production environment variables or
databases, verify private object-storage ACLs, or run a penetration test from
inside the deployment network. Certificate renewal automation was not tested.
