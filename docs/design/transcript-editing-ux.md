# Transcript editing in the Wagtail admin: a workflow an editor can follow

Status: implementation in progress, 2026-11-15. Slices 1–4 and 7 implemented; slices 5, 6, 8, 9 and 10 await owner answers. Integration branch: `develop`
(evidence taken at `e723b0c4`).

This document is about the **editor** who works in the Wagtail admin. It is not
about how listeners read a transcript. The owner's complaint is: "Ich finde es
schwierig, bei einer Podcast-Episode ein Transkript mit Sprechern hinzuzufügen.
Das ist alles sehr hakelig."

## Goal

An editor adds a transcript with named speakers to a podcast episode in four
clear steps, all reached from the episode page, without a shell and without
knowing the data model:

1. say who is in the episode (hosts and guests),
2. generate or upload the transcript,
3. name the voices and check the uncertain passages,
4. look at the result as the public will see it.

No step may silently remove or change speaker names that are already published.

## Non-goals

- No change to public transcript rendering, the player, feeds or themes.
- No new service, queue, storage or JavaScript framework. Everything stays in
  Django views, Wagtail panels and templates, with small inline scripts as
  today.
- No change to how Voxhelm transcribes, diarizes or recognises voices.
- No new data model for transcripts. The three public files, the two private
  sidecars and `TranscriptSpeakerMapping` stay as they are. One slice adds one
  file field (slice 10).
- No free-text editing of transcript segments (see owner question 3).
- No bulk tooling for many episodes at once. The management commands stay for
  that.

## How the walk-through was done

A local instance of the example project ran on SQLite with Wagtail 8.1 and
Django 6.1. A superuser, a podcast, a 60-second synthetic audio file and a
12-segment sample transcript (Podlove, WebVTT, DOTe, four speaker labels and one
unlabelled segment) were used. Headless Chromium (Playwright) clicked through
the admin and took 37 screenshots; nine are kept in
`docs/design/transcript-editing-ux/`.

Voxhelm is not available locally. A 60-line local stand-in answered the three
HTTP calls django-cast makes (submit job, poll job, download files) so that the
real "Generate transcript" button, the real completion task and the real import
code ran. It returned the same transcript with renumbered speaker labels and a
known-speaker sidecar, which is what a second diarization run does. A
1,200-segment transcript (one hour at three seconds per segment) was loaded to
test the editor at realistic size.

Staging was not opened; the local run and the code answer the questions.

## Current state

### The path an editor has to take today

Task: one new episode, two hosts and one guest who do not exist as contributors
yet, transcript files at hand, no Voxhelm. The editor needs six visits to four
admin areas. None of them links to the next.

| # | Where | What | Page loads |
|---|-------|------|-----------:|
| 1 | Audio → Add audio | upload the audio files | 3 |
| 2 | Pages → podcast → Add child page | create the episode, pick the audio from a dropdown | 3 |
| 3 | Transcript → Add transcript | pick the audio again, fill three file fields | 3 |
| 4 | Contributors → Add (three times) | name, hand-typed slug, role | 7 |
| 5 | Pages → podcast → episode | scroll to the last panel, open it, add three rows | 3 |
| 6 | Transcript → click the ID | scroll down, choose a name per label, save | 3 |

That is 22 page loads, three chooser dialogs and about 55 clicks. Assigning the
three contributors in step 5 alone takes 11 clicks. There is no seventh step
"look at the result": the admin has no view of the finished transcript.

With Voxhelm, steps 3 and 6 change. Step 3 becomes one click in the episode's
"More actions" menu, and step 6 becomes a review of suggestions. The django-chat
runbook (`docs/contributors-and-diarization.md` in `ephes/django-chat`) shows
what editors really do instead: it documents the whole process as shell
commands and Python snippets over SSH, including finding out who "Speaker 2"
is, creating contributors, rewriting labels, seeding voice references,
reordering contributors, and backing up files by hand before a regeneration
because "`--force` overwrites existing labels".

### Friction points, ranked by impact

Each point names what was seen and where the behaviour comes from.

#### 1. "Generate transcript" overwrites a reviewed transcript without asking

On a live episode whose speakers were named, one click on More actions →
"Generate transcript" was enough. There was no confirmation. The public
transcript had shown `Jochen Wersdörfer, Dominik Geldmacher, Johannes
Spielmann, …, Werbung`; directly after the click every segment had no speaker.
The old files were deleted from storage, so nothing could be restored.
Screenshot `06-episode-more-actions-generate.png`.

- The action is a plain submit button, shown whenever Voxhelm is configured:
  `src/cast/wagtail_hooks.py:274-304`,
  `src/cast/templates/cast/wagtail/voxhelm_generate_transcript_action.html:2-13`.
