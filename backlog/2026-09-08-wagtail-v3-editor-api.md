# Wagtail v3 API and Cast programmatic authoring

Date: 2026-09-08

Status: evaluation in progress; isolated mounting/discovery, scalar
draft-write, revision-aware update-adapter, and publication-policy slices are
implemented in test configuration only, along with an authorization/scope
experiment, a draft-state precondition experiment, a revision-bound
publication experiment, a scheduling-input experiment, a draft read and
preview experiment, a body-conversion experiment, and a media experiment. No production v3 integration or client migration is
implemented.

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
builds its v3 registry. The third slice, measured on 2026-09-17, registers a
disposable Cast router over Wagtail's v3 form builder and edit action. It
requests a row lock, checks a strong ``If-Match`` revision identifier,
materializes the latest draft, and returns a minimal response that does not
invoke Cast's v2 serializers. The row lock is effective on databases such as
PostgreSQL but is a no-op on the experiment's SQLite database, so concurrent
atomicity is not yet proven. The fourth slice, measured on 2026-09-17, invokes
the stock create-and-publish, edit-and-publish, and standalone publish routes
for Episodes, and executes a scheduled revision that was approved through the
standalone route. Every Wagtail 8 tox environment first runs the complete suite
with normal ``tests.settings`` and ``tests.urls``, then runs only the experiment
module in a second process with the disposable settings. The fifth slice,
measured on 2026-09-17, gives separate non-staff bearer-token users tree-scoped
change and publish permissions, then exercises Post and Episode actions inside
and outside those trees. The sixth slice, measured on 2026-09-17, changes the
same latest Post and Episode revision from draft to live or scheduled before an
update. It compares stock v3 with an explicit test-adapter precondition that
requests locks on the page and existing revision rows. The test is sequential
on SQLite and does not prove PostgreSQL serialization. The seventh slice,
measured on 2026-09-17, selects a Post or Episode revision through the v3
revision listing, saves a newer draft, and then calls stock standalone
publication. It compares that with a test-adapter publish route that requires
the selected revision in a strong ``If-Match`` header, requests a page-row
lock, and delegates to Wagtail's registered page publish action. Those tests
are also sequential on SQLite. The eighth slice, measured on 2026-09-17,
opts Wagtail's own ``go_live_at`` and ``expire_at`` fields into the disposable
Post and Episode write inventory, submits them through the adapter, and
schedules the selected revision through the revision-bound publish route.
The ninth slice, measured on 2026-09-17, reads Post and Episode detail
through stock v3, compares stock draft-read access with Cast's editor preview
rule, and adds a test-only bearer-authenticated preview route that renders the
latest revision through Wagtail's ``make_preview_request``. The tenth slice,
measured on 2026-09-17, opts ``body`` into the disposable write inventory,
submits native StreamField values through stock v3, and adds a test-adapter
route that converts Cast author blocks through ``cast.content``. The
eleventh slice, measured on 2026-09-17, inventories the installed v3 media
types and exercises stock v3 image uploads under collection permissions and
anonymous image listing. Every django-cast
production module remains unchanged. Normal Wagtail 8 test runs and Wagtail 7
collect the experiment as a configuration-gated skip without importing a v3
module.

Evidence labels below are deliberate: **test** means
``tests/wagtail_v3_experiment_test.py`` exercised the behavior; **source**
means it was established by reading the installed Wagtail 8.0 implementation
but was not exercised through a Cast integration test in this slice;
**inference** identifies a conclusion drawn from that evidence.

