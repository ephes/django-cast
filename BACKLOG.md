# Backlog

This is the local backlog for django-cast. Keep it small and actionable.

- Use this file as the index for future work.
- Put larger feature notes in `backlog/*.md` and link them from here.
- Do not keep a separate done list. Completed user-facing work belongs in the current release notes under
  `docs/releases/`; implementation history belongs in git.
- GitHub issues are optional for public coordination, but local planning starts here.

## Ready

- [ ] Harden modelsearch follow-ups
  - Notes: [backlog/2026-04-22-search-hardening-follow-ups.md](backlog/2026-04-22-search-hardening-follow-ups.md)
  - Scope: decide whether the current normalization-only guard needs a database-exception backstop, and file
    the upstream `django-modelsearch` issue.
  - Done when: the local behavior decision is documented, any needed guard is implemented and tested, and the
    upstream issue is filed or explicitly deferred.

- [ ] Repository read-model cleanup experiment
  - Notes: [backlog/2026-04-18-repository-readmodels.md](backlog/2026-04-18-repository-readmodels.md)
  - Scope: try local typed read shapes around the repository layer before considering `django-mantle`.
  - Done when: a narrow branch proves whether typed read shapes clarify repository logic without changing
    template contracts or query counts.

## Later

- [ ] Documentation polish pass
  - Notes: [backlog/2025-07-11-documentation-polish.md](backlog/2025-07-11-documentation-polish.md)
  - Scope: retire the stale documentation task list by checking remaining docs structure, links, and warnings.
  - Done when: docs build cleanly and remaining docs TODOs are either implemented or intentionally removed.
