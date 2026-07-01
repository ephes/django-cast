# Anonymous Comment Self-Editing and Deletion

Date: 2026-06-21

Status: Implemented and tested (2026-06-22) — backend, browser frontend (templates + AJAX JS), and user docs/release
notes all landed. See Implementation Notes.

## Summary

django-cast accepts comments from anonymous visitors. Once a comment is posted there is currently no way for the author
to fix a typo or retract it; only staff with `django_comments` moderation permissions can act on it. This PRD proposes
letting an author edit or delete *their own* comment for as long as the browser session that created it remains valid,
without introducing authentication.

The ownership proof is the server-side Django session, never anything the client supplies. On a successful post the new
comment id is recorded in `request.session`. Edit and delete endpoints authorize purely by checking that the current
session created the target comment — the same path works for anonymous and authenticated authors, so no special
authenticated-user handling is needed. Editing re-runs the existing spam/moderation pipeline (via the same
`comment_will_be_posted` signal as a new post), so an edit cannot slip abusive content past moderation
("bait-and-switch"). Both edit and delete are permitted only while a comment is still publicly visible **and has not yet
been answered** (has no reply); once someone has replied, the comment is frozen. Deletion is a soft delete that stays
visible and restorable to staff in Django admin, and author-deleted comments are excluded from the spam-training corpus
so deleting legitimate content cannot poison the filter.

This is deliberately a small, optional, security-bounded feature. It does not add user accounts, does not expose any
cross-user capability, and degrades to today's behavior when disabled.

## Resolved Decisions

These were settled during shaping and drive the rest of the document:

- **Ownership proof:** server-side Django session only (a server-side session backend is required; `signed_cookies` is
  rejected by a system check). No signed token, no email link.
- **Operations:** both edit and delete.
- **Edit window:** the session lifetime (`SESSION_COOKIE_AGE`, default two weeks). No separate hard time cap.
- **Freeze once answered:** a comment that has been replied to can no longer be edited or deleted. Combined with the
  still-public rule, edit/delete only ever touch an owned, still-public, reply-less comment.
- **Edit re-moderation:** every edit re-enters the spam/moderation pipeline via the `comment_will_be_posted` signal.
- **Delete:** soft delete (kept in the database, restorable by staff via Django admin), excluded from spam training.
- **Storage:** one small dependency-free model, `CommentAuthorMeta` (Option B below).
- **Edited indicator:** a persistent **boolean** only (no timestamp shown to readers).
- **Authenticated users:** no change — the session path covers them; there is no separate `user`-FK branch.
- **Admin tooling:** register `CommentAuthorMeta` with a standard `ModelAdmin` so staff can see/clear `deleted_at`; no
  bespoke UI. Operators restore a comment by un-removing it in the existing comment admin.
- **Rate limiting:** built in on the cache; no new third-party dependency.

## Motivation

- Anonymous commenters routinely want to correct a typo, fix a broken link, or withdraw a comment they regret. Today
  their only recourse is to ask a site operator to edit the database or use Wagtail/Django admin.
- Site operators carry that burden manually, which does not scale and exposes them to "please delete my comment"
  requests with no self-service path.
- django-cast already has all the moderation machinery (Naive Bayes spam filter, `comment_will_be_posted` signal) needed
  to make edits safe; the only missing piece is a way to bind an author to the comment they created.
- The feature must not weaken the current security posture. The whole point of this PRD is to show the safe path is the
  only path: ownership lives server-side, edits are re-moderated, frozen-once-answered protects existing replies, deletes
  are staff-restorable, and the capability evaporates with the session.

## Goals

- Allow an author to edit the text of a comment they created from the same browser session.
- Allow an author to delete a comment they created from the same browser session.
- Authorize every edit/delete strictly against server-side session state, so no client can act on a comment it did not
  create, with the identical path for anonymous and authenticated authors.
- Re-run the spam/moderation pipeline on every edit, so editing cannot bypass moderation.
- Freeze edit and delete once a comment has been answered, so a thread is never mutated under an existing reply.
- Keep the feature optional and configurable, and keep current behavior unchanged when it is disabled.
- Reuse the existing AJAX, CSRF, honeypot, and template-rendering patterns already used by `post_comment_ajax`.

## Non-Goals

- Adding authentication, registration, or login for commenters.
- Any special-casing for authenticated users beyond the shared session path.
- Cross-device or cross-browser editing (clearing cookies or switching browsers ends the ability — by design).
- Letting a commenter edit or delete anyone else's comment, or any comment that has been answered.
- An author-facing undo/restore UI (staff can restore a soft-deleted comment from Django admin; that is sufficient).
- Replacing staff moderation tools, or building any bespoke admin UI beyond a standard `ModelAdmin` registration for
  `CommentAuthorMeta`.
- Email-based ownership proof (the default config excludes the `email` field, so this is not viable for typical
  deployments — see Alternatives Considered).