| Area | Classification | Evidence from this slice | Remaining work |
| --- | --- | --- | --- |
| Test-only mount | upstream equivalent | **Test:** the v3 namespace reverses under the disposable URLconf, while ``tests.urls`` does not mount it. | Decide a production route only after the evaluation; none exists now. |
| Schema discovery | upstream equivalent | **Test:** bearer-authenticated ``/schema/`` discovery includes ``cast.Post`` and ``cast.Episode`` and returns read/create/patch schemas for both. | Add agent-facing Cast block guidance only if v3 is selected. |
| Authentication identity | upstream equivalent | **Test:** anonymous and session-only schema requests return 401; a native Wagtail ``APIToken`` bearer succeeds. **Source:** bearer auth overwrites any session user. | Token migration and service-account lifecycle remain unverified. |
| Page authorization | upstream equivalent | **Test:** a non-staff token owner with change permission on one Blog can update its Post but receives 403 for a Post under another Blog and for publish. A publish-only user cannot update an Episode but can publish it. **Source:** Wagtail's route permission and action layers perform the model-level and instance/tree checks. | Extend to create-parent and page-restriction cases only if v3 remains a candidate. |
| Wagtail admin access | Cast extension required | **Test:** a non-staff user without ``wagtailadmin.access_admin`` can update through v3 when its tree permission allows it. **Source:** the current editor API requires admin access in addition to page permission. | Explicitly choose the service-account admission policy before production enablement. |
| Write/publish scopes | Cast extension required | **Test:** one native token for a user with change and publish page permissions performs both operations, and model-field introspection finds no ``scope`` or ``scopes`` field. **Inference:** tree permissions can separate drafting and publishing users, but native tokens cannot provide different write and publish scopes for the same user. | Prove a token-auth extension point or accept separate service accounts before exposing writes. |
| Live page exposure | upstream equivalent | **Test:** each anonymous type-filtered listing contains the live Post or Episode fixture id with the correct ``meta.type``. | Exclusion of restricted pages remains unverified. |
| Page detail reads | Cast extension required | **Test:** stock v3 detail for Post and Episode returns 422 for anonymous and bearer-authenticated callers, with ``version=live`` and ``version=draft``. The error locations are the inherited ``html_overview`` and ``html_detail`` fields. **Source:** v3's ``APIField(serializer=...)`` compatibility shim binds a copied DRF field with no parent and never passes the resolver context. Cast's ``HtmlField`` reads ``self.context["request"]``. **Inference:** stock v3 cannot currently read any Cast Post or Episode detail. The failure is in the shared serializer bridge, not in the write actions. | Choose between a transport-native Cast read schema and an upstream context fix. The write-response failures above report the same two fields. |
| Draft read access | Cast extension required | **Test:** with a ``cast.Blog`` draft, whose schema has no ``HtmlField``, a publish-only user with no edit permission reads the draft title through ``version=draft``. An anonymous caller receives the live title from the same query, and a user with permissions only under another blog receives 404. **Source:** the detail route returns ``get_latest_revision_as_object()`` for any authenticated user within ``explorable_instances``. The editor API requires admin access and edit permission for draft reads and previews. | A Cast read route would need to keep the edit-permission rule, because stock v3 lets explore-only users read drafts. |
| Rendered draft preview | Cast extension required | **Test:** the complete installed v3 page-route inventory contains detail, revision, and action routes but no preview route. A test-adapter route renders the latest Post or Episode draft as ``text/html`` without publishing it. It returns 401 for a session-only caller, 403 for a publish-only user and for a change user outside the page tree, and 404 for a missing page; none of the denied bodies contains the draft title. A tree-scoped editor receives the preview. The rendered request is anonymous for a bearer-only call, but sees the session user when a session cookie is also sent. A preview GET also re-adds a body image to the page's stored media relationship. **Source:** the route delegates to the same ``make_preview_request`` used by the editor API. Wagtail copies cookies and other original headers into the fake request and runs middleware, so the bearer principal is not the rendering identity. Cast's ``Post.serve_preview`` calls ``prepare_post_media``, which adds and removes stored media relationships and creates missing renditions. **Inference:** rendered previews are not read-only in the existing editor API, the Wagtail admin, or this adapter. | Keep rendered previews Cast-owned. Before exposing a v3 preview, define the rendering identity (strip cookies, or render as the bearer user) and decide whether preview may synchronize media relationships; this also applies to the existing editor preview. Admin-access admission remains the policy decision recorded above. |
| Common page fields | upstream equivalent | **Test:** Post and Episode create/patch schemas include ``title``, ``slug``, ``seo_title``, ``search_description``, and ``show_in_menus``; draft create requests reach Wagtail's action layer. | A successful API response still requires the response-schema incompatibility below to be resolved. |
| Post field inventory | Cast extension required | **Test:** the disposable configuration makes ``visible_date``, ``cover_alt_text``, and (since the body slice) ``body`` writable; read schemas also expose ``cover_image``. ``cover_image``, ``tags``, and ``categories`` remain absent from writes. Once ``body`` is writable, stock create-and-publish requires a valid body before Cast's publication policy runs. **Source:** the read fields originate in existing v2 ``APIField`` declarations. | Evaluate relation fields only if v3 writes are selected. |
| Episode field inventory | Cast extension required | **Test:** Episode inherits the two Post write fields and additionally exposes ``episode_number``, ``episode_type``, ``keywords``, ``explicit``, and ``block``. A draft Episode without audio is persisted. ``podcast_audio`` and ``season`` remain absent from read/create/patch schemas. | Evaluate FK representation, same-podcast season policy, and media permissions separately. |
| StreamField schema | incompatible for self-describing agent input | **Test:** the opted-in Post patch schema describes ``body`` only as an array with an empty ``items`` schema. **Source:** v3 reads ``body`` as ``list[Any]``, so discovery cannot describe Cast's author block contract. | Publish Cast block guidance separately if an agent-facing v3 route is chosen. |
| Revision conflict guard | Cast extension required | **Test:** the disposable adapter accepts a quoted base revision and returns 409 for a sequential stale request without creating a revision. **Source:** the stock v3 update route has no revision precondition; the adapter uses a transaction and ``select_for_update``. SQLite ignores that lock, and no concurrent test was run. | Prove the race on PostgreSQL and SQLite or retain the existing editor guard; do not infer atomicity from the sequential test. |
| Draft-only live-page guard | Cast extension required | **Test:** after the same latest Post or Episode revision becomes live, stock v3 accepts another draft edit and creates a revision. The test adapter's optional precondition instead returns ``409 published_post`` without writing, while still allowing an unpublished page. This proves sequential behavior on SQLite only. **Source:** the stock update route and edit action have no live-page equivalent to Cast's ``require_unpublished`` check. | Preserve the client-selectable precondition in any v3 adapter and explicitly decide its default; the revision id alone does not detect publication of that same revision. Prove its concurrency behavior on PostgreSQL. |
| Scheduled-state guard | upstream equivalent | **Test:** stock v3 returns 403 and creates no revision after the same latest Post or Episode revision is scheduled. The adapter can map that state to Cast's explicit ``409 scheduled_post`` contract before invoking the action. **Source:** Wagtail's ``ScheduledForPublishLock`` applies to every user, and the edit action checks it. | Reuse the upstream lock unless a stable machine-readable conflict code is required; PostgreSQL concurrency remains unproven. |
| Write response serialization | Cast extension required | **Test:** stock Post and Episode creates and a stock Post PATCH commit before returning 422 because inherited ``html_overview`` and ``html_detail`` v2 serializers lack request context. A successful standalone Episode publish and schedule also commit before returning the same 422. The adapter returns 200 with ids and native metadata only after its revision is created; Wagtail's form-error handler returns 422 for an invalid Episode scalar without creating a revision. | Decide whether a supported transport-native schema extension is preferable to an upstream response-context change. |
| Partial update against a newer draft | Cast extension required | **Test:** the stock route replaces an omitted newer-draft cover value with the live value. The adapter preserves omitted values for both Post and Episode while updating a supplied scalar. **Source:** Wagtail's form builder preserves omitted fields on the object it is given, so the adapter supplies the latest revision object instead of the live row. | Extend the proof to relations and StreamField only in later focused slices. |
| Episode publication policy | Cast extension required | **Test:** Cast's existing publication hook rejects audio-less Episodes through stock create-and-publish, edit-and-publish, and standalone publish. Create and edit roll back the tentative page/revision. A valid audio Episode becomes live. A revision scheduled through the standalone route is rechecked and rejected after its audio is deleted. **Source:** all routes delegate to Wagtail revision actions, where ``cast.publication`` is installed. | Preserve the existing shared Cast hook; no v3-specific publication policy adapter is needed for these paths. Revision binding and permissions are recorded in their own rows. |
| Publication validation response | Cast extension required | **Test:** policy rejection is a truthful 422 and does not publish, but Wagtail's generic Django validation handler returns only the message, without Cast's ``podcast_audio`` field or ``required`` code. | Define a transport-native structured error adapter if v3 is selected. |
| Revision-bound publication | Cast extension required | **Test:** a caller selects revision A from the v3 revision listing, then revision B is saved. Stock standalone publish ignores a quoted ``If-Match: "A"`` and makes B live for both Post and Episode, still returning the post-commit 422. For an Episode whose newer revision lacks audio, Cast's policy rejects B, so neither revision is published. The test adapter instead returns ``409 revision_conflict`` with B's id and publishes neither revision, including when B is a valid audio Episode and A is not. When A is still latest, the adapter returns 200 and A becomes the live revision. An audio-less selected Episode revision receives the shared policy's 422 without publication. Missing, bare, non-integer, and weak tokens return 400. Session-only calls return 401; change-only users and publish users outside the page's tree return 403 without the conflict body. **Source:** the stock route accepts no body or revision parameter, reads ``page.get_latest_revision()``, and has no route transaction or row lock. ``PublishPageRevisionAction`` checks only page publish permission, not Wagtail edit locks. Cast's policy hook opens its own transaction around the revision action. The ``revert`` action takes a ``revision_id`` but creates a new draft revision with change permission; it does not publish the selected revision. **Inference:** stock v3 has the same latest-revision race that Cast's optional editor ``If-Match`` mitigates, and a thin adapter can bind approval to a revision without duplicating publication policy. | The adapter's row lock matches the editor API design, but SQLite ignores it; prove the publish-versus-draft race on PostgreSQL. Decide whether the token is mandatory, whether an already-live page with no newer draft is rejected as in the editor API, and whether publication should honor Wagtail edit locks. |
| Scheduling input | Cast extension required | **Test:** stock ``cast.Blog`` read/create/patch schemas have no ``go_live_at`` or ``expire_at``; the disposable opt-in makes both writable for Post and Episode. A future ``go_live_at`` written through the adapter, followed by revision-bound publication, returns 200 with ``live: false`` and no live revision. The selected revision receives ``approved_go_live_at``, is the only item in the v3 revision listing filtered by that time, and places the page under ``ScheduledForPublishLock``. A past ``go_live_at`` publishes immediately. An audio-less Episode is rejected with 422 before approval, and no schedule log is written. Submitting ``go_live_at`` later than ``expire_at`` in one request returns 422 for both fields without a revision. Submitting only ``go_live_at`` after an earlier request set ``expire_at`` is accepted, leaving a draft whose ``go_live_at`` is later than its ``expire_at``. Earlier tests show that the scheduler rechecks an approved revision. **Source:** v3's base page write inventory is ``title``, ``slug``, ``seo_title``, ``search_description``, and ``show_in_menus``. Wagtail's admin form checks ``go_live_at``/``expire_at`` only when both are bound, and v3 partial updates bind only submitted fields. Cast's editor API accepts no schedule input and only reports ``status: "scheduled"``. **Inference:** scheduling is not a current editor-API guarantee. Exposing it through v3 needs an explicit field opt-in plus a Cast check against the stored counterpart value. | Decide whether programmatic scheduling is required at all. If it is, validate the merged ``go_live_at``/``expire_at`` pair in the adapter and define its read representation; the page detail schema exposes it only after the opt-in. |
| Native body writes | incompatible with Cast body safeguards | **Test:** a stock native body PATCH replaces the whole field, dropping the omitted ``detail`` section, and commits before the known 422. Wagtail's rich-text input sanitizer removes a script, a ``javascript:`` link, and an ``onerror`` image. A non-staff page editor without image permissions can store an existing image id, and a missing image id is stored as ``null``. An unknown block type returns 422 without a revision. **Source:** v3 flattens native values into the StreamField form (``form_data.flatten_block_value``). Chooser blocks resolve ids without a ``choose`` permission check. Rich text passes through ``DbHTMLConverter``. **Inference:** native writes bypass Cast's per-section preservation and media-choice policy. | Do not expose native ``body`` writes for Cast pages. |
| Author-block body conversion | Cast extension required | **Test:** a test-adapter route with a strong ``If-Match`` converts Post and Episode ``overview`` author blocks through ``cast.content``, stores the converted paragraph and image, and leaves the existing ``detail`` section unchanged in parsed StreamField data. A caller without image ``choose`` permission receives ``422 validation_error`` at ``detail.0.value.id`` with code ``not_found``, and an unsupported author block is reported at ``overview.0.type``. Neither creates a revision. Empty input returns 400, a stale base returns 409, an unquoted token returns 400, and an out-of-tree editor receives 403 without the current revision id. **Source:** the adapter calls ``cast.content.convert.author_blocks_to_section`` and saves through Wagtail's registered edit action. It reuses ``_section_value`` and ``_body_sections_with_replacements`` from the DRF ``PostEditorMixin``. **Inference:** ``cast.content`` is reusable without transport coupling, but the section-merge rule still lives in the DRF editor view. | Move section selection and merging into ``cast.content`` before any production adapter reuses them. Media upload remains a separate slice. |
| Image upload | Cast extension required | **Test:** a bearer user with ``add_image`` on two collections receives 422 at ``collection`` for an unpermitted or missing collection and 422 at ``file`` for non-image bytes, creating no image. A permitted upload returns 201 and records the uploader and the requested collection. A user with exactly one usable collection who requests another one receives 201, and the image is stored in the usable collection instead. An add-only user can upload an image that ``get_choosable_image`` then hides, so the Cast body adapter refuses to attach it with ``not_found``. **Source:** v3 builds Wagtail's admin image form, whose collection field is limited to ``add`` collections and hidden when only one is available. Cast's editor upload requires ``add`` and ``choose`` on the target collection and returns ``collection_permission_denied`` for any other requested collection. **Inference:** upstream image validation and collection scoping are reusable, but silent collection substitution and add-without-choose uploads differ from Cast's contract. | Keep a Cast upload route, or accept the upstream contract explicitly and document the substitution. |
| Audio, video, and transcripts | Cast extension required | **Test:** the v3 schema registry lists ``wagtailimages.Image`` and ``wagtaildocs.Document`` but no ``cast.Audio``, ``cast.Video``, or ``cast.Transcript``; the installed route names contain no audio, video, or transcript routes. **Source:** v3 registers snippet types only for registered snippet models with API fields; Cast media are not among them. Cast's upload lock, probe budget, derivation, and cleanup live in its media-ingestion service. | Keep Cast audio/video/transcript upload routes over the existing ingestion service; do not use snippet registration as a substitute. |
| Public image reads | upstream equivalent | **Test:** anonymous v3 and Cast's existing v2 image listings both return the same unrestricted image. **Source:** v3 uses the v2-parity queryset that excludes only restricted collections. The editor media list additionally filters by ``choose``. | Keep editor-style choose filtering for authoring pickers. |

