# Scout rounds 55–57: media and glossary reads

Round 56 has no django-cast slice. Work targets develop, with synthetic fixtures
and no deployments or releases.

The round 55 input-boundary bundle is implemented: decimal ffprobe seconds and
bounded glossary source reads. The round 57 duration slice describes the same
probe defect and needs no second implementation. Focused regressions reproduced
the old failures; public duration and CLI contracts are documented in the media
guides and Unreleased notes.

The round 55 glossary publication bundle is implemented with one identity-index
read and optimistic field comparisons. Model validation scans remain. Synthetic
interleavings cover omitted notes and same-field conflicts, with independent
PostgreSQL connections exercised by the existing postgres tox/CI gate.

The round 57 metadata bundle is implemented: chapter readers reuse prefetches,
and snapshots use Wagtail rendition prefetching for contributor avatars. Query
regressions compare 1/20 audios/contributors with controlled caches and synthetic
images; shared contributors, missing derivatives and avatarless people remain
supported.
The round 57 authorization bundle is implemented with Wagtail public querysets
and batched candidate restriction data. Synthetic tests freeze aggregate and
anchor query budgets at 1/20 referencing episodes and retain inherited login,
password/group restrictions, alias ancestry, draft editing and cache policy.

All requested bundles are implemented. The final round 57 rich-text change
resolves only missing targets and caches localized relative/absolute results and
broken links within the render context. Synthetic 1/20-target batches repeat
without queries; language switches, separate contexts and absolute feed mode
retain their contracts. Its duplicate duration slice was already covered by the
round 55 input bundle. Round 56 supplied no django-cast slices.

Validation uses isolated local database/media directories per concurrent test
process. PostgreSQL could not initialize locally because the machine's SysV
shared-memory IDs were exhausted; the glossary branch's PostgreSQL CI jobs
exercised the separate-connection regressions successfully before integration.
