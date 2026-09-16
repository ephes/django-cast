# Publication policy service

Date: 2026-09-16   Status: Implemented on 2026-09-16

Implementation commits, by slice: 1 — `2dbdb954` (policy and adapters); 2a — `c87c6024` (installer relocation);
2b — `63a25ff6` (shared enforcement); 2c — `e638f007` (system check); 3 — `17adff2e` (scheduled rejection);
4 — `e71822e7` (boundary ownership); 5 — `972ab86b` (revision-bound editor publication).

## Problem

The rule "an episode needs `podcast_audio` before it goes live" is implemented twice and enforced on two of the
many publish paths. `CustomEpisodeForm.clean` (`src/cast/models/pages.py:653-658`) fires only when the Wagtail
admin form POST carries `action-publish`; the editor API's `_reject_unpublishable_episode`
(`src/cast/api/editor/views.py:344-357`) re-implements the predicate and the message, and `_publish`
(`views.py:360-385`) calls it at line 378 before `revision.publish(user=user)` at line 379. Both are transport
checks: nothing enforces the rule where Wagtail actually flips `live` to true. Every other publish path bypasses
them: `publish_scheduled` (`wagtail/management/commands/publish_scheduled.py:117` in 7.0.9, `:120` in 8.0 calls
`rp.publish(...)`), the admin bulk "Publish" action (`wagtail/admin/views/pages/bulk_actions/publish.py:46,67`),
workflow approval (`wagtail/workflows.py:27`), Wagtail's admin API publish action
(`wagtail/admin/api/actions/publish.py:19`), Wagtail 8.0's v3 `pages/{id}/actions/publish/`
(`wagtail/api/v3/routers/pages.py:407-422`), and any `revision.publish()` from code.

Two further publish-time behaviours live in unrelated mechanisms. Episode numbering wraps Wagtail's private
`PublishRevisionAction._publish_revision` (`src/cast/podcast_numbering.py:168-199`, installed from
`src/cast/apps.py:59`, guarded by `_validate_publish_revision_api` at `:146-157`). Post media preparation is a
`page_published` receiver (`src/cast/post_media.py:90-102`, installed from `apps.py:60`). A reader needs four
files to answer "what happens when a Post is published", and every new transport or rule is wired by hand.

The security review left the "Publication approval binding" observation open
(`backlog/2026-09-07-security-review.md:140-146`; there is no `SEC-*` label for it): `_publish` publishes
`page.get_latest_revision()` without a revision precondition, and `docs/reference/api.rst:816-824` documents
that gap. There is no shared place to put that precondition today.

## Current call sites

Paths: A = admin form, B = bulk publish, S = scheduled go-live, W = workflow approval, X = Wagtail admin API,
V = Wagtail 8.0 v3, C = `revision.publish()` from code, E = editor API publish endpoint.

All paths under `src/cast/`; Wagtail paths under its package root.

| Site | File:line | Owns today | Bypassed by |
| --- | --- | --- | --- |
| Admin form `clean` | `models/pages.py:653-658` | audio rule, keyed on `action-publish` | B S W X V C |
| Editor API `_publish` | `api/editor/views.py:344-357,378` | audio rule copy; 409 codes; permission | A B S W X V C |
| `_publish_revision` wrapper | `podcast_numbering.py:168-199`, `apps.py:59` | numbering | none |
| `page_published` receiver | `post_media.py:90-102`, `apps.py:60` | media prep | none; fires on copy/alias too |
| `before_publish_page` hook | unused; `admin/views/pages/edit.py:589`/`:700` | nothing | all but A; post-revision |

## Target design

Choke point: the `_publish_revision` wrapper. It is the only point every path above passes through in both
supported Wagtail versions (`Revision.publish` -> `Page.publish` -> `PublishPageRevisionAction.execute` ->
`_publish_revision`; `wagtail/models/revisions.py:201-216`, `models/pages.py:1157-1172` in 7.0.9 and
`:204-219`, `:1278-1293` in 8.0). Rejected alternatives: the admin hooks (admin-only, run after the revision is
saved); an override of the public `Post.publish()` model method (never reached: `Revision.content_object` is a
`GenericForeignKey` on `base_content_type`, i.e. the base `Page`, `revisions.py:117-125`, and admin `edit.py`,
the admin API and the v3 router construct `PublishPageRevisionAction` themselves); 8.0's `ActionRegistry` (only
v3 consults it). A validator "called explicitly by form, API and wrapper" is what the wrapper design already
contains: the form and the API call the validator for good error UX, the wrapper is the backstop that makes the
rule true for paths nobody wired.