- A full comment edit-history viewer for readers (the persistent marker is a single boolean).

## Actors

- Author (anonymous or authenticated): posts a comment, then later edits or deletes it from the same browser session.
- Site operator: enables/configures the feature, manages and restores comments through Django admin, and retains full
  staff moderation powers regardless of this feature.
- django-cast comment app: records ownership on post, authorizes edit/delete, re-moderates edits, and renders
  ownership-aware affordances.

## Current Architecture (verified)

- Comments use `django_comments` (django-contrib-comments), optionally `threadedcomments`. `CastComment`
  (`src/cast/comments/models.py`) is a `proxy = True`, `managed = False` model over the active base comment table.
- Posting goes through one custom AJAX view, `post_comment_ajax` (`src/cast/comments/views.py`): `@csrf_protect`,
  `@require_POST`, requires the `X-Requested-With: XMLHttpRequest` header, builds the form, runs `security_errors()`,
  fires `comment_will_be_posted` (which the moderation receiver uses to run the spam filter) and `comment_was_posted`.
- Anonymous comments store `user_name`/`user_email`/`user_url` and `ip_address`; the `user` FK is null. The default
  example config sets `CAST_COMMENTS_EXCLUDE_FIELDS = ("email", "url", "title")`, so email is frequently not collected.
- Moderation (`src/cast/moderation.py` + `src/cast/models/moderation.py`): the Naive Bayes `SpamFilter` predicts a label
  on post; a "spam" prediction sets `is_removed = True, is_public = False`. Training labels are derived from the current
  `is_public`/`is_removed` state of all comments via `SpamFilter.get_training_data_comments`.
- Comments are rendered **live** by the `{% render_comment_list %}` / `{% render_comment_form %}` template tags in the
  post templates (e.g. `src/cast/templates/cast/bootstrap4/post.html`). They are **not** part of the repository
  serialization cache (`src/cast/models/repository/serialization.py` only serializes the `comments_enabled` flag). This
  keeps the cache-invalidation surface for this feature small.
- `render_comment_list` only renders comments with `is_public = True` and `is_removed = False`, so a soft-deleted comment
  disappears from the list without a hard delete.
- With `threadedcomments`, a reply carries a `parent` FK to the comment it answers; flat `django_comments` has no
  per-comment reply structure (all comments attach to the post, not to each other).

## Ownership Model (security core)

Ownership is proven by **server-side session membership only**, uniformly for anonymous and authenticated authors:

1. On a successful post in `post_comment_ajax`, after `comment.save()`, append the comment's PK **as a string** to a
   session-held list: `request.session.setdefault("cast_owned_comments", [])`, append `str(comment.pk)`, and reassign to
   mark the session dirty. Strings are used because Django's default JSON session serializer cannot serialize arbitrary
   PK objects (e.g. UUIDs), and because POSTed ids arrive as strings anyway. Cap the list to the N most recent ids
   (default 200) to bound session size; drop the oldest beyond the cap. Capped ids simply lose their edit affordance,
   which is acceptable. This runs only when the feature is enabled and the runtime backend guard passes (see
   Configuration).
2. Edit and delete endpoints authorize with `owns = str(posted_id) in request.session.get("cast_owned_comments", [])`,
   comparing the normalized string form on both sides. There is no `user`-FK fallback: a logged-in author's own comment id
   is in their session list just the same, so the single check covers everyone. A client-supplied comment id is **never**
   trusted on its own.
3. Like all session-based authentication, the session cookie is a **bearer credential**: whoever holds it acts as that
   session. This feature adds no new bearer token beyond the session cookie the site already relies on, and the standard
   protections apply (`HttpOnly`, `Secure`, HTTPS-only transport, sane `SESSION_COOKIE_*`). Two properties depend on the
   session backend:
   - **Server-side backends** (`db` — the default — `cache`, `cache_db`, `file`): the cookie carries only an opaque
     session id; the owned-ids list lives on the server, is never exposed to or modifiable by the client, and the session
     is **server-revocable** (deleting the session row immediately voids the capability). A client cannot read the list
     or add an id it did not create.
   - **`signed_cookies` backend**: the owned-ids list travels *inside* the cookie. `SECRET_KEY` signing stops the client
     from forging new ids, but the list is client-readable, **not server-revocable**, and portable as data — strictly
     weaker. The feature therefore **disallows the `signed_cookies` backend outright**: a system check (see Configuration)
     refuses to start with the feature enabled on that backend, with no opt-out. The feature is optional, so a deployment
     that wants it runs a server-side backend.
   This is *not* a claim that the session cookie cannot be copied: cookie theft (XSS, physical access, non-HTTPS
   transport) transfers the capability exactly as it would for any logged-in session. That residual risk is the standard
   session-hijacking caveat — mitigated by the protections above and by server-side revocability, not eliminated by this
   feature.