- The view enqueues without looking at an existing transcript:
  `src/cast/views/voxhelm.py:91-121` (episode) and `:124-145` (audio).
- The import replaces all files and deletes the old ones:
  `src/cast/voxhelm/service.py:533-553`, `src/cast/file_replacement.py:115-120`.
- The management command does protect a complete transcript unless `--force`
  is given (`src/cast/management/commands/generate_transcripts.py:61-64`). The
  admin button has no such check.

#### 2. After a regeneration the form offers the old, now wrong, names

A new diarization run numbers the voices differently. After the run above,
"Speaker 1" was the guest. The mapping form still showed "Jochen Wersdörfer
(Host)" selected for "Speaker 1", next to samples in which the guest speaks, with
the small note "Needs review". Pressing "Save speaker mappings" without changing
anything answered "Speaker mappings saved." and published the hosts' names on
the wrong voices. Screenshot `07-transcript-edit-after-regen.png`.

- The form takes its initial value from the stored mapping regardless of the
  review state: `src/cast/forms.py:460-465`.
- Saving sets every row with a target to "approved" with the new fingerprint:
  `src/cast/forms.py:532-548`.
- Public output itself is safe while the row is in "needs review": only
  approved rows with the current fingerprint are used
  (`src/cast/transcripts/visibility.py:183-193`). The wrong names reach the
  public only through the re-approval above. Once re-approved, the row also
  names the segments that "Approve and apply confident suggestions" left on the
  raw label "Speaker 1" (`src/cast/transcripts/visibility.py:227-250`). The fix
  therefore belongs in the form, not in the visibility filter.

#### 3. The segment review breaks at real episode length

The review table has one row and one dropdown per segment, for all segments.
With 1,200 segments the page was 1.9 MB with 1,204 dropdowns. The "Map speakers
to contributors" section started 103,899 pixels down the page. "Save segment
decisions" failed with HTTP 400 `TooManyFieldsSent`, because Django accepts at
most 1,000 form fields by default. Screenshot `08-save-decisions-1200.png`.

- All segments become form fields: `src/cast/forms.py:591-600`.
- All rows are rendered: `src/cast/templates/cast/transcript/edit.html:408-461`.
- No site setting was checked. A site that raised
  `DATA_UPLOAD_MAX_NUMBER_FIELDS` avoids the error but keeps the page size. The
  django-chat runbook reports 681 suggestions for one episode.

#### 4. The episode page does not know about its transcript

An episode with audio and a finished, published transcript shows nothing about
it: no status, no link, no place to add one. The only transcript element on the
page is a status line that exists only after a Voxhelm run, and it sits in the
middle of the form. Without Voxhelm configured there is no hint that transcripts
exist at all. Screenshot `01-episode-edit-draft.png`.

- The panel hides itself without a generation record:
  `src/cast/wagtail_panels.py:30-31`,
  `src/cast/transcripts/generation_status.py:38-45`.
- The link "Edit transcript" appears only for a succeeded generation:
  `src/cast/transcripts/generation_status.py:61-63`.
- Panel order: `src/cast/models/pages.py:742-786`.

#### 5. A transcript is called "1"

The transcript editor is titled "Editing 1". The list has two columns, "ID" and
"Audio title". Messages read "Transcript file '1' updated". Nothing names the
episode, and nothing links back to it. Saving the files sends the editor away to
the list. Screenshot `05-transcript-edit-after-mapping.png`.

- Title: `src/cast/templates/cast/transcript/edit.html:5` and `:346`.
- List: `src/cast/templates/cast/transcript/list.html:9-33`; the search looks
  at the audio title only (`src/cast/views/transcript.py:156-157`).
- Messages use the primary key: `src/cast/views/transcript.py:164-165`, `:466`.
- Redirect to the list after saving: `src/cast/views/transcript.py:469`,
  `src/cast/views/media.py:187`.

#### 6. Named voices cannot become voice samples

Voice samples ("voice references") are what lets Voxhelm recognise the hosts
next time. After all labels were mapped and shown as "Approved", the
voice-reference table still said "Map this speaker label to one contributor
before creating a voice reference" and "Needs contributor mapping" for every
candidate. Screenshot `09-voice-reference-needs-mapping.png`.

- The contributor is found only when the label text equals a contributor's
  display name: `src/cast/transcripts/editing.py:60-72`. That is true only after
  names were written into the files, which the admin does only through
  known-speaker suggestions, which need voice samples first. For the first
  episode of a show this is a dead end. The runbook seeds the samples by script.

#### 7. Speakers are spread over three places

Contributors are created under "Contributors", assigned in the episode's last
panel (collapsed, 1,541 pixels down), and used in the transcript editor. When no
contributor is assigned, the transcript editor says "No episode contributors
are available for this transcript's audio" and offers no link. The contributor
slug is not filled from the name. Screenshot `04-episode-contributors-filled.png`.