New module `src/cast/publication.py` (import-light like `podcast_numbering.py`: models only under
`TYPE_CHECKING` or inside functions, so `cast.models` may import it and `tests/import_cycle_test.py` stays green):

```python
@dataclass(frozen=True)
class PublicationViolation:
    field: str  # "podcast_audio" | "non_field_errors"
    code: str  # "required" today; a new rule brings its own code
    message: str  # str(gettext_lazy(...)) at raise time


class PublicationRejected(django.core.exceptions.ValidationError):
    violations: tuple[PublicationViolation, ...]

    def __init__(self, violations):  # MUST build the dict form, see Compatibility
        self.violations = tuple(violations)
        super().__init__({v.field: [ValidationError(v.message, code=v.code)] for v in self.violations})

    def as_error_map(self) -> dict[str, list[dict[str, str]]]: ...  # editor envelope, same shape as today
    def as_form_error(self) -> django.forms.ValidationError: ...  # {field: [message]}


EPISODE_AUDIO_REQUIRED = _("An episode must have an audio file to be published.")


def episode_audio_violation(podcast_audio_id: int | None) -> PublicationViolation | None: ...
def violations_for(page: Post, *, revision: Revision | None = None) -> list[PublicationViolation]: ...
def check_publishable(page: Post, *, revision: Revision | None = None) -> None: ...  # raises PublicationRejected
def install_publication_policy() -> None: ...  # wraps _publish_revision once; connects page_published receiver
```

Rules are pure functions over primitives (`episode_audio_violation(podcast_audio_id)`), so the admin form can
evaluate them against `cleaned_data` before the instance is built, while `violations_for(page)` evaluates them
against `revision.as_object()`, the content about to go live. New rules are added to one tuple in this module.

Data flow at publish time (inside the wrapper, `object` is `revision.as_object()`):

```
caller (admin, API, scheduled, bulk, workflow, v3, code)
  -> Revision.publish -> Page.publish -> PublishPageRevisionAction.execute -> _publish_revision (wrapped)
       not a Post ............................................ original(...)
       Post: transaction.atomic():
         check_publishable(object, revision)  -- raises PublicationRejected
           | rejected and log_action == "wagtail.publish.scheduled": record + clear approval, return
           | rejected otherwise: raise (ValidationError subclass; see Compatibility for what each caller does)
         Episode: assign_episode_number_for_publish(object, revision, previous_revision)
         original(...)  -> ... _after_publish -> page_published -> prepare_published_post_media (unchanged)
```

Rules run at approval time as well as at go-live: scheduling a future `go_live_at` is itself a call into
`_publish_revision`, which sets `approved_go_live_at` and leaves the object a draft - returning early when the page
is already live, otherwise falling through with `object.live = False` (`actions/publish_revision.py:113-128` in
7.0.9, `:119-134` in 8.0). An audio-less revision is therefore rejected when an editor approves it, on every path;
the `wagtail.publish.scheduled` branch above is a backstop for revisions that were never validated (approved before
this change) or that became invalid after approval (a time-dependent rule added later, or an `Audio` row deleted
between approval and go-live). That last case needs no rule of its own: `Revision.as_object()` runs
`Page.with_content_json` -> `from_serializable_data(content)` (`wagtail/models/pages.py:1936` in 7.0.9), whose
`check_fks=True` default makes modelcluster null a dangling `SET_NULL` reference
(`modelcluster/models.py:96-111`; `podcast_audio` is `on_delete=SET_NULL`, `models/pages.py:670-679`), so the
reconstructed episode simply has no audio and the `required` rule already covers it. Today such a scheduled
go-live publishes the episode audio-less and silently; after slice 3 it is rejected and recorded.