4. The capability is intentionally ephemeral. Clearing cookies, switching browser/device, logging out (Django flushes the
   session on logout), or session expiry (`SESSION_COOKIE_AGE`, default two weeks) ends it. The UI must state this so
   authors are not surprised.

### Eligibility predicate (shared by edit and delete)

A comment is actionable by its owner only when **all** hold:

- it is owned by the current session (per above);
- it is currently public: `is_public = True and is_removed = False`;
- it has **not been answered**: no other comment has it as a direct `parent`, in **any** moderation state. Replies are
  counted regardless of their current visibility — a reply that is pending or spam-flagged now could be approved later,
  and the parent must not have been edited or deleted out from under it in the meantime. (In flat mode there are no
  per-comment replies, so this clause is always satisfied; it is meaningful only with `threadedcomments`.)

Any other state returns a generic, identical failure (see Operations) so the endpoints never reveal whether a comment
exists. Two consequences fall out of this predicate and are intentional:

- **Loss of public visibility is terminal.** A comment hidden by the spam filter, removed by staff, unpublished/pending,
  or already author-deleted cannot be edited or deleted by its author. This prevents an author from re-moderating a
  hidden comment back into visibility, and prevents erasing a spam/staff-removed comment to destroy moderation evidence.
- **Being answered is terminal.** Once any reply exists (even a hidden/pending one), the comment is frozen, so edits and
  deletes never mutate a thread out from under an existing or soon-to-be-approved reply. This also means delete only ever
  applies to a reply-less comment, so there is no parent-with-children deletion case to handle.

### New side effect to disclose

Today an anonymous commenter receives no session and no cookie, because nothing writes to `request.session`. This
feature starts writing to the session on the first comment, which means:

- A session row is created and a session cookie is set for previously cookieless anonymous commenters.
- The session table grows roughly in proportion to distinct commenting visitors; operators should keep
  `django-admin clearsessions` (or a cached session backend) in mind.
- The cookie is functional (it stores no tracking identifier beyond Django's session key), but its introduction should
  be documented for operators with cookie-disclosure obligations.

This trade-off must be called out in docs and is part of why the feature is opt-in (see Configuration).

## Storage Decision

The feature adds exactly **one small, dependency-free model**, `CommentAuthorMeta`, which is the minimum that supports
the persistent "edited" boolean, staff-restorable soft delete, and deletion-aware spam training. Ownership itself needs
no storage — it lives in the session.

```python
class CommentAuthorMeta(models.Model):
    # NOT a ForeignKey, and stored as text rather than an integer. The concrete
    # comment model varies by deployment (django_comments / threadedcomments /
    # custom COMMENTS_APP), so a migration must not freeze a FK to one table, and
    # the PK type is not guaranteed to be a 32-bit int — it may be a BigAutoField
    # or a UUID. Mirror how django_comments itself references variable-PK objects
    # (object_pk as text). 255 chars covers integers, big integers, and UUIDs.
    comment_pk = models.CharField(max_length=255, unique=True, db_index=True)
    edited = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
```

- The row is created lazily (`get_or_create(comment_pk=str(comment.pk))`) on the first edit or delete of a comment;
  comments that are never self-edited or self-deleted carry no row.
- `edited = True` powers the persistent boolean "edited" marker shown to readers (no timestamp is exposed).
- `deleted_at` records an author deletion. The training query filters on it, and it lets staff recognize and restore
  author-deleted comments in Django admin.
- `comment_pk` stores the comment's primary key **as text**, not a `ForeignKey` and not a fixed-width integer, so the
  model is independent both of which comment backend a deployment uses (no migration freezes a concrete FK target) and of
  that backend's PK type — integer, big integer, or UUID. The 255-char field covers all of those; a custom backend with
  string PKs longer than that is out of scope (django_comments and threadedcomments both use integer PKs). Because there is no DB-level cascade, a `post_delete`
  receiver on the active comment model (`django_comments.get_model()`) removes the matching `CommentAuthorMeta` row when
  staff hard-delete a comment in admin; all lookups and the training query tolerate a missing row. A companion receiver on
  `comment_was_flagged` (moderator approval), with a `post_save` fallback, clears `deleted_at` when a comment is restored,
  maintaining the `deleted_at` invariant. (A `GenericForeignKey` would also work but is heavier than needed here.)
- `CommentAuthorMeta` is registered with a simple `ModelAdmin` (e.g. `list_display = ("comment_pk", "edited",
  "deleted_at")`) so staff can identify author-deleted comments. Restoring a soft-deleted comment is done by un-removing
  it in the standard comment admin; the `comment_was_flagged`/`post_save` receiver then clears `deleted_at`
  **automatically**. This clearing is required, not optional: the training query excludes any row with a non-null
  `deleted_at`, so a restored comment must have it cleared to re-enter training as ham (staff do not edit the metadata row
  by hand).
- This is one migration and no third-party dependency. Deferred extensions (not in this slice) could add `session_key`
  for a secondary cross-check, an `edit_count` cap, or a `last_edited` timestamp; none are required for the resolved
  design.

## Operations

### Edit

`POST /comments/edit/ajax/` — `@csrf_protect`, `@require_POST`, AJAX-only (mirrors `post_comment_ajax`).

Request fields: `comment_id`, the new `comment` text, and anti-abuse fields (`honeypot`, plus `security_hash`/`timestamp`
where applicable) — **and nothing else**. Identity fields (`user_name`, `user_email`, `user_url`) are not accepted on
edit. Flow:

1. In a transaction, resolve and **lock** the comment row (`select_for_update()`) and apply the **eligibility predicate**
   (owned, currently public, not answered), re-evaluating it inside the lock immediately before any write (see
   Concurrency). On any failure return a generic `403`/`404` that does not reveal whether the comment exists (avoid an
   ownership oracle).
2. Validate **only** the editable text and anti-abuse fields. The author's identity fields (`user_name`, `user_email`,
   `user_url`) and all other comment metadata are **immutable** on edit: they are preserved from the stored comment and
   never read from the request, so an edit cannot change the displayed author. Reuse the comment-field validation (max
   length, required, honeypot); if the `CommentForm` is used for this, seed it with the stored comment's existing field
   values so its required/security checks pass while only `comment` is taken from the request.