The stock write experiment reproduced two runtime incompatibilities without
enabling production routes: response serialization reports failure after
committing a write, and partial updates discard omitted values from a newer
draft. The third slice proves that a small Cast adapter can avoid both for
scalar updates while reusing Wagtail's form builder and edit action. It also
proves bearer authentication on the adapter and rejects action-bearing
requests (``publish`` is the only action accepted by Wagtail 8.0's update
schema) so this experiment cannot become an untested publication path. The
fourth slice shows that stock v3 publication reaches the shared Cast policy;
it does not require policy duplication. Successful publication still inherits
the stock response-serialization failure, while rejected publication returns a
truthful but less structured validation response. The StreamField limitation
remains a separate schema incompatibility for the intended self-describing
agent workflow. The sixth slice shows that Wagtail's scheduled-publication lock
already blocks scheduled edits, but a live-page draft-only precondition still
requires a Cast adapter. Sequential checks in that test adapter preserve Cast's
explicit conflict codes without adding production behavior; the locking design
mirrors the editor API, but this SQLite slice does not prove its concurrency
behavior.

The seventh slice shows that stock standalone publication publishes the latest
revision at request time, so a newer draft can go live instead of the reviewed
one. A test adapter that requires the selected revision id rejects that case
with ``409`` before invoking Wagtail's publish action, while successful
publication and Episode policy still run through that action.

