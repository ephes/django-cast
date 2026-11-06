# DRF and Pillow advisory-floor CI repair — implemented

Scheduled CI run [41455061407](https://github.com/ephes/django-cast/actions/runs/41455061407)
on `ff692f9002f2` (2026-11-02) failed only the advisory-floor audit, at the
`djangorestframework==3.17.2` entry:

```text
Found 3 known vulnerabilities in 1 package
Name                Version ID              Fix Versions
djangorestframework 3.17.2  CVE-2026-114138 3.18.2
djangorestframework 3.17.2  CVE-2026-114136 3.18.2
djangorestframework 3.17.2  CVE-2026-114137 3.18.2
```

As in the [2026-10-03 repair](2026-10-03-dependency-floor-ci-repair.md), the
hosted loop stops at the first failing minimum, so the entries after DRF were
not audited in that run. Checking all 15 minima locally with the CI command
(strict pip-audit 2.10.1, one requirement per run, 2026-11-04T19:21Z) found
exactly one more failure: Pillow 12.3.0 with 39 advisories, all fixed in
13.0.0. The other 13 minima report no known vulnerabilities. Reported IDs:

```text
PYSEC-2026-4326 through PYSEC-2026-4343 (18 IDs)
CVE-2026-96638 CVE-2026-96640 CVE-2026-96778
CVE-2026-112390 CVE-2026-112391 CVE-2026-112393 CVE-2026-112395
CVE-2026-112399 CVE-2026-112400 CVE-2026-112401 CVE-2026-112404
CVE-2026-112406 CVE-2026-112891 CVE-2026-112892 CVE-2026-112893
CVE-2026-112894 CVE-2026-112895 CVE-2026-112897 CVE-2026-112899
CVE-2026-112900
GHSA-78g4-xqwv-q3g8
```

Raise installer metadata and the audit targets to `djangorestframework>=3.18.2`
and `Pillow>=13.0.0`. No tox environment pinned either minimum, so no tox
change is needed. Keep both audit jobs and strict failure behavior; no
advisory ignore, skip, continue-on-error or loosened strictness. The
installer-boundary regression rejects DRF 3.17.2/3.18.1 and Pillow 12.3.0 and
accepts the patched releases; those three cases fail against the old metadata.

Pillow 13 is a major release. Metadata check: pillow-heif 1.3.0 to 1.8.1
requires `pillow>=11.1.0`, Wagtail 7.0.9 requires `Pillow>=9.1.0` and
`Willow[heif]>=1.11,<2`. All four `dependency-compatibility` combinations
resolve with Pillow 13.0.0 and DRF 3.18.x. The image, HEIF/AVIF and EXIF tests
pass with Pillow 13.0.0, as do the full suite and the oldest/LTS tox
environments (see the campaign report for counts). DRF 3.17.2 no longer
imports against the Django 6.1.3 that the open ranges now resolve to (missing
`django.utils.cache.cc_delim_re`), so the old floor was also unusable in
practice.

This is point-in-time advisory evidence, not a guarantee about future
disclosures. Application locks retaining earlier DRF or Pillow still need an
explicit refresh and audit. No deployment, package release or cache purge.
