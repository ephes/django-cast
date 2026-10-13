Unreleased
==========

- Resolve Voxhelm API base and token as a pair from one configuration level.
  Incomplete pairs no longer inherit deployment credentials. Move mixed-level
  credentials to one level before upgrading; changing the Wagtail API base
  requires re-entering its token. Saving with both credential fields blank
  removes the site pair so deployment credentials can be used.

- Fall back to the plain theme selector fragment for HTMX requests when a
  theme omits the optional ``select_theme.html`` template.
- Report missing soft-required theme templates as ``cast.W002`` system check
  warnings, including configured themes and templates provided by custom loaders.
  Template syntax errors also produce warnings rather than aborting startup checks.