Failure surfaces per path:

- Admin form (A): `CustomEpisodeForm.clean` keeps its `action-publish` detection and raises
  `rejected.as_form_error()`; same field, same message as today. It stays because it is the only place that can
  refuse before a draft revision is written.
- Editor API (E): `_publish` calls `check_publishable(revision.as_object())` and maps `PublicationRejected` to
  `EditorValidationError(rejected.as_error_map())`. Envelope, `podcast_audio`, `required` and the message stay
  byte-identical (`tests/api/editor_episodes_test.py:882-917` are the guard). `no_unpublished_draft`,
  `no_revision` and permission handling are untouched.
- Scheduled go-live (S; `user=None`, `log_action="wagtail.publish.scheduled"`): the wrapper does not raise (an
  exception would abort the command's loop for every later due revision; `publish_scheduled.py:117` has no `try`
  around `rp.publish(...)`). It clears `approved_go_live_at`, writes
  a `cast.publish.rejected` page log entry (`register_log_actions` hook, `wagtail/log_actions.py:97` in both
  versions) so the failure shows on the History tab, and logs at ERROR. The page stays a draft.
- Admin API (X): Wagtail catches `DjangoValidationError` from `action.execute()` and answers 400 with
  `e.message_dict` (`admin/api/actions/publish.py:29-31`, both versions).
- v3 (V, 8.0 only): `api/v3/errors.py:118-132` answers 422 `application/problem+json` built from
  `exc.messages`, which drops the field name; the body carries only the message text.
- Bulk publish (B), workflow approval (W): `PublicationRejected` propagates; neither `bulk_actions/publish.py:
  46,67` nor `publish_workflow_state` (`workflows.py:27`) and the workflow/edit views catch `ValidationError`,
  so the admin renders a 500 (question 4). Safer than a silent publish; UX follow-up.
- Code (C): `PublicationRejected` propagates to the caller.

Post-publish effects stay on `page_published`: it is Wagtail's supported "after" seam, and copy-with-keep-live
and alias updates (`Page.update_aliases`, `models/pages.py:1036,1127` in 7.0.9, `:1156,1248` in 8.0) never
enter `PublishRevisionAction` but still fire it, so media preparation keeps covering them.
`install_publication_policy` connects the receiver so `apps.py` has one call and one module owns both halves.

## Compatibility

Inspected: Wagtail 7.0.9 at `.tox/py312-django52-wagtail70/.../wagtail` and 8.0.0 at
`.tox/py312-django60-wagtail80/.../wagtail` (the repo `.venv` holds 7.4.3, not 8.0). `_publish_revision` has the
identical positional signature `(revision, object, user, changed, log_action, previous_revision=None)` in both
(`actions/publish_revision.py:102` and `:108`), so `_validate_publish_revision_api` keeps working as the guard.
8.0 adds an `ActionRegistry` (`actions/registry.py`) fed by a `register_actions` hook; only the v3 routers
consult it (`api/v3/routers/pages.py:419`). `Page.publish`, `publish_scheduled`, bulk publish and workflows
reach `PublishPageRevisionAction` directly, and 8.0's `EditAction`/`CreateAction` call `self.revision.publish()`
(`actions/edit.py:175`, `actions/create.py:169`), which reaches it via `Revision.publish -> Page.publish`; the
registry is not a choke point even on 8.0. `publish_scheduled` and the `page_published`/`published` signals are
unchanged between the versions.

`PublicationRejected` must be built in dict form. `ValidationError.message_dict` reads `self.error_dict` and
raises `AttributeError` for a string- or list-form error (verified with `.venv` python), which would turn the
admin API's 400 into a 500. The dict form gives `message_dict == {"podcast_audio": [message]}`,
`messages == [message]` and `error_dict["podcast_audio"][0].code == "required"`; slice 1 asserts all three.
Status mapping is therefore: admin API 400 with `message_dict`; v3 422 problem+json with `messages`.

Theme repos (`../cast-bootstrap5`, `../cast-vue`) reference none of the four mechanisms. `../homepage` connects
its own `page_published` receiver (`homepage/core/webmention_integration.py:17`), which keeps firing from
`_after_publish`. `../python-podcast` has no reference. `../daybook/src/daybook/cast_client.py` never calls the
publish endpoint (`base_revision_id`/`require_unpublished` on PATCH only); a future publish call should send
`If-Match`.