The eighth slice shows that stock v3 has no schedule input. After a
disposable field opt-in, revision-bound publication schedules exactly the
selected revision through Wagtail's action, and Cast's audio policy still
rejects it before approval. Partial updates, however, skip Wagtail's
go-live/expiry cross-check when only one of the two fields is submitted.

The ninth slice shows that stock v3 cannot serialize any Cast Post or Episode
detail response, live or draft. Its draft selection is gated by explore
permission rather than edit permission, and it has no rendered preview. A thin
Cast route can reuse Wagtail's preview machinery under the editor API's edit
rule. That machinery renders with the session identity rather than the bearer
token, and Cast's preview synchronizes media relationships as a side effect.

**Source:** the installed ``wagtail.images``, ``wagtail.documents``, and
``wagtail.snippets`` app configs register image, document, and snippet
routers with the v3 API, so media can be measured directly.

The tenth slice shows that native v3 body writes replace the whole field and
skip Cast's media-choice checks, while a thin adapter can reuse
``cast.content`` for author-block conversion and preserve the untouched
section. The section-merge helper still lives in the DRF editor view.

The eleventh slice shows that stock v3 image uploads reuse Wagtail's image
validation and collection scoping, but may substitute the requested
collection and do not require ``choose``. v3 has no route for Cast audio,
video, or transcripts, so Cast's ingestion service stays authoritative.

