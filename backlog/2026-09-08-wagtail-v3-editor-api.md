# Wagtail v3 API and Cast programmatic authoring

Date: 2026-09-08

Status: evaluation in progress; isolated mounting/discovery and scalar
draft-write slices are implemented in test configuration only. No production
v3 integration or client migration is implemented.

Evaluate whether Wagtail 8's writable v3 REST API can replace parts of Cast's
editor API. Prefer upstream functionality where it reduces maintenance, while
preserving the workflow safeguards that authoring clients need. Daybook is
also our project and can be changed alongside Cast; compatibility with its
exact current API contract is not a requirement or a reason to retain an
otherwise unnecessary adapter. The first
deliverable is a compatibility experiment and decision, not a rewrite.

## Current state

- django-cast 0.2.66 allows patched Wagtail 7 releases and Wagtail 8. The
  default ``.venv`` resolves to Wagtail 7.4.3; the exact Wagtail 8 experiment
  runs in the ``py312-django61-wagtail80`` tox environment.
  The inspected homepage and python-podcast lockfiles also resolve to 8.0;
  this is not evidence of production deployment or v3 enablement.
- Cast currently mounts its own `/api/editor/` endpoints and the Wagtail v2
  read API. Its custom `APIField` declarations do not opt into v3 writes.
- The editor API implements Post and Episode draft create/read/update,
  explicit publishing, rendered previews, image/audio/video list/upload,
  collection discovery, custom blocks, and unsupported-block preservation.
- Updates require a revision token and support an atomic
  `require_unpublished` precondition that also rejects scheduled publication.
  Scoped tokens have separate write and publish requirements in addition to
  Wagtail permissions. Slug lookup and reservation support deterministic draft
  find-or-create workflows, including concurrent creation.
- Daybook is an existing client, not a hypothetical consumer. Its
  `../daybook/src/daybook/cast_client.py` uses draft lookup, revision checks,
  draft-only updates, and editor media endpoints.
  These are useful acceptance cases, not a fixed transport contract: payloads,
  URLs, authentication, and error handling can change in coordinated work.

Use [the current API reference](../docs/reference/api.rst) and implementation
under `src/cast/api/editor/` as the current contract. The
[original editing API plan](2026-06-19-programmatic-content-editing-api.md)
contains historical shaping entries; rendered previews and scope enforcement
are already implemented despite older deferred-status text there.

The initial analysis ran `just check` on Wagtail 8.0: 2,616 tests passed,
one skipped, 100% coverage, with lint and type checks passing. This establishes
the current Cast baseline; it does not validate v3 integration.

## Compatibility experiment evidence

Measured on 2026-09-16 with Python 3.12, Django 6.1.1, and Wagtail 8.0 in
``py312-django61-wagtail80``. The default development environment remained on
Wagtail 7.4.3. Installed source under that tox interpreter was treated as
authoritative, specifically ``wagtail.api.v3.api``, ``auth``, ``registry``,
``routers.pages``, ``routers.schema``, the read/write schema generators, and
``form_data``.

The first slice adds ``wagtail.api.v3`` and mounts its URLs only through
``tests.wagtail_v3_settings`` and ``tests.wagtail_v3_urls``. The second slice,
measured on 2026-09-17 in the same environment, adds a disposable AppConfig
that marks selected Post and Episode scalar fields writable before Wagtail
builds its v3 registry. Every Wagtail 8 tox environment first runs the complete
suite with normal ``tests.settings`` and ``tests.urls``, then runs only the
experiment module in a second process with the disposable settings. Every
django-cast production module remains unchanged. Normal Wagtail 8 test runs and
Wagtail 7 collect the experiment as a configuration-gated skip without
importing a v3 module.

Evidence labels below are deliberate: **test** means
``tests/wagtail_v3_experiment_test.py`` exercised the behavior; **source**
means it was established by reading the installed Wagtail 8.0 implementation
but was not exercised through a Cast integration test in this slice.