Must stay byte-identical: the editor `validation_error` envelope for the audio rule, the `no_unpublished_draft`
and `no_revision` 409 bodies, the `revision_conflict` 409 body (reused verbatim by slice 5), `published_revision_id`
in the publish response, the admin form error text, the "does not accept a request body" publish contract
(`docs/reference/api.rst:821-822`; `tests/api/editor_episodes_test.py:886` posts `{}` and must keep working),
and numbering behaviour covered by `tests/podcast_numbering_test.py` (scheduled first publish numbers at go-live).

## Security considerations

- Fail closed: a rejected policy never publishes, on any path, including paths added later.
- The scheduled-path rejection must not loop: clearing `approved_go_live_at` is what stops `publish_scheduled`
  from retrying every minute; the History entry is what tells a human. The log entry must not include content.
- Slice 5 closes the Publication approval binding observation: with `If-Match` the publisher approves a specific
  revision, and the publish runs under `transaction.atomic` with `select_for_update` on the page row (the pattern
  `_get_post(..., for_update=True)` at `views.py:159` already uses), so a concurrent PATCH cannot interleave
  between the check and the publish.
- Permission checks stay where they are (`permissions_for_user(user).can_publish()` in `_publish`,
  `PublishPageRevisionAction.check` for Wagtail callers). The policy adds content rules, never grants rights.
- The wrapper still refuses to install on an unexpected Wagtail signature and logs a warning; slice 2c makes
  that a `cast.E0xx` system check so deploys fail loudly instead of silently dropping the rules.

## Implementation slices

Each slice is independently committable, keeps `just check` green (lint, mypy, 100% coverage) and updates
`docs/releases/0.2.65.rst` where behaviour changes. Sizes are changed lines including tests.
1. **Policy module and adapters.** Add `src/cast/publication.py` with `PublicationViolation`,
   `PublicationRejected` (dict-form `__init__`), `EPISODE_AUDIO_REQUIRED`, `episode_audio_violation`,
   `violations_for`, `check_publishable`. `CustomEpisodeForm.clean` and `_reject_unpublishable_episode`
   delegate to it. Tests: `tests/publication_test.py` (rule, both error adapters, `message_dict`/`messages`/
   `error_dict[...].code`, `Post` returns no violations); existing form and API tests unchanged. Docs: none.
   Release note: internal. ~150 lines.
2a. **Relocate the installer.** Move `_validate_publish_revision_api`, `_publish_revision_and_object` and the
   wrapper into `publication.install_publication_policy()`; `podcast_numbering` keeps only the numbering
   service; `install_episode_numbering_publish_hook` is removed and `apps.py:59` calls the new name. Pure
   relocation, no behaviour change. Tests: `tests/podcast_numbering_test.py:112-137,584-604` move to
   `tests/publication_test.py` with the new import path and warning text. Release note: none. ~180 lines.
2b. **Enforce at the choke point.** The wrapper calls `check_publishable(object, revision)` for every `Post`
   before numbering. Tests: `revision.publish()` and `publish_workflow_state()` on an audio-less episode raise
   `PublicationRejected` and leave the page draft; a `Post` and a non-cast page pass through; an episode with
   audio still numbers. Admin-view tests for bulk and workflow are deferred to the question-4 follow-up, since
   the 500 they would assert is the accepted interim behaviour. Release note: "publishes through Wagtail (bulk,
   workflow, scheduled approval, admin API, code) now enforce the episode audio rule". ~120 lines.
2c. **System check for the guard.** Add `cast.E007` in `checks.py`: fails when `PublishRevisionAction.
   _publish_revision` is not the installed wrapper after app loading (decide question 3 here). Tests in
   `tests/checks_test.py` per existing pattern. Docs: the checks/settings reference. Release note: deploy-time
   error replaces the silent warning. ~120 lines.