3. Replace `comment.comment` with the cleaned text and re-enter moderation **through the same signal path as a new
   post**, not by calling `default_moderator` directly. Re-dispatch `comment_will_be_posted` (honoring a `False` return
   from any receiver as a rejection, exactly as `post_comment_ajax` does) so the edited comment passes through the cast
   moderation receiver — and through any deployment that overrides moderation via the signal rather than the default
   moderator. The receiver re-classifies the updated text: a "spam" outcome sets `is_removed = True, is_public = False`
   (which, per the eligibility predicate, freezes the comment against further author edits); a "ham" outcome leaves it
   public. Do **not** fire `comment_was_posted` on edit — existing receivers treat it as a new-comment event and would
   resend notifications or run other create-only side effects. If a deployment needs to react to edits, emit a dedicated
   `comment_was_edited` signal instead.
4. Save, set `CommentAuthorMeta.edited = True` (via `get_or_create`), and return the re-rendered comment HTML (reusing
   `get_comment_context_data` + `get_comment_template_name`) plus a status payload: whether the edit is now publicly
   visible, and the `edited` flag.

An edit can therefore flip a previously public comment to hidden; that is the correct, intended behavior and must be
surfaced clearly in the response and UI. An author whose edit trips the spam filter cannot then edit it back, because the
comment is no longer public (a future slice with richer per-comment state could safely allow revising one's own
spam-flagged — but not staff-actioned — comment).

### Delete

`POST /comments/delete/ajax/` — same decorators and eligibility predicate.

- Performs a **soft delete**: set both `is_removed = True` and `is_public = False` and save, so the comment is hidden
  robustly across every `django_comments` query and template path, not only the default list filter. Record the deletion
  by setting `CommentAuthorMeta.deleted_at` (via `get_or_create`).
- Soft delete (rather than a hard `DELETE`) keeps the row so staff can recognize and restore it in Django admin, and so
  the eligibility predicate already guarantees the comment has no replies — there is no thread to corrupt either way.
- **Spam-training interaction:** `SpamFilter.get_training_data_comments` labels a comment `spam` whenever it is not
  (`is_public and not is_removed`). A soft delete would otherwise feed an author's *legitimate* comment to the filter as a
  spam example. `deleted_at` carries the invariant *"the comment is currently author-deleted"*: it is set together with
  `is_removed = True`/`is_public = False` on delete, and **cleared when the comment is un-removed (restored)**. The
  training query excludes any comment whose id is in `CommentAuthorMeta` with a non-null `deleted_at` (author-deleted ⇒
  neither ham nor spam). A moderator-removed comment carries no such record and remains a spam example. Because restore
  clears `deleted_at`, a comment that is restored and later removed again as spam has no marker and is correctly labeled
  spam.
- **Restore:** staff restore a soft-deleted comment with the normal comment admin. Restoring **clears `deleted_at`** to
  keep the invariant. The django_comments approve action (`perform_approve`) un-removes each comment with a *per-object*
  `comment.save()` and emits the `comment_was_flagged` signal with the `MODERATOR_APPROVAL` flag (verified against the
  bundled package — it does not use `queryset.update()`); the comment change-form save path is likewise per-object. A
  receiver on `comment_was_flagged` (approval), with a `post_save` fallback, nulls `deleted_at`, so staff never touch the
  metadata row. The only path that bypasses this is a raw `queryset.update()`, which bypasses all Django signals — a
  general caveat, not specific to the admin restore flow.