| Area | Classification | Evidence from this slice | Remaining work |
| --- | --- | --- | --- |
| Test-only mount | upstream equivalent | **Test:** the v3 namespace reverses under the disposable URLconf, while ``tests.urls`` does not mount it. | Decide a production route only after the evaluation; none exists now. |
| Schema discovery | upstream equivalent | **Test:** bearer-authenticated ``/schema/`` discovery includes ``cast.Post`` and ``cast.Episode`` and returns read/create/patch schemas for both. | Add agent-facing Cast block guidance only if v3 is selected. |
| Authentication identity | upstream equivalent | **Test:** anonymous and session-only schema requests return 401; a native Wagtail ``APIToken`` bearer succeeds. **Source:** bearer auth overwrites any session user. | Token migration and service-account lifecycle remain unverified. |
| Write/publish scopes | Cast extension required | **Source:** native tokens represent a user but carry no Cast ``write`` versus ``publish`` scopes. | Prove an extension point before exposing writes. |
| Live page exposure | upstream equivalent | **Test:** each anonymous type-filtered listing contains the live Post or Episode fixture id with the correct ``meta.type``. | Draft reads, exclusion behavior, and per-page permission behavior remain unverified. |
| Common page fields | upstream equivalent | **Test:** Post and Episode create/patch schemas include ``title``, ``slug``, ``seo_title``, ``search_description``, and ``show_in_menus``; draft create requests reach Wagtail's action layer. | A successful API response still requires the response-schema incompatibility below to be resolved. |
| Post field inventory | Cast extension required | **Test:** the disposable configuration makes ``visible_date`` and ``cover_alt_text`` writable; read schemas also expose ``cover_image`` and ``body``. ``cover_image``, ``body``, ``tags``, and ``categories`` remain absent from writes. **Source:** the read fields originate in existing v2 ``APIField`` declarations. | Evaluate relations and body conversion only after safe scalar updates exist. |
| Episode field inventory | Cast extension required | **Test:** Episode inherits the two Post write fields and additionally exposes ``episode_number``, ``episode_type``, ``keywords``, ``explicit``, and ``block``. A draft Episode without audio is persisted. ``podcast_audio`` and ``season`` remain absent from read/create/patch schemas. | Evaluate FK representation, same-podcast season policy, and media permissions separately. |
| StreamField schema | incompatible for self-describing agent input | **Source and test schema:** ``body`` is read as ``list[Any]`` and is absent from writes, so discovery cannot currently describe Cast's author block contract. | Evaluate a Cast adapter over ``cast.content`` rather than duplicating conversion. |
| Revision conflict and draft-only guards | unverified | **Source:** the inspected v3 update route has no Cast revision token or ``require_unpublished`` precondition. | Reproduce concurrent and scheduled-state behavior after a field is writable. |
| Write response serialization | incompatible | **Test:** Post and Episode draft creates persist, and a Post PATCH creates a revision, but each response is 422 because the inherited ``html_overview`` and ``html_detail`` v2 serializers require a request context that the v3 write response lacks. The write has committed before serialization fails. | Give v3 a transport-native read schema or establish an upstream response-context extension; do not mask committed writes as validation failures. |
| Partial update against a newer draft | incompatible | **Test:** after a newer draft changes ``cover_alt_text``, a v3 PATCH that supplies only ``visible_date`` creates a revision whose omitted cover text comes from the live row. **Source:** ``build_page_update_form`` binds the database page object and narrows the form to submitted fields. | A Cast adapter must materialize the latest draft and enforce an explicit base revision before editing. |
| Episode publication policy | unverified | **Source:** v3 publish uses Wagtail's action registry and revision publish path, which should reach ``cast.publication``. | Test create/edit/standalone/scheduled publication, including audio-less rejection. |
| Media and body conversion | Cast extension required | Existing Cast services remain the required policy seams; no v3 write path exercised them in this slice. | Keep ``cast.content`` transport-neutral and reuse media ingestion without internal HTTP calls. |

The write experiment reproduced two runtime incompatibilities without enabling
production routes: response serialization reports failure after committing a
write, and partial updates discard omitted values from a newer draft. The
StreamField limitation remains a separate schema incompatibility for the
intended self-describing agent workflow.

The next smallest experiment slice is a test-only revision-aware update
adapter. It should expose a transport-native response shape, require a base
revision, materialize the latest draft before applying an update, and prove
that stale requests fail without creating a revision. Body, publication,
preview, media upload, and Daybook migration remain later slices.

## Upstream capabilities and remaining questions