3. **Scheduled-publish rejection.** In the wrapper, on `log_action == "wagtail.publish.scheduled"`: clear
   `approved_go_live_at`, add `cast.publish.rejected` via a `register_log_actions` hook in `wagtail_hooks.py`,
   log ERROR, return. No new rule and no new violation code (Q5). Tests: (i) an approved revision whose `Audio`
   row is deleted after approval - `as_object()` nulls `podcast_audio`, so the `required` rule fires:
   `call_command("publish_scheduled")` leaves the page draft, records the log entry and still publishes the next
   due revision (today it publishes the episode audio-less); (ii) a revision with `approved_go_live_at` set by
   `update()` and audio removed from `revision.content`, standing in for legacy or time-dependent state. Docs:
   `docs/content/podcasts-and-episodes.rst` (what happens to a scheduled episode that lost its audio). ~150 lines.
4. **One boundary, one guard.** `install_publication_policy` also connects `prepare_published_post_media`;
   module docstring explains pre-publish rules vs post-publish effects; AST test asserting no module outside
   `cast.publication` imports `wagtail.actions.publish_revision` or calls `page_published.connect`. Docs: short
   "Publication" section in `docs/reference/models.rst` or a new `docs/reference/publication.rst`. ~80 lines.
5. **Revision precondition on publish (Publication approval binding).** `POST .../publish/` accepts an optional
   `If-Match: "<id>"` header only, parsed by the existing `_if_match_revision_id` (`views.py:65-80`); no request
   body is introduced, so the documented contract holds. `_publish` runs in `transaction.atomic`, locks the page
   row, compares against `latest_revision_id`, raises the existing `EditorRevisionConflict` on mismatch, and
   publishes exactly the checked revision. Tests: match publishes, stale token returns the `revision_conflict`
   body, malformed header returns the existing `If-Match` validation error, omitted header behaves as today.
   Docs: rewrite `docs/reference/api.rst:816-824` and the episode cross-reference. Release note. Daybook: no
   change (see Compatibility). ~150 lines.
6. **Bookkeeping.** Mark the theme-2 item in `BACKLOG.md:23-27` done, cross-link this note from
   `backlog/2026-09-15-architecture-review.md`, point `backlog/2026-09-07-security-review.md:140-146` at slice 5.

Prerequisites: slices 1-4 are the "publication policy service" the Wagtail v3 evaluation
(`backlog/2026-09-08-wagtail-v3-editor-api.md:132-135`) names as its precondition; slice 5 is the security item
and an input to that evaluation's option 2/3 comparison. Slices 1-2b alone already make the v3
`actions/publish/` route and 8.0's `EditAction(publish=True)` enforce the audio rule.

## Risks and open questions

1. **Scheduled rejection: clear approval or leave it?** (a) clear `approved_go_live_at` and log (no retry
   storm, visible in History); (b) leave it and log each tick (noisy, but a later fix publishes automatically);
   (c) raise and let the command abort (blocks every later due page in the same run). Recommend (a).
2. **Required or optional `If-Match` on publish?** Optional is backwards compatible and closes the observation
   for clients that opt in; required breaks a documented contract. Recommend optional now; "required" is a
   candidate for the next editor API version alongside the v3 decision.
3. **Silent non-installation.** Today an unexpected `_publish_revision` signature only logs a warning and the
   rules silently stop applying. Slice 2c adds the system check; keep the warning fallback (the check runs at
   deploy, the warning at import in shell and test contexts)? Recommend yes, with the check as an `Error`.
4. **Bulk publish and workflow approval UX.** After slice 2b the admin bulk "Publish" and a moderator's
   workflow approval of an audio-less episode raise instead of publishing; Wagtail renders both as a 500. A
   `before_bulk_action` hook (`admin/views/bulk_action/base_bulk_action.py:84`, both versions) could filter the
   bulk case; workflow approval has no equivalent hook and needs a custom task or a `before_edit_page` check.
   Recommend accepting the exception now and tracking both in one follow-up that owns the deferred admin tests.