- After delete the comment disappears from `render_comment_list`. Optionally drop its id from the session list; this is
  cosmetic, not a security measure.

### Concurrency

The eligibility check and the mutation must be atomic, **and reply-posting must coordinate with them**, or a concurrent
request could slip past the "never mutate once answered/deleted/non-public" guarantee. The **parent comment row is the
shared coordination point**:

- Edit/delete run inside a transaction that locks the target comment row with `select_for_update()` and **re-evaluates
  the predicate inside the lock** (owned, `is_public = True and is_removed = False`, no reply) immediately before writing.
  Two edit/delete requests on the same comment serialize on the lock; the second observes the first's committed result
  (e.g. already removed) and is rejected — an edit cannot resurrect a concurrently deleted comment, and a comment cannot
  be both edited and deleted.
- **Reply posting coordinates on the same lock** (only when the feature is enabled and the post carries a `parent`):
  before inserting the reply, `post_comment_ajax` `select_for_update()`s the parent row and re-checks the parent is still
  a valid target (public, not removed, not author-deleted), rejecting the reply otherwise. The invariant being protected
  is *"a comment is never edited or deleted **after** a reply to it exists"* (not "a reply is never created after an
  edit"). Because both paths take the parent-row lock and re-check after acquiring it:
  - if the reply commits first, the later edit *and* delete re-read children, see it, and are rejected — the parent is
    never edited or deleted once a reply exists;
  - if a delete commits first, the later reply re-reads the parent, sees it removed, and is rejected — no child is created
    under a deleted parent;
  - if an edit commits first, the reply proceeds against the now-edited (still public) parent — which is correct: the
    parent was not edited *after* a reply existed, and editing changes only the author's own text, not the thread
    structure, so there is nothing to reject.
- The author-delete writes (`is_removed`, `is_public`, `deleted_at`) all happen in that same transaction.

This coordination applies only in threaded mode (flat comments have no parent); when the feature is disabled the reply
path is unchanged.

## Threat Model and Mitigations

| Threat | Mitigation |
| --- | --- |
| Forge ownership of another visitor's comment | Authorize only via server-side session membership; never trust a client-supplied id alone. |
| Bait-and-switch: edit an approved comment into spam/abuse | Every edit re-runs the spam/moderation pipeline via `comment_will_be_posted`; a persistent "edited" boolean adds reader transparency. |
| Mutating a thread under an existing reply | A comment is frozen for edit and delete once it has any direct reply, in any moderation state (so a pending/spam reply approved later cannot end up under an already-edited/deleted parent). |
| Race: reply/edit/delete interleaving past the eligibility check (TOCTOU) | Predicate re-evaluated inside a `select_for_update` transaction immediately before the write; serializes same-comment mutations and prevents resurrecting a concurrently deleted comment. |
| Author identity tampering via edit | Edit accepts only the comment text + anti-abuse fields; `user_name`/`user_email`/`user_url` are immutable, preserved from the stored comment, never read from the request. |
| CSRF on edit/delete | Reuse `@csrf_protect`, `@require_POST`, and the `X-Requested-With` AJAX check from `post_comment_ajax`. |
| Ownership oracle (probe which comment ids exist) | Return generic, identical responses for every ineligible/failed case. |
| Edit/delete churn flooding the re-moderation/retrain path | Built-in cache-based rate limiting per session/IP. |
| Author re-moderates a hidden/pending comment into visibility | Edits permitted only while `is_public = True and is_removed = False`. |
| Author erases a spam/staff-removed comment to destroy evidence | Delete permitted only while the comment is still public; removed comments cannot be deleted, and delete is soft (staff-restorable) anyway. |
| Spam-training poisoning via author deletion (legit content labeled spam) | `deleted_at` marks author deletions; the training query excludes them, so only moderator removals count as spam examples. |
| Edit bypassing a deployment's custom moderation receiver | Edits re-dispatch the `comment_will_be_posted` signal rather than calling `default_moderator` directly. |
| Owned-ids list exposed or portable as client-side data | Require a server-side session backend; under `db`/`cache`/`file` the list stays server-side and the cookie holds only an opaque session id. |
| Session cookie theft / hijacking (bearer credential) | Standard caveat for all session auth, not new to this feature; mitigated by `HttpOnly` + `Secure` cookies, HTTPS, and server-side revocability — acknowledged, not claimed to be prevented. |
| Session fixation | Rely on Django's session framework defaults; do not weaken `SESSION_*` settings; the cookie stays `HttpOnly`. |
| Shared/public-computer session inheritance | Capability bounded by session lifetime and by logout flushing the session; documented as a residual risk. |

Conclusion: there is no fundamental security blocker. The residual risks (shared computers, session-table growth, a new
functional cookie) are bounded and addressed through configuration and documentation.

## Privacy Considerations

- Introducing a session cookie for previously cookieless anonymous commenters is the most notable privacy change;
  document it for operators.
- No new personal data is collected beyond what posting already stores. The session stores only comment ids the visitor
  themselves created; `CommentAuthorMeta` stores no personal data (a boolean, a timestamp, and the comment link).
- Soft delete retains comment content in the database (as today's moderation already does). If an operator needs true
  erasure for a deletion request, that remains a staff/admin action; document this distinction so author "delete" is not
  mistaken for GDPR erasure.

## UX and Templates

- `comments/comment.html` (and the threaded/flat list templates) gain ownership-aware affordances: render "edit" and
  "delete" controls only for a comment the current request owns **and** that is still eligible (public and unanswered).
  Eligibility for rendering is computed server-side from the session list plus the comment state, exposed to the template
  context (e.g. an `editable_comment_ids` set or a per-comment flag), never inferred client-side.
- Edit uses an inline AJAX form that reuses the comment form styling/helper.
- After an edit that becomes non-public, show an explicit message ("Your edit is awaiting moderation") rather than
  silently hiding the comment.
- Show the ephemerality note near the controls ("You can edit or delete this comment from this browser until someone
  replies or your session expires").
- Render the persistent "edited" boolean as a small marker (e.g. "(edited)") on edited comments. Because there is no
  reverse relation, the view supplies the edited state to the template the same way it supplies editable ids — e.g. an
  `edited_comment_ids` set built from one `CommentAuthorMeta` query for the rendered page (avoid per-comment queries).
- Soft-deleted comments simply vanish from the list (they are never the parent of any reply, by the freeze rule).

## Caching

- The comment list renders live and is not in the repository serialization cache, so edits/deletes are reflected on the
  next page load without explicit cache invalidation there.
- Verify no full-page/fragment cache wraps the rendered comment list in shipped templates. If a deployment adds page
  caching over comments, document that edits/deletes are subject to that cache TTL.

## Configuration

- A new setting, `CAST_COMMENTS_ALLOW_AUTHOR_EDITS` (default `False`), gates the whole feature. When `False`, behavior is
  exactly as today and no session writes occur on post.
- The `signed_cookies` session backend is rejected as a **hard requirement with no opt-out**, enforced in layers because
  a system check alone does not run in every production entrypoint (a raw WSGI/ASGI server may never invoke
  `manage.py check`):
  - A Django system check (`src/cast/checks.py`) errors when the feature is enabled with
    `SESSION_ENGINE = django.contrib.sessions.backends.signed_cookies` — developer-time feedback.
  - A shared `author_edits_enabled()` helper — used by the on-post session write and by both endpoints — returns `False`
    when the backend is `signed_cookies`, so an insecure configuration **silently disables** the feature at runtime
    rather than operating insecurely.
  - `AppConfig.ready()` may additionally raise `ImproperlyConfigured` for fail-fast startup where checks are run.
  The security model depends on a server-side backend (revocability and a non-client-exposed owned-ids list); the feature
  is optional, so deployments that want it run a server-side backend.
- Tunables: the owned-id list cap (default 200). Rate-limit thresholds for the cache-based limiter.
- Follow the existing `appsettings.py` `__getattr__` pattern and the `CAST_COMMENTS_*` naming, honoring legacy
  `FLUENT_COMMENTS_*` fallbacks where that pattern already exists.

## Spam Filter Interaction

- Edits flow through the same `comment_will_be_posted` signal path as a new post, so re-classification is consistent with
  first-post behavior and respects any deployment-specific moderation receiver.
- `SpamFilter.get_training_data_comments` reads current comment state, so retraining naturally reflects edited content and
  re-moderated labels. The one required change is to **exclude any comment marked author-deleted** (a `CommentAuthorMeta`
  row with a non-null `deleted_at`), so author deletion of legitimate content cannot mislabel it as spam. To avoid a
  cross-type SQL comparison between a typed comment PK and the text `comment_pk` column, do the match in Python: build a
  set of `comment_pk` strings whose `deleted_at` is non-null, and exclude any comment whose `str(pk)` is in that set. The
  delete path sets `deleted_at` and restore clears it (see Delete), so a restored comment re-enters as ham and a
  restored-then-respammed comment is correctly labeled spam; moderator-removed comments carry no record and remain spam
  examples.

## Alternatives Considered

- **Signed HMAC token returned to the browser**: survives session loss but is a bearer credential — anyone who obtains it
  can edit the comment, and revocation is hard. Rejected in favor of revocable server-side session state that keeps the
  owned-ids list off the client and adds no token beyond the existing session cookie.
- **Email magic-link**: strongest ownership proof but requires a collected, deliverable email; the default config
  excludes `email`, and it adds friction. Rejected for the default path; could be an opt-in enhancement for deployments
  that collect verified email.
- **Hard delete (no model)**: simplest, but loses the persistent "edited" marker, removes staff recoverability, and
  destroys the row. Rejected in favor of the one small `CommentAuthorMeta` model, which keeps deletes staff-restorable in
  Django admin and gives the boolean marker a home, with no third-party dependency.
- **Concrete custom comment model with added columns**: would allow `edited`/`deleted_at` directly on the comment, but
  swapping `COMMENTS_APP` to a managed model is a heavier migration with data-migration risk for existing deployments.
  The unmanaged proxy plus the side model avoids that.

## Open Questions

Most shaping questions are resolved (see Resolved Decisions). The remaining minor points:

- "Answered" is defined as *has any direct reply, in any moderation state* (a pending or spam-flagged reply still freezes
  the parent, since it may be approved later). Confirm this matches intent (vs. counting only currently-public replies,
  or treating any later top-level comment on the post as an answer).
- Is 200 the right default for the owned-id list cap, or should it be lower/unbounded-with-pruning?

## First Implementation Slice

1. Add `CAST_COMMENTS_ALLOW_AUTHOR_EDITS` (default `False`) in `comments/appsettings.py`, the system check in
   `checks.py` that rejects the `signed_cookies` session backend when the feature is enabled (hard error, no opt-out), and
   a shared `author_edits_enabled()` runtime guard (used by the post hook and both endpoints) that also returns `False`
   under `signed_cookies`.
2. On successful post in `post_comment_ajax`, record `str(comment.pk)` in `request.session["cast_owned_comments"]`
   (capped), only when the feature is enabled and the runtime guard passes.
3. Add the `CommentAuthorMeta(comment_pk unique text, edited bool, deleted_at)` model + migration, register it with a
   simple `ModelAdmin`, add a `post_delete` receiver on the active comment model to clean up its row on staff
   hard-delete, and add a `comment_was_flagged` (moderator-approval) receiver with a `post_save` fallback that clears
   `deleted_at` when a comment is restored. Update `SpamFilter.get_training_data_comments` to exclude comments whose
   `str(pk)` is in the set of `CommentAuthorMeta.comment_pk` values with `deleted_at` set (string-normalized in Python, not
   a cross-type SQL compare).
4. Add `post_comment_edit_ajax` and `post_comment_delete_ajax` views with `@csrf_protect` + `@require_POST` + AJAX check,
   each running inside a transaction that locks the comment row (`select_for_update`) and re-evaluates the shared
   eligibility predicate (owned, still-public, not answered) before writing, with generic not-found/not-owned responses.
   When the feature is enabled, also have `post_comment_ajax`'s reply path lock and re-check the `parent` row before
   inserting a reply, rejecting replies to a removed/author-deleted parent (closing the freeze race — see Concurrency).
5. Edit validates only the editable text + anti-abuse fields (identity fields immutable, preserved from the stored
   comment), re-dispatches `comment_will_be_posted` (re-classification through the same receiver chain as posting), does
   **not** fire `comment_was_posted`, sets `CommentAuthorMeta.edited = True`, and reports the public-visibility outcome.
6. Delete performs a soft delete (`is_removed = True` and `is_public = False`) and sets `CommentAuthorMeta.deleted_at`.
7. Add cache-based rate limiting per session/IP for both endpoints (no new dependency).
8. Expose editable-comment ids and the `edited` flag to the comment templates; render edit/delete controls + the
   ephemerality note only for eligible owned comments; add the inline edit form, the "(edited)" marker, and the "awaiting
   moderation" message.
9. Wire the two new routes into `comments/urls.py` alongside `post/ajax/`.
10. Document the feature, the required server-side session backend, the new session cookie for anonymous commenters, the
    frozen-once-answered rule, and the soft-delete-is-not-erasure caveat, and add a release note.

## Test Scenarios

- An author who posted in the current session can edit and delete that comment; the list reflects both, and an edited
  comment shows the "(edited)" marker.
- A second session/browser cannot edit or delete the first session's comment and receives a generic failure that does not
  confirm the comment exists.
- A client that POSTs an arbitrary `comment_id` it never created is rejected purely by the session check.
- A logged-in author can edit/delete their own comment through the same session path, with no `user`-FK-specific code;
  logging out (session flush) ends the ability.
- Editing benign text into spam re-moderates the comment to hidden/non-public, the response says so, and it can no longer
  be edited (no longer public).
- A comment that is not currently public (spam-flagged, staff-removed, staff-unpublished/pending, or author-deleted) is
  not editable or deletable; the endpoints return the generic failure.
- A comment that has any direct reply — including one currently pending or spam-flagged — can no longer be edited or
  deleted.
- A staff hard-delete of a comment in Django admin removes its `CommentAuthorMeta` row (no orphaned metadata).
- Editing does not fire `comment_was_posted`, so new-comment notifications/side effects are not re-triggered on edit.
- An edit request that also includes `name`/`email`/`url` does not change the comment's stored author identity; only the
  text changes.
- Concurrent delete + edit on the same comment: the second to acquire the row lock is rejected by the re-checked
  predicate; the comment is never both edited and resurrected.
- Concurrent reply + parent **delete**: either the reply commits and the delete is rejected, or the delete commits and
  the reply is rejected — never a child created under a deleted parent.
- Concurrent reply + parent **edit**: either the reply commits first and the edit is rejected (parent now answered), or
  the edit commits first and the reply proceeds against the edited text — the parent is never edited after a reply exists.
- A deployment with a custom `comment_will_be_posted` receiver sees that receiver run on edit, not just the default
  moderator.
- Author-deleting a comment sets `deleted_at` and excludes it from `get_training_data_comments`; a moderator-removed spam
  comment (no `deleted_at`) is still present as a spam example.
- A soft-deleted comment remains visible and restorable to staff in Django admin; restoring it (un-removing) clears
  `deleted_at` and re-includes it in spam training as ham without anyone editing the `CommentAuthorMeta` row.
- A comment that is author-deleted, restored by staff, and later removed as spam is labeled spam in training (restore
  cleared `deleted_at`), not excluded.
- Edit and delete endpoints reject non-AJAX requests and requests failing CSRF, matching `post_comment_ajax`.
- With `CAST_COMMENTS_ALLOW_AUTHOR_EDITS = False`, no session is written on post and the endpoints are unavailable/no-op.
- Enabling the feature with the `signed_cookies` session backend fails the system check at startup (server-side backend
  required; no opt-out).
- Even if the system check is skipped (e.g. raw WSGI), the runtime `author_edits_enabled()` guard disables the feature
  under `signed_cookies`: no owned-ids are written on post and the endpoints no-op.
- Ownership round-trips through the JSON session serializer: a POSTed string `comment_id` matches the session-stored
  `str(comment.pk)`, and a non-integer/bigint comment PK (e.g. UUID) is stored and compared correctly as a string.
- Rate limiting blocks rapid repeated edits/deletes from one session/IP.
- The owned-id list is capped and pruning the oldest ids only removes their edit affordance, nothing else.

## Success Criteria

- Authors can self-serve edit and delete their own comments within their session, with zero ability to touch any other
  comment or any comment that has been answered.
- Editing cannot be used to bypass moderation; spam edits are caught by the same filter as new posts.
- Deletion never corrupts threaded discussions, never destroys moderation evidence, and remains restorable by staff in
  Django admin.
- The feature is opt-in, documented (including the new-cookie, frozen-once-answered, and soft-delete caveats), and leaves
  current behavior unchanged when disabled.

## Implementation Notes (2026-06-22)

The backend slice landed and is covered by `tests/comment_author_edits_test.py` (reviewed clean). Key files:
`src/cast/comments/author_edits.py` (guard, ownership, eligibility, metadata helpers, rate limit),
`src/cast/comments/views.py` (`post_comment_edit_ajax`, `post_comment_delete_ajax`, reply-coordinated `post_comment`),
`src/cast/comments/models.py` (`CommentAuthorMeta`), `src/cast/comments/receivers.py`,
`src/cast/comments/admin.py`, `src/cast/comments/migrations/0002_commentauthormeta.py`,
`src/cast/checks.py` (`cast.E006`), and the `get_training_data_comments` exclusion in `src/cast/models/moderation.py`.

A few details settled differently from the design above and supersede it:

- **Restore clears `deleted_at` via a `post_save` receiver**, not `comment_was_flagged`. A `post_save` receiver on the
  comment model clears the marker whenever a comment is saved un-removed (`is_removed=False`), which covers both the
  django_comments approve action (it calls per-object `comment.save()`) and the admin change-form save — a strict
  superset of the `comment_was_flagged` path.
- **The stock non-AJAX reply path is blocked, not lock-coordinated.** Rather than have the stock `django_comments` post
  view participate in `select_for_update`, the overriding `views.post_comment` rejects replies (a `parent` in the POST)
  while the feature is on, so all threaded replies go through the lock-tight AJAX endpoint. Top-level stock comments are
  unaffected. A redundant `comment_will_be_posted` reply guard was therefore dropped.
- **JSON responses serialize `str(comment.pk)`** (UUID-safe), and `comment_has_reply` / the edit/delete views thread the
  `using` database through `select_for_update`/`save`, consistent with the text `comment_pk` storage.

Still pending (a follow-up slice): the browser frontend — ownership-aware edit/delete controls, inline edit form,
`(edited)` marker, and the ephemerality/"awaiting moderation" messaging across the `bootstrap4`, `plain`, and `vue`
template families plus the AJAX JS — and the matching user docs and release note. The endpoints are fully functional and
tested server-side; only the in-browser affordances are missing.