Wagtail 8 v3 provides writable page operations, revisions, images, documents,
API-enabled snippets, bearer tokens tied to users, rich-text conversion, and
OpenAPI discovery. It is explicitly a preview that may change incompatibly
in any release until stabilized. Enabling it requires separate app/URL setup.

| Area | Initial assessment | Evidence required before replacement |
| --- | --- | --- |
| Page operations | Strong overlap; v3 also offers unpublish, copy, move, and revert. | Prove Cast create/update/publish and revision behavior through supported extension points. |
| Authentication | Wagtail manages native tokens with the owning user's permissions. | Decide how service accounts and existing per-token scopes coexist; do not silently grant a drafting token publish rights. |
| Body format | v3 uses native StreamField structures and replaces the whole supplied field. Cast exposes separate overview/detail authoring lists. | Preserve omitted sections, custom blocks, IDs where required, and unsupported content; quantify adapter complexity. |
| Agent discovery | v3 provides generated OpenAPI, but its StreamField schema is currently `list[Any]`. | Supply enough Cast block guidance for an agent to produce valid payloads; do not assume OpenAPI describes every block. |
| Concurrent editing | Installed v3 code has no equivalent to Cast's required revision token or `require_unpublished`. | Demonstrate atomic conflict/schedule checks, or retain Cast's guarded update path. |
| Podcast/media behavior | Generic Wagtail endpoints do not automatically implement Cast audio/video processing or episode rules. | Verify permissions, upload/probe budgets, audio requirements, seasons, and numbering on every proposed path. |
| Rich text | Wagtail has reusable conversion/sanitization code, including nested rich-text handling in the installed v3 implementation. | Run Cast's sanitization and feature-preservation cases; retain explicit raw-HTML/inline-media policy. |
| Preview and publishing | Cast renders authenticated draft previews; its current publish action publishes the latest revision without a revision precondition. | Prove preview behavior and explicitly decide how publication binds to the revision reviewed by a human. |

Two source-level concerns need focused regression proofs:

1. The installed v3 update router builds its update form from the model row.
   The scalar write experiment confirms that a partial edit of a live page
   with a newer draft reconstructs omitted values from the live row. Any Cast
   adapter must start from the latest revision and reject stale base revisions.
2. `CustomEpisodeForm.clean()` identifies publication using the admin's
   `action-publish` form input, while Cast's editor publish handler explicitly
   checks the revision for `podcast_audio`. A v3 standalone publish bypasses
   that Cast handler. Verify create-and-publish, edit-and-publish, standalone
   publish, and scheduled publication before enabling Episode writes.

## Proposed plan

### 1. Capture the compatibility contract

Inventory the editor views, body/rich-text conversion, media/scopes code, and
tests under `tests/api/editor_*`. Trace actual Daybook usage and inspect
homepage/python-podcast authentication and custom-block configuration.

Produce a matrix mapping each operation and safeguard to one of:
upstream equivalent, Cast extension required, incompatible, or unverified.
Record the exact upstream version used. Separate current guarantees from
desirable improvements such as revision-bound publication.

Do not expand the editor API with generic CMS operations during evaluation
unless an existing consumer needs them. Existing bug fixes and security work
continue independently.

### 2. Build an isolated v3 experiment

Use an isolated test/example configuration and disposable data. Mount v3 at
an explicit preview URL and enable only the selected Cast fields needed for
one Post and one Episode workflow. Do not enable production routes or migrate
clients as part of this experiment.

Exercise create draft, read latest draft, partial edit, preview, and explicit
publish with a drafting user and a publishing user. Discover/upload an image
through v3 and attach it to a Cast body. Continue using Cast audio/video
services initially; generic snippet registration alone is not a media-upload
replacement.

Keep the existing v2 field serializers and public response contracts working.
Avoid unconditionally introducing Wagtail-8-only APIs into code imported on
supported Wagtail 7 installations.

### 3. Prove compatibility and identify shared rules

Use focused integration/regression cases for:

- Stale revisions, simultaneous updates, draft slug lookup, and same-slug
  create/rename races on SQLite and PostgreSQL.
- Atomic refusal of draft-only writes after publication or scheduling.
- Live content remaining unchanged until publication, and subsequent edits
  preserving the latest draft's omitted fields and relations.
- Overview/detail independence; custom and unsupported blocks; inaccessible
  or deleted media references; preservation of unrelated body content.