5. **Audio existence as a rule: rejected.** An earlier draft added a `does_not_exist` rule for a deleted `Audio`
   row. `Revision.as_object()` already nulls that reference (`check_fks=True` plus `on_delete=SET_NULL`), so the
   `required` rule covers it; a distinct code would have to read `revision.content` rather than the reconstructed
   object, and would be a new client-visible code for a state the existing code already describes. Revisit only if
   an operator needs to tell "never had audio" from "audio was deleted" in the History entry.
6. **Copy-with-keep-live and aliases** bypass `PublishRevisionAction` entirely, so a copied live episode keeps
   its `episode_number` and neither copies nor alias updates are re-validated. Out of scope; note as a known gap.

## Non-goals

- No change to how numbering decides (`assign_episode_number_for_publish` and its tests stay as they are).
- No `before_publish_page`/`before_publish` hooks; no `register_actions` subclass for 8.0 (the wrapper already
  covers the v3 route; a registered action is a v3-evaluation topic).
- No new settings; no change to permission checks or token scopes; no change to `require_unpublished` PATCH
  semantics; no request body on the publish endpoint; no daybook changes.
- No admin UX for bulk or workflow rejections (question 4); no fix for copy-with-keep-live or alias updates.

## Done when

- `grep -rn "from wagtail.actions.publish_revision import\|page_published.connect" src/cast` hits only
  `src/cast/publication.py`.
- An audio-less episode cannot go live via admin form, editor API, `revision.publish()`,
  `publish_workflow_state()` or `publish_scheduled`; each failure surface is tested and matches the list above.
  Bulk publish and admin workflow approval are covered transitively; their admin views belong to the question-4
  follow-up.
- Editor API error bodies for publish are unchanged except for the new optional `If-Match` precondition, whose
  stale case returns the existing `revision_conflict` body; no new error code is introduced.
- `just check` and the full tox matrix (7.0.9 through 8.0) are green; docs and `docs/releases/0.2.65.rst` are
  updated per slice; `BACKLOG.md` theme 2 and the security review's Publication approval binding bullet are
  closed with links to this note.

## Review log

- warning, accepted: slice 3 scenario unreachable after slice 2. Added the "rules run at approval time"
  paragraph, rewrote slice 3 tests (dangling audio, synthetic legacy state), existence rule joins slice 3 (Q5).
- warning, accepted: `PublicationRejected` must be dict-form (verified `ValidationError('x').message_dict`
  raises). Contract shows `__init__`; slice 1 asserts the three accessors.
- warning, accepted: v3 maps to 422 problem+json from `messages`, not 400. Fixed Compatibility and the
  failure-surface list, including the dropped field name.
- warning, accepted: workflow approval also 500s and was untested. W listed with B in the failure surfaces, Q4
  extended, model-level `publish_workflow_state()` test assigned to slice 2b, admin-view tests moved to follow-up.
- warning, accepted: slice 2 overran. Split into 2a (relocation), 2b (enforcement), 2c (system check).
- suggestion, accepted: acceptance grep vs. guard strings. Guard moves into `cast.publication` in 2a and the
  grep now targets the import and `page_published.connect`.
- suggestion, accepted: `update_aliases` also fires `page_published` (reworded; aliases in table and Q6);
  `EditAction` wording fixed; `Post.publish()` override recorded as rejected with the `GenericForeignKey` reason.
- suggestion, accepted: no `SEC-obs-3` label exists; all references now name the security review bullet.
- suggestion, accepted: publish endpoint stays body-less; slice 5 is `If-Match` only via `_if_match_revision_id`.
- critical, accepted (round 1): the dangling-`Audio` scenario was wrong. `Revision.as_object()` nulls a `SET_NULL`
  reference whose row is gone (`modelcluster/models.py:96-111` via `wagtail/models/pages.py:1936`), so there is no
  `IntegrityError` today and no need for a `does_not_exist` rule. The approval-time paragraph, the S failure
  surface, slice 3 (now ~150 lines), Q1(c), Q5 and the acceptance list were rewritten.
- suggestion, self-found: `_publish_revision` returns early only for an already-live page; a first publication with
  a future `go_live_at` falls through with `object.live = False`. Wording corrected.
- suggestion, accepted (round 2): the backstop wording read as if a deleted `Audio` row were out of scope. It now
  reads "never validated, or became invalid after approval", with the deleted-audio case named there.
