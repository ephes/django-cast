Unreleased
==========

- Resolve Voxhelm API base and token as a pair from one configuration level.
  Incomplete pairs no longer inherit deployment credentials. Move mixed-level
  credentials to one level before upgrading; changing the Wagtail API base
  requires re-entering its token. Saving with both credential fields blank
  removes the site pair so deployment credentials can be used.
- Exclude view-restricted root pages from navigation links in blog, post and
  feed contexts, including for signed-in visitors. Pages beneath a restricted
  root are also omitted; member-only sites must supply their own navigation.
- Render shared feed descriptions with the blog/site default theme, ignoring
  visitor session, query and internal preview theme overrides.