The remaining decision-relevant gap is concurrency: the adapter row locks and
the editor API's guards are proved only by sequential SQLite tests. The next
slice should determine whether a PostgreSQL run is available for the
experiment; if not, record that as an explicit blocker and state whether it
changes the architecture choice. The architecture decision follows.

## Upstream capabilities and remaining questions

Wagtail 8 v3 provides writable page operations, revisions, images, documents,
API-enabled snippets, bearer tokens tied to users, rich-text conversion, and
OpenAPI discovery. It is explicitly a preview that may change incompatibly
in any release until stabilized. Enabling it requires separate app/URL setup.

| Area | Initial assessment | Evidence required before replacement |
| --- | --- | --- |
| Page operations | Strong overlap; v3 also offers unpublish, copy, move, and revert. | Prove Cast create/update/publish and revision behavior through supported extension points. |
| Authentication | Wagtail manages native tokens with the owning user's permissions. | Decide how service accounts and existing per-token scopes coexist; do not silently grant a drafting token publish rights. |
| Body format | v3 uses native StreamField structures and replaces the whole supplied field. Cast exposes separate overview/detail authoring lists. | The body-conversion experiment above shows a thin ``cast.content`` adapter preserving the other section; custom and unsupported block round trips remain covered only by existing editor tests. |
| Agent discovery | v3 provides generated OpenAPI, but its StreamField schema is currently `list[Any]`. | Supply enough Cast block guidance for an agent to produce valid payloads; do not assume OpenAPI describes every block. |
| Concurrent editing | Installed v3 code has no revision token or live-page `require_unpublished` equivalent; its scheduled-publication lock does reject scheduled edits. | Prove the remaining PostgreSQL races, or retain Cast's page-locking guarded update path. |
| Podcast/media behavior | Generic Wagtail endpoints do not automatically implement Cast audio/video processing or episode rules. | Verify permissions, upload/probe budgets, audio requirements, seasons, and numbering on every proposed path. |
| Rich text | Wagtail has reusable conversion/sanitization code, including nested rich-text handling in the installed v3 implementation. | Run Cast's sanitization and feature-preservation cases; retain explicit raw-HTML/inline-media policy. |
| Preview and publishing | Cast renders authenticated draft previews; its publish actions bind to a reviewed revision only when the optional ``If-Match`` header is sent. Stock v3 publishes the latest revision and has no selector or rendered preview. | The experiments above show that both need Cast routes; decide whether the revision token is mandatory. |

