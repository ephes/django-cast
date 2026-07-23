# Cast Studio product boundary and django-cast implications

Date: 2026-07-09

Status: complete boundary decision (2026-07-22). Cast Studio planning and any
implementation live in a private sibling repository; this historical record
keeps django-cast's public backlog self-contained and records only the
decisions and possible core implications.

## Summary

Cast Studio is a proposed macOS-first Electron application for non-developers
who want to evaluate and use a private local django-cast blog or podcast without
Python, Git, repositories, command-line setup, or account signup.

It is a separate product and deployment target, not an Electron shell to add to
the django-cast package repository.

The onboarding review is complete. The supported paths have distinct audiences:

- ``django-cast-quickstart`` generates new developer projects;
- ``example/scripts/bootstrap_example_data.py`` prepares disposable content for
  django-cast contributors;
- ``ensure_reference_site`` creates repeatable theme-development and visual-test
  content;
- Cast Studio owns the possible installed, non-developer desktop experience.

Local-to-hosted synchronization and an external editor client remain separate
research topics. Neither is required by Cast Studio's first local blog proof.

The first proof is deliberately narrow:

- macOS Apple silicon;
- Electron, based on `desktop-django-starter`;
- signed/notarized app and DMG with stapled tickets for offline Gatekeeper
  validation;
- offline-capable local use with no signup;
- purpose-built Cast Studio Django project depending on pinned django-cast and
  `cast-bootstrap5` packages;
- one local SQLite database and media directory under application data;
- one app-created local Wagtail owner with no universal password;
- Wagtail admin as the editor;
- blog + image create/edit/preview/publish;
- persistence across quit/relaunch;
- user-visible backup;
- no task worker, podcast media tooling, importer, hosting, or Windows release
  in the first proof.

## Evidence already available

`desktop-django-starter` already used django-cast as a staged wrapping
benchmark. Its deterministic scaffold successfully built a standalone Python
runtime, installed django-cast and dependencies, collected static assets, and
served `/health/` and Wagtail's default root page through Electron.

That evidence de-risks Python/Wagtail bundling, but it did not prove a useful
product:

- no Blog/Post or Podcast/Episode page;
- no Wagtail owner-login flow was exercised; the scaffold appears to migrate a
  fresh database without creating an owner, so bootstrap behavior still needs
  explicit verification;
- no admin editing, preview, chooser, or publishing flow;
- no image/audio persistence;
- a django-vite warning on deeper django-cast pages;
- no signed installed-app acceptance run for this product.

Cast Studio therefore needs product-specific packaged settings and acceptance
tests rather than a new generic desktop architecture.

## Repository boundary

### Cast Studio owns

- Electron shell and application identity;
- purpose-built Django project/settings/URLs;
- local shell-token middleware and desktop-only owner bootstrap;
- local app-data paths, logs, backup UX, and updater feed;
- first-run/sample content UX;
- packaged theme and Vite manifest configuration;
- macOS signing/notarization workflow;
- future hosting entry points;
- initially, podcast import provenance and UI.

### django-cast owns

- reusable Blog/Podcast/Post/Episode models and Wagtail behavior;
- themes and extension contracts;
- media validation, rendering, feeds, editor API, revisions, and permissions;
- generic capabilities that are independently useful to normal hosted sites.

No desktop middleware, Electron dependency, billing concept, local auto-login,
or provider-specific deployment code should be added to django-cast core.

## Onboarding relationship

Cast Studio and `django-cast-quickstart` serve different audiences:

- quickstart remains a developer project generator;
- Cast Studio is an installed end-user application;
- Wagtail remains the shared authoring interface;
- the existing example bootstrap/reference-site tools remain development and
  theme-test tools unless generic seeding primitives are deliberately extracted.

The broader onboarding review should document these separate paths instead of
trying to make one command satisfy both.

## Custom desktop editor decision

A custom desktop content editor is not required for Cast Studio's first proof.
Electron supplies distribution, lifecycle, navigation, update, backup, and
future hosting controls; Wagtail supplies content editing.

An external editor API client remains a distinct possible example. It would be
useful for offline editing of a remote site, multi-site workflows, specialized
media/background work, or agent-assisted authoring, but it should not be treated
as a dependency of the local Electron playground.

## Local-to-hosted boundary

Cast Studio must not copy a local SQLite database over a production database.
A future **Put this site online** flow requires one of two separately designed
models:

1. a versioned portable content/media export imported into a provisioned
   hosted site; or
2. a hosted trial created independently and later converted to a paid tenant.

That work requires identity, billing, domains/TLS, storage, backups, upgrades,
rollback, and support ownership in a separate hosting control plane. It is not
part of django-cast core or the first desktop proof.

## Podcast importer follow-up

The private Cast Studio plan uses the `django-chat` sibling importer as a
concrete reference. Reusable lessons include:

- parse into immutable source structures before model writes;
- durable podcast/episode/audio provenance;
- idempotent reruns using GUID/provider identifiers;
- limited and dry-run planning;
- explicit, streaming artwork/audio copy;
- HTML sanitization before Wagtail RichText storage;
- safe imported link schemes;
- SSRF-resistant requests with redirect checks and connect-time IP pinning;
- fixture-only automated tests.

Cast Studio's importer must initially be generic public RSS, not Simplecast- or
Django Chat-specific. It should add a hardened XML parser, pure pre-write
planning, feed/media byte limits, explicit user-selected podcast-source identity,
per-field last-applied provenance for local-edit conflict handling, and
progress/cancel/retry behavior.

The first Cast Studio proof remains blog-only. The intended sequence is:

1. packaged blog + image authoring;
2. podcast/audio authoring and FFmpeg/FFprobe distribution decision;
3. latest-N public feed import with preview and provenance;
4. hosting conversion research.

Implement importer provenance in Cast Studio first. Promote a contract or model
to django-cast only after it proves generic across more than one consumer.

## Potential future core work

These are not accepted django-cast implementation tasks yet:

- safe, generic site/bootstrap service primitives independent of dev fixtures;
- a capability/version endpoint if external shells need one;
- portable content/media export/import after a concrete hosted-conversion
  contract exists;
- generic RSS import services after the Cast Studio and Django Chat approaches
  demonstrate a stable common core;
- media-probe executable configurability if bundled FFmpeg cannot be exposed
  through a normal process `PATH`.

Each should be shaped and justified separately rather than added preemptively
for Cast Studio.

## Completion

The private Cast Studio specification has reviewed requirements and can proceed
without an unrecorded django-cast core dependency. django-cast's documentation
now distinguishes the developer quickstart, contributor example bootstrap,
theme reference site, and separate desktop product. The remaining local sync,
external client, and podcast import questions stay as explicit backlog items;
no speculative desktop capability is accepted into django-cast core.
