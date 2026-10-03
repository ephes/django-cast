# Django 6.1 advisory-floor CI repair — implemented

CI run [37122375408](https://github.com/ephes/django-cast/actions/runs/37122375408)
on `31f640210815dda9d693ed775420bdc9425cb661` failed only the advisory-floor
audit. At 2026-10-03T12:17:22Z its strict pip-audit 2.10.1 output was:

```text
Found 1 known vulnerability in 1 package
Name   Version ID             Fix Versions
django 6.1.0   CVE-2026-15830 5.2.17,6.0.8,6.1.1
```

The two cache fixes did not change package constraints or audit configuration.
The pre-integration base also admitted/audited 6.1.0. This is a dependency-policy
gap exposed by current advisory data, not an identified cache-code regression.
The resolved-runtime audit passed because it selected a newer version. No
GeoDjango exploit or deployment exposure is claimed. Upstream August security
notes describe the geometry DoS and 5.2/6.0 fixes, but the exact 6.1.1 floor
comes from the actual audit result; do not reinterpret upstream release prose
as evidence that the reported package version is safe.

Exclude 6.1.0 in installer metadata, audit 6.1.1 and align Django 6.1 tox
constraints. Keep both audit jobs and strict failure behavior; no advisory
ignore, skip, continue-on-error or broad branch removal. Add installer-constraint
regressions around patched and vulnerable supported release boundaries. The
6.1.0 case fails before the repair, while patched 5.2/6.0 remain accepted.
Local current-data audit reproduces the vulnerable minimum and verifies its
replacement; this is point-in-time advisory evidence, not a guarantee about
future disclosures. Application locks still need explicit refresh/auditing.

Historical source: [Django August security announcement](https://www.djangoproject.com/weblog/2026/aug/04/security-releases/).
Final integration/validation and hosted run evidence are recorded in the campaign
`cast-ci-repair.md` report; no deployment, package release or cache purge.

The hosted loop stopped at Django, hiding a second failing minimum. Checking
all 15 minima locally then found urllib3 2.7.0 affected by PYSEC-2026-4175,
PYSEC-2026-4176 and PYSEC-2026-4177 (CVE-2026-97687/97688/97689), all fixed
in 2.8.0. Raise installer metadata and its audit target to 2.8.0; the same
boundary test rejects the old pin and retains patched releases. This is a
proven next CI failure, not a broader dependency-refresh campaign. Upstream
advisories: [chunk size](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw),
[deflate](https://github.com/urllib3/urllib3/security/advisories/GHSA-gh4c-6fx4-qh6g),
[HTTPS proxy](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77).