The experiments establish two important action-path findings:

1. The installed v3 update router builds its update form from the model row.
   The scalar write experiment confirms that a partial edit of a live page
   with a newer draft reconstructs omitted values from the live row. Any Cast
   adapter must start from the latest revision and reject stale base revisions.
2. `CustomEpisodeForm.clean()` identifies publication using the admin's
   `action-publish` form input, but v3 does not need to emulate that input.
   Create, edit, standalone, and scheduled publication all reach the shared
   ``cast.publication`` revision hook. Rejected create/edit operations roll
   back, and successful publication must still solve the response-schema gap.
3. Publishing or scheduling the same latest revision does not change its id.
   Stock v3 therefore accepts a new draft edit after publication, while its
   edit action rejects a scheduled page through ``ScheduledForPublishLock``.
   In sequential tests, the adapter preserves Cast's explicit live and
   scheduled conflict responses while requesting the same page and existing
   revision-row locks as the editor API. PostgreSQL serialization remains
   unproven in this experiment.
4. Stock standalone publication is not bound to the revision a caller
   reviewed: it publishes whichever revision is latest when the request runs,
   and ignores ``If-Match``. Publication policy still inspects that published
   revision. A test adapter can check a quoted revision id under a requested
   page-row lock and then delegate to the same Wagtail action; its sequential
   SQLite tests do not prove the concurrent guarantee.

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