- Panel position and collapsed state: `src/cast/models/pages.py:781-785`.
- Message without link: `src/cast/templates/cast/transcript/edit.html:492-494`.
- Plain field panels for name and slug: `src/cast/models/contributors.py:85-87`.
- Hosts are the same every episode but have to be added every time. The runbook
  uses a script for assignment and another for ordering.

#### 8. One page, four tools, expert vocabulary

The transcript editor stacks, in this order: the three file fields,
"Known-speaker suggestions", "Glossary corrections", "Map speakers to
contributors" and "Voice-reference candidates". Two of them name speakers in
different ways and do not explain how they relate. Observed consequences:

- After "Approve and apply confident suggestions" the mapping form listed the
  real names as labels to be mapped ("Dominik Geldmacher — Unmapped").
- The success message counted "24 public transcript entries" for a 12-segment
  transcript, because it adds up the three file formats
  (`src/cast/views/transcript.py:321-327`).
- After uploading different files by hand, the suggestions of the earlier
  Voxhelm run were still offered for the new files.
- Labels such as "Use bulk result", "margin 0.03", "One-off display name" and
  "Store approved speaker mappings … without rewriting the raw Podlove, DOTe,
  or WebVTT files" describe the implementation, not the task
  (`src/cast/templates/cast/transcript/edit.html:390`, `:482`;
  `src/cast/forms.py:583-584`).

#### 9. There is no preview

The editor cannot read the transcript in the admin. The mapping form shows
three samples per voice; the rest is invisible. Wagtail's page preview of the
episode leaves the transcript link out on purpose
(`src/cast/models/pages.py:830-832`). The only way to check the result is to
publish and open the public page. The runbook verifies with `curl` and a Playwright
script.

- A segment can get a different speaker only when a Voxhelm sidecar exists
  (the review table). For an uploaded transcript there is no way to correct one
  segment.

#### 10. Upload asks for three formats and explains none

Screenshots `02-transcript-add.png` and `03-transcript-add-duplicate.png`.

- The three fields are described as "The transcript format for the Podlove Web
  Player" and "… for feed / podcatchers" (`src/cast/models/transcript.py:42-65`).
  Nothing says that all three are needed for player and feed, or what is
  missing when one is left out.
- A transcript with an audio and no file at all is accepted and reported as
  "Transcript file '1' added."
- A WebVTT file in the Podlove field is rejected as "Podlove transcript is not
  valid JSON."
- A second transcript for the same audio ends in "Transcript with this Audio
  already exists." without a link to the existing one. The audio dropdown offers
  audios that already have a transcript, labelled "1 - Folge 1 Audio"
  (`src/cast/forms.py:311-315`).

#### 11. Generation gives little feedback

- The status line does not update. The editor has to reload the page to see
  whether the run finished
  (`src/cast/templates/cast/wagtail/episode_transcript_status_panel.html`).
- A run without voice samples produces only anonymous labels. The warning for
  that is logged and printed by the management command but never shown in the
  admin (`src/cast/voxhelm/service.py:345-348`, `src/cast/views/voxhelm.py:57-67`).
- A failed submission showed the error once; the status line kept saying
  "Succeeded", because only a new or interrupted record is marked as failed
  (`src/cast/voxhelm/service.py:630-633`).
- Whether speakers are detected is set on the audio page, in a field with the
  values "Inherit / Enabled / Disabled" that does not say what "Inherit"
  currently means (`src/cast/models/audio.py:61-80`).

### What already works and stays

- Upload validation catches broken files with a field-level message
  (`src/cast/forms.py:326-376`).
- The mapping form shows samples per voice and plays them from the timestamp.
- Roles follow the contributor's default role when a contributor is chosen.
- Concurrent edits are refused with "Reload the transcript" instead of being
  merged (`src/cast/views/transcript.py:561-565`).
- Names reach the public only for visible contributors assigned to the episode
  (`src/cast/transcripts/visibility.py`).

## Target workflow

Everything starts on the episode page. Two new hosts-and-guests conveniences
and one hub panel replace the six visits.

**Step 1 – Who is in the episode.** The "Contributors" panel sits directly
under "Podcast audio" and is open. For a new episode the hosts of the previous
episode of the same podcast are already filled in. The editor adds the guest:
"Add contributor", "Choose", pick. A new person is created in the chooser's
"create" tab if the Wagtail version offers one, otherwise under Contributors,
where the slug now fills itself.

**Step 2 – Get the transcript.** A "Transcript" panel under the contributors is
always visible and says where things stand:

| State | The panel shows |
|-------|-----------------|
| no audio saved | "Choose the podcast audio and save first." |
| no transcript | readiness facts (below), "Generate transcript", "Upload transcript files" |
| generation running | "Transcript is being generated (started 14:02)." It refreshes itself. |
| generation failed | the error and "Try again" |
| transcript present | "3 of 3 voices named · 14 passages without a name", "Edit transcript and speakers", "Preview", "Generate again…" |

Readiness facts before generating: "Speaker detection: on (site default)" with
a link to change it, and "Voice samples: 2 of 3 contributors. Johannes Spielmann
has none, so this voice has to be named by hand."

"Upload transcript files" opens the upload form with the audio already chosen.
"Generate again…" opens a confirmation page that lists what will be replaced.

**Step 3 – Name the voices.** "Edit transcript and speakers" opens a page
titled "Transcript: Folge 1" with a link back to the episode. It has these
sections, in this order:

1. *Speakers.* One row per voice with samples to listen to and one dropdown of
   the episode's contributors. If Voxhelm recognised voices, the row shows the
   suggestion and one button applies all confident ones.
2. *Passages to check.* Only passages that are uncertain or have no name, 50 per
   page. A filter shows all passages.
3. *Voice samples for next time.* Collapsed. Works for every named voice.
4. *Spelling corrections.* The glossary review, unchanged.
5. *Files.* Collapsed. The three file fields.

**Step 4 – Check.** "Preview" shows the whole transcript as the public will see
it, with names, grouped by speaker, each timestamp playable. Passages without a
name are marked. The speaker of a single passage can be changed there.

Counted the same way as above, the task takes two admin areas, about six page
loads and about 20 clicks.

## Options considered

**A. Episode page as hub, existing transcript views reworked (chosen).**
Keep the models, the hand-written transcript views and the services. Add a hub
panel on the episode page, fix the dangerous paths, reorder and rename the
transcript page, add a read-only preview.
*For:* each slice is small and independently useful; the worst problems (1, 2,
3) are fixed by guards and paging, not by new concepts; nothing changes for
sites that use the management commands. *Against:* the transcript page keeps
its hand-written template, and the two ways of naming speakers remain two
mechanisms under one heading.

**B. Make the transcript part of the episode page (inline panel or snippet
chooser).** *Against:* a transcript belongs to an audio, which several episodes
can share (`src/cast/models/transcript.py:41`), so it cannot be an inline child
of one page. Uploading multi-megabyte files and running review actions inside
the page editor's single form would mix page revisions with file writes that
are not versioned. Rejected.

**C. A dedicated transcript editor as a JavaScript application.** A waveform,
inline text editing, drag-to-assign speakers. *Against:* new frontend
infrastructure and build artefacts in a package that requires 100 % coverage; a
second source of truth for the edit rules that the server already enforces. The
owner asked for simple and Wagtail-native. Rejected.

**D. A multi-step wizard.** *Against:* the steps are not strictly sequential
(contributors can change after generation, a regeneration restarts step 3), so
a wizard needs its own state. The hub panel gives the same guidance by showing
the state and the next action. Rejected.

**E. Merge the two naming mechanisms into one.** Remove either the label
mapping or the per-segment suggestions. *Against:* both are needed (mapping for
plain diarization and uploads, suggestions when voice samples exist), both are
covered by many tests, and both have published data. The design presents them
as one "Speakers" section instead. Rejected for this plan.

## Chosen design in detail

### Guard rails first