- User/page/collection permissions and separate write/publish scopes,
  including attempts to use an alternative endpoint to bypass restrictions.
- Built-in and nested rich-text sanitization, malformed HTML, configured
  features, comment anchors, raw HTML, and inline image/oEmbed rejection.
- Episode audio requirements, same-podcast seasons, metadata round trips,
  automatic numbering, publishing hooks, and scheduled revisions.
- Token-authenticated rendered previews and media upload validation,
  cumulative probe limits, per-user locks, and failure cleanup.

Move essential publication rules into shared model/service/action integration
only after establishing which entry points must invoke them. Drafts without
audio must remain valid. Check how scheduled publication and admin actions
reach the same rule; do not fix only the new endpoint.

Coordinate revision-bound publication with the existing
[security-review follow-up](2026-09-07-security-review.md), and retain the
boundaries from the [rich-text sanitization record](2026-09-07-editor-richtext-sanitization.md).
Historical-content auditing remains separate from write-path migration.

### 4. Decide the architecture from the results

Compare three concrete options:

1. Keep the editor transport and selectively reuse upstream Python helpers.
2. Retain the editor contract as a small adapter over supported Wagtail
   operations, with Cast-specific safeguards and media services.
3. Move new clients directly to v3 plus explicit Cast extensions, then migrate
   existing clients through a documented transition.

Prefer the option with fewer duplicated rules and a clear supported API
boundary. Do not add internal HTTP calls merely to reuse Wagtail code, or
couple the stable editor contract tightly to preview internals without a
version/compatibility policy. Keeping current endpoints is an acceptable
outcome if v3 cannot yet preserve their guarantees economically.

Record reproducible upstream gaps for possible issue reports; publishing
issues is a separate action. The decision must state what can be removed,
what remains Cast-owned, what awaits upstream changes, and how Wagtail 7
support is maintained or eventually retired through a separate decision.

### 5. Implement only the selected follow-up slices

Start with one independently useful reuse change and run the existing
contract tests against it. Migrate Daybook only after its draft/update/media
workflow passes end to end. Updating its client and tests is a normal part of
the migration, not a major blocker. Prefer direct v3 adoption over a permanent
compatibility adapter if the adapter would exist only to avoid changing
Daybook. Document authentication, payload/error mapping, preview behavior, and
rollback. Inventory other consumers before deciding whether route retirement
needs a deprecation period; do not assume Daybook requires one.

Keep old and new writes on the same models and revision history; do not
introduce a second content store or rewrite stored content just to switch
transport. Choose a coordinated rollout/rollback strategy for Cast and
Daybook; temporary support for both contracts is an option, not a mandatory
long-term architecture.

For implementation, update API docs and the applicable current release notes,
check affected theme/consumer repos according to `AGENTS.md`, run `just check`,
and test the relevant supported-Wagtail matrix. No release note is needed for
this planning-only entry.

## Completion criteria for this backlog item

- The isolated Post/Episode proof has a recorded compatibility matrix with
  tests or explicit unresolved blockers for every required safeguard.
- An architecture decision chooses selective reuse, an adapter, direct v3
  adoption, or deferral with reasons.
- Remaining implementation/client migration work is split into concrete
  backlog slices with dependencies, including Wagtail 7 and preview-version
  policy. Completing this evaluation does not imply migration is complete.

## Sources

Initial assessment used the installed Wagtail 8.0 code, Cast and sibling-repo
source, and the upstream documentation read on 2026-09-08. The `stable` links
can advance; recheck them against the experiment's exact version.

- [Wagtail 8.0 release notes](https://docs.wagtail.org/en/stable/releases/8.0.html)
- [v3 setup, scope, and limitations](https://docs.wagtail.org/en/stable/advanced_topics/api/v3/index.html)
- [Pages and writable fields](https://docs.wagtail.org/en/stable/advanced_topics/api/v3/pages.html)
- [Token authentication and permissions](https://docs.wagtail.org/en/stable/advanced_topics/api/v3/authentication.html)
- [StreamField replacement and schema limitations](https://docs.wagtail.org/en/stable/advanced_topics/api/v3/streamfield.html)
- [Rich-text formats](https://docs.wagtail.org/en/stable/advanced_topics/api/v3/rich_text.html)