1. **Confirm before replacing.** When the audio already has a transcript, the
   episode action and the audio-page button lead to a confirmation page instead
   of posting directly. The page is a normal Wagtail confirmation view, like
   delete. It states what will be replaced: number of named voices, number of
   per-passage decisions, glossary decisions, and whether the episode is live
   ("speaker names disappear from the public transcript until you name the
   voices again"). The POST views refuse an unconfirmed request when a
   transcript exists, so a stale form cannot bypass the page.
2. **A mapping that needs review is not pre-selected.** For a row in state
   "needs review" the dropdown starts empty and a hint says "Before the
   transcript changed: Jochen Wersdörfer. Listen to the samples and choose
   again." Saving the form leaves untouched rows in "needs review".
3. **Suggestions belong to the files they were made for.** When new public
   files are stored by upload, the known-speaker sidecar of the previous run is
   detached, as the code already does for an invalid sidecar
   (`src/cast/views/transcript.py:519-534`).

### Episode hub panel

`EpisodeTranscriptStatusPanel` becomes the hub. It is always shown and renders
one of the states in the table above. It reads only the saved state of the
latest revision, as the generate view already does
(`src/cast/views/voxhelm.py:98-99`).

The numbers come from existing functions: `get_speaker_labels`,
`speaker_mappings`, `known_speaker_review_summary`,
`build_known_speaker_references`, `resolve_audio_diarization_enabled`. They read
the transcript files, so the panel computes them only when a transcript exists
and reads each file once.

While a generation is active, a small inline script asks a new JSON status view
every five seconds and reloads the panel's text when the state changes. It stops
after the run ends. No websocket, no task queue change.

The "Generate transcript" entry in "More actions" stays for people who know it.

### Transcript page

- Title and header: "Transcript: {episode title}", falling back to the audio
  title. A link "Episode: {title}" goes to the episode editor; with several
  episodes on one audio all are listed.
- The list gets the columns Episode, Audio, Files (player / feed), Voices named,
  and searches episode titles as well.
- Messages name the episode. Saving files stays on the page.
- Section order and names as in step 3 above. The speaker rows hide the
  dropdown for a label that already is the display name of an assigned
  contributor and show "named" instead.
- Messages count passages, not file entries.
- Voice samples resolve the contributor through the current approved mapping as
  well as through an equal name. The signed candidate token already contains
  the contributor (`src/cast/transcripts/editing.py:118-131`), so the create
  path keeps its protection.
- When no contributor is assigned, the page links to the episode's contributor
  panel.

### Passages to check, at any length

The review form is built only for the passages on the current page. The service
already changes only the positions it is given
(`src/cast/transcripts/services.py:353-356`), so a partial form is safe once the
form stops treating absent positions as "reset". The default filter is "needs a
decision": uncertain, no suggestion, or already decided by an editor. Page size
is 50, so one request carries about 55 fields. Choices get plain names: "As
suggested", "No name", then the contributors.

### Preview and single-passage correction

A read-only view under the transcript namespace renders the Podlove data through
the same functions the public view uses
(`apply_public_speaker_mapping_to_podlove_data`, `sanitize_podlove_data`,
`editor_speaker_preview_episode`), for the episode's latest revision. It needs
"change" permission on the transcript. Consecutive passages of one speaker are
grouped. The page is paged by 200 passages.

Each passage has "Change speaker". The change goes through one new service
function. If the transcript has a sidecar entry for that start time, the choice
is stored as an editor decision and applied through the existing path. If it has
none, the name is written to the three files for that start time with the
existing per-format writers (`src/cast/models/transcript.py:435-487`), keeping
the source fingerprint. Both paths keep the existing concurrency check.

### Upload

- Help texts say what each file is for: "Shown in the web player and on the
  transcript page" and "Sent to podcast apps through the feed".
- The form refuses a transcript without any file.
- Each uploaded file is recognised by content (WebVTT header, `transcripts`
  key, `lines` key). A file in the wrong field produces "This looks like a
  WebVTT file. Put it in the WebVTT field."
- After saving, a notice names what is missing: "Podcast apps get no transcript
  yet: the WebVTT and DOTe files are missing."
- The audio dropdown lists audios without a transcript and shows the episode
  title. `?audio=<id>` preselects one. The duplicate error links to the existing
  transcript.

### Contributors

- The panel moves under "Podcast audio", open, with the help text "Hosts and
  guests of this episode. Speaker names in the transcript can only be chosen
  from this list."
- A new episode starts with the host rows of the podcast's most recent episode.
  The rows are ordinary unsaved inline rows, so the editor can remove them.
- The contributor form fills the slug from the name with Wagtail's
  `TitleFieldPanel`.

### Keeping the previous version

After the confirmation exists, a regeneration or a manual file replacement
stores the replaced public files, sidecars and mapping rows as one private JSON
bundle in a new nullable file field on `Transcript`, in the private storage
used for the sidecars. The transcript page offers "Restore the version from
{date}" while a bundle exists. One level only; a restore swaps current and
previous. This is the only migration in the plan.

## Risks and failure modes

| Risk | Handling |
|------|----------|
| The hub panel reads transcript files on every episode edit page load and slows the editor down. | Read each file once per request; show counts only when a transcript exists; cap by the existing 10 MiB / 30 MiB evidence budget and show "Open the transcript" without counts when it is exceeded. Test with a query and file-open counter. |
| The status poll keeps running in forgotten tabs. | Poll only while a run is active, stop after 30 minutes, and stop when the tab is hidden. |
| The confirmation is bypassed by a direct POST or by the API. | Enforce it in the views, not in the template. The editor API (`src/cast/api/editor/transcripts.py`) keeps its own explicit behaviour; the slice documents it and adds a test that pins it. |
| An empty dropdown for "needs review" rows makes editors lose a correct mapping after a harmless change. | A mapping only becomes "needs review" when the received files change. The hint shows the former name, so re-choosing is one click per voice. |
| A partial review form resets decisions on other pages. | The form is built from the positions on the page only; a test saves page 2 and asserts page 1 decisions are unchanged. |
| Writing a single passage's speaker to the files diverges between formats when a start time exists in one format only. | Use the existing destination-time validation (`src/cast/transcripts/services.py:228-247`) and refuse with a message instead of writing one format. |
| Prefilled host rows are saved by accident on an episode where a host is absent. | Rows are visible and removable; the help text says they were copied from the previous episode. Owner question 2 decides whether to do this at all. |
| Prefilling unsaved inline rows behaves differently on Wagtail 7.0 and 8.1. | The slice starts with a spike test on both; if it fails on one, the fallback is a "Copy hosts from previous episode" button that posts to a view. |
| The previous-version bundle doubles private storage per transcript. | One level only, text files of at most a few megabytes; the bundle is deleted with the transcript. |
| Renamed labels and moved sections break sites that override the transcript templates. | The templates are under `cast/transcript/` and not part of a theme. The release notes list the renamed blocks. |
| Translations: new strings appear in English only. | All new strings go through `gettext`; the existing German catalogue is updated in the same slice where one exists. |

## Test and qualification plan

**Unit and view tests (pytest, 100 % coverage as required by `just check`).**
Each slice adds tests next to the code it changes, mirroring the module path:

- generate views: transcript present → redirect to confirmation; confirmed POST
  enqueues; unconfirmed POST with transcript is refused; no transcript → as
  today;
- mapping form: a "needs review" row has no initial target; an unchanged save
  leaves it in "needs review" and publishes no name;
- upload: sidecar detached when public files are replaced; empty transcript
  refused; wrong-field detection; duplicate error contains the edit link;
  `?audio=` preselects;
- review form: built for a page of positions; saving one page leaves other
  decisions unchanged; a 1,200-segment transcript renders at most 50 rows and a
  save sends fewer than 100 fields;
- hub panel: one test per state; counts; bounded file reads;
- status view: permission, JSON shape for each state;
- preview: uses the public mapping and sanitizer; needs "change" permission;
  never returns sidecar data;
- single-passage change: sidecar path and direct path; conflict → 409;
- voice samples: contributor resolved through the mapping; token still bound to
  the contributor;
- restore: bundle written on replacement; restore swaps; bundle deleted with
  the transcript.

**Admin browser test.** One opt-in journey in
`tests/transcript_admin_browser_test.py`, following the existing pattern in
`tests/comment_browser_test.py` (`CAST_RUN_BROWSER=1`, `live_server`, Chromium
through `CAST_BROWSER_EXECUTABLE`). Voxhelm is replaced by a stub client, as in
the existing Voxhelm tests. The journey grows with the slices:

1. open a new episode: contributors panel is open and under the audio;
2. save with audio: the Transcript panel shows "Generate" and "Upload";
3. upload through the panel link: audio is preselected; save stays on the page;
4. name three voices; the panel shows "3 of 3 voices named";
5. open the preview; the three names are present; change one passage;
6. "Generate again…" shows the confirmation; confirm; the mapping rows are
   empty with the "before" hint; saving unchanged publishes no name;
7. a 1,200-segment fixture: the review shows 50 rows and saves without error.

The journey fails on any browser console error.

**Qualification before each merge.** `just check`. Slices that touch Wagtail
panels or the page form (2, 9) also run the tox environments for Wagtail 7.0
and 8.1. For slices 2, 5 and 6 the implementer adds before/after screenshots of
the changed page to the merge note.

**Acceptance for the whole plan.** The task from "The path an editor has to
take today" is repeated on the local example project and counted again. Target:
two admin areas, at most eight page loads, no shell, and none of the eleven
friction points reproducible.

## Implementation plan

Ten slices, biggest gain first. Each is 30–90 minutes for an implementation
worker, includes its tests, and updates `docs/media/audio-and-transcripts.rst`
and `docs/releases/unreleased.rst` where behaviour changes. Slices 1, 3 and 4
are independent of each other. Slice 2 is the base for 7. Slice 5 is the base
for 6.

### Slice 1 – No silent overwrite, no stale names

Fixes friction points 1 and 2.

- Files: `src/cast/views/voxhelm.py`, `src/cast/admin_urls/voxhelm.py`,
  `src/cast/wagtail_hooks.py`,
  `src/cast/templates/cast/wagtail/voxhelm_generate_transcript_action.html`,
  new `src/cast/templates/cast/wagtail/confirm_regenerate_transcript.html`,
  `src/cast/templates/cast/audio/edit.html`, `src/cast/forms.py`,
  `src/cast/templates/cast/transcript/edit.html`, tests under `tests/`.
- Acceptance:
  - With an existing transcript, the episode action and the audio button open a
    confirmation page that lists named voices, per-passage decisions and
    whether the episode is live. Nothing is enqueued before the confirm POST.
  - A POST without the confirmation field is refused with 400 when a transcript
    exists.
  - Without a transcript the behaviour is unchanged.
  - A mapping row in "needs review" renders with an empty dropdown and the
    former name as a hint. Saving the unchanged form leaves it in "needs
    review" and the public Podlove JSON has no speaker for that label.

### Slice 2 – Transcript panel on the episode page

Fixes friction point 4 and the first half of 7.

- Files: `src/cast/wagtail_panels.py`,
  `src/cast/templates/cast/wagtail/episode_transcript_status_panel.html`,
  `src/cast/transcripts/generation_status.py`, `src/cast/models/pages.py`
  (panel order and heading only), `src/cast/views/media.py` and
  `src/cast/views/transcript.py` (`?audio=` on add), tests.
- Acceptance:
  - The panel is shown for every saved episode and renders the five states of
    the table in "Target workflow".
  - With a transcript it shows "{n} of {m} voices named" and links to the
    transcript page; without one it links to the upload form with the audio
    preselected and, when Voxhelm is configured, offers "Generate transcript".
  - "Contributors" is the panel after "Podcast audio" and is open.
  - Opening the episode editor opens each transcript file at most once.

### Slice 3 – A transcript has a name and a way back

Fixes friction point 5.

- Files: `src/cast/templates/cast/transcript/edit.html`, `index.html`,
  `list.html`, `results.html`, `src/cast/views/transcript.py`,
  `src/cast/views/media.py` (optional per-config redirect target), tests.
- Acceptance:
  - Editor title and header read "Transcript: {episode title}" and link to each
    episode that uses the audio; the fallback is the audio title.
  - The list shows Episode, Audio, Files and Voices named, and finds a
    transcript by episode title.
  - Success and error messages name the episode.
  - Saving the file form returns to the transcript page.
  - The list issues a constant number of queries for a page of 20 transcripts.

### Slice 4 – Passages to check at any length

Fixes friction point 3.

- Files: `src/cast/forms.py` (`KnownSpeakerSegmentReviewForm`),
  `src/cast/views/transcript.py`,
  `src/cast/templates/cast/transcript/edit.html`, tests.
- Acceptance:
  - The review shows at most 50 passages per page; the default filter is
    "needs a decision"; a second filter shows all.
  - Saving one page changes only the decisions on that page.
  - With a 1,200-segment transcript the editor page is under 300 kB and a save
    succeeds with Django's default field limit.
  - Choices read "As suggested", "No name" and the contributor names.

### Slice 5 – One "Speakers" section in plain words

Fixes friction points 6 and 8.

- Files: `src/cast/templates/cast/transcript/edit.html` (split into includes
  under `cast/transcript/`), `src/cast/views/transcript.py`,
  `src/cast/transcripts/editing.py`, `src/cast/media_derivation.py` or
  `src/cast/forms.py` (sidecar detach on upload), tests.
- Acceptance:
  - Section order: Speakers, Passages to check, Voice samples (collapsed),
    Spelling corrections, Files (collapsed).
  - A label that equals an assigned contributor's display name is shown as
    named, without a dropdown.
  - After mapping "Speaker 1" to a contributor, its voice-sample candidates
    offer "Save pending" and "Create approved".
  - Replacing a public file by upload detaches the known-speaker sidecar.
  - Messages count passages. No user-visible text contains "bulk", "margin" or
    "raw".
  - With no contributor assigned, the page links to the episode's contributor
    panel.

### Slice 6 – Preview and single-passage speaker change

Fixes friction point 9.

- Files: `src/cast/admin_urls/transcript.py`, `src/cast/views/transcript.py`,
  new `src/cast/templates/cast/transcript/preview.html`,
  `src/cast/transcripts/services.py`, `src/cast/models/transcript.py` (thin
  method), tests.
- Acceptance:
  - "Preview" on the transcript page and in the episode panel shows the full
    transcript with the names the public would get for the episode's latest
    revision, 200 passages per page, timestamps playable.
  - Passages without a name are marked and counted at the top.
  - "Change speaker" on a passage updates Podlove, DOTe and WebVTT for that
    start time, or stores an editor decision when a sidecar entry exists.
  - A changed transcript in between yields the existing "Reload" response.
  - The view requires "change" permission and never outputs sidecar content.

### Slice 7 – Generation feedback

Fixes friction point 11.

- Files: `src/cast/views/voxhelm.py`, `src/cast/admin_urls/voxhelm.py`,
  `src/cast/voxhelm/service.py` (failure state only),
  `src/cast/templates/cast/wagtail/episode_transcript_status_panel.html`,
  `src/cast/templates/cast/audio/_transcript_status.html`, tests.
- Acceptance:
  - A JSON status view returns the state for an audio the user may change.
  - While a run is active the panel text updates without a reload and ends
    with a link "Name the voices".
  - Before generating, the panel shows whether speaker detection is on and for
    how many contributors a voice sample will be sent, naming those without.
  - A failed submission sets the status to failed with the message.
  - Polling stops when the run ends, after 30 minutes, or when the tab is
    hidden.

### Slice 8 – Upload that explains itself

Fixes friction point 10.

- Files: `src/cast/forms.py` (`TranscriptForm`), `src/cast/models/transcript.py`
  (help texts; a migration that changes help text only),
  `src/cast/templates/cast/transcript/add.html`, `src/cast/views/transcript.py`,
  tests.
- Acceptance:
  - A transcript without any file is refused.
  - A file in the wrong field is refused with a message that names the right
    field.
  - After saving, a notice lists which of "web player" and "podcast apps" have
    no transcript yet.
  - The audio dropdown lists only audios without a transcript and shows the
    episode title; the duplicate error links to the existing transcript.

### Slice 9 – Contributors with less typing

Fixes the rest of friction point 7.

- Files: `src/cast/models/contributors.py` (panels), `src/cast/models/pages.py`
  (`CustomEpisodeForm`), tests; tox runs for Wagtail 7.0 and 8.1.
- Acceptance:
  - Typing a contributor's name fills the slug.
  - A new episode under a podcast whose latest episode has hosts starts with
    those host rows, in the same order; an episode that already has rows is not
    touched. If owner question 2 is answered with no, this point is dropped.
  - Both behaviours pass on Wagtail 7.0 and 8.1.

### Slice 10 – Previous version and restore

Completes friction point 1.

- Files: `src/cast/models/transcript.py`, one migration,
  `src/cast/voxhelm/service.py`, `src/cast/forms.py`,
  `src/cast/transcripts/services.py`, `src/cast/views/transcript.py`,
  `src/cast/templates/cast/transcript/edit.html`, tests,
  `docs/operations/backup.rst`.
- Acceptance:
  - Replacing public files by generation or upload stores the replaced files,
    sidecars and mapping rows as one private bundle.
  - The transcript page offers "Restore the version from {date}"; restoring
    brings back files, sidecars and mappings and keeps the replaced state as
    the new previous version.
  - The bundle is never served publicly and is deleted with the transcript.

## Open owner questions (class C)

1. Soll „Transkript neu erzeugen" bei einer bereits veröffentlichten Episode
   nach der Rückfrage sofort die öffentlichen Sprechernamen entfernen (wie
   heute), oder soll die Episode das alte Transkript weiter zeigen, bis du die
   Stimmen im neuen Transkript benannt hast? Das Zweite ist sicherer, braucht
   aber einen Entwurfszustand für Transkripte und wäre ein eigener, größerer
   Schritt. Der Plan nimmt das Erste an und sichert es mit Rückfrage und
   „Vorherige Version wiederherstellen" ab.
2. Sollen bei einer neuen Episode die Hosts der vorherigen Episode automatisch
   eingetragen werden? Wenn ja: in welcher Reihenfolge sollen Hosts und Gäste
   stehen (Django Chat stellt Gäste nach vorn)?
3. Brauchst du im Admin auch die Korrektur des Textes einzelner Passagen
   (Tippfehler, falsch verstandene Wörter), oder reichen das Glossar und das
   Ändern des Sprechers pro Passage?
4. Lädst du Transkripte überhaupt von Hand hoch, oder kommen sie praktisch
   immer aus Voxhelm? Wenn sie immer aus Voxhelm kommen, kann Slice 8 ans Ende
   rücken oder entfallen.
5. Darf die Oberfläche die Fachbegriffe ersetzen („Known-speaker suggestions"
   wird „Speakers", „Voice reference" wird „Voice sample")? Die Doku und das
   Django-Chat-Runbook verwenden die alten Begriffe und müssten nachgezogen
   werden.

## Screenshots

All from the local walk-through, in `docs/design/transcript-editing-ux/`.

| File | Shows |
|------|-------|
| `01-episode-edit-draft.png` | Episode with audio: no transcript element on the page. |
| `02-transcript-add.png` | Upload form: audio dropdown and three file fields. |
| `03-transcript-add-duplicate.png` | "Transcript with this Audio already exists." without a link. |
| `04-episode-contributors-filled.png` | Contributors panel at the end of the episode form, three rows. |
| `05-transcript-edit-after-mapping.png` | Page "Editing 1": files, glossary, mapping with samples. |
| `06-episode-more-actions-generate.png` | "Generate transcript" in the footer menu of a live episode. |
| `07-transcript-edit-after-regen.png` | After regeneration: review table, and "Speaker 1 – Needs review" with the old host selected next to the guest's samples. |
| `08-save-decisions-1200.png` | `TooManyFieldsSent` on "Save segment decisions" with 1,200 segments. |
| `09-voice-reference-needs-mapping.png` | Voice samples ask for a mapping that is already saved. |
