# Identifier redaction (Safe Harbor de-identification)

Status: implemented as a standalone, reusable module. Not a claim of HIPAA
compliance and not legal advice; see `privacy-research.md` and `hhs-sources.md`
for the source evidence and its limits.

## What is implemented

`psychtool/core/redact.py` is the de-identification engine. It is deliberately a
self-contained tool (stdlib `re` only, no network, no persistence) so it can be
reused by the draft prompt builder, the eval hard gates, and any future
import/export surface. Three entry points:

- `redact_text(text, *, known_names=()) -> (redacted, token_map)` — replaces
  identifiers with semantic tokens like `[[TELEPHONE_1]]` and returns the
  reversible mapping to its immediate caller.
- `restore_text(text, token_map)` — a local utility that can reverse tokens when
  a caller deliberately retains a map; the strict model-egress path does not
  call it after generation.
- `find_identifiers` / `gate_pii` — output-side re-identification scan.

Current model wiring is the strict runner path. It first assembles the final,
complete prompt—including selected claims, metadata, and instructions—and then
`prepare_egress_request` redacts that complete string using the workspace's
known names. The token map is used only during that prepare call to derive the
identifier categories; it is discarded rather than persisted across the
prepare/approve/send phases. The persisted envelope and the model therefore
contain semantic tokens, not the original values.

The CLI and API do not expose a switch that bypasses this prepare-stage
processing for `real` requests. The first-version model response keeps semantic
tokens and is subject to the output identifier gate, including workspace known
names; generated text is not
automatically restored to original identifying values. `eval.run_case` also
reports its output `pii` gate and folds it into `blocked`.

## Model-egress boundary

Every model call now prepares the complete outbound envelope before approval.
The workspace request record is the review preview: it includes the exact
redacted messages, provider/model routing, purpose, data tier, source versions,
and identifier categories. Its canonical SHA-256 hash covers all of that
approval-relevant content. Lifecycle metadata (status, reviewer, approval
reason, and timestamps) is excluded so a state transition does not change the
approved hash. Any envelope, routing, source-version, or data-tier change
requires a newly prepared and approved request.

Redaction happens before the request record is persisted. The reversible token
map remains in memory only: it is not included in the preview, hash input,
security events, or any persisted request. API keys are likewise excluded.
Ordinary security-event serialization uses an explicit allowlist of request ID,
hash, purpose, tier, provider/model, identifier categories, status,
`reviewer_fingerprint` (lowercase SHA-256 of the approval record's reviewer),
timestamps, and a fixed error category. It excludes free-text reviewer identity,
envelope message content, response bodies, identifier values, token maps, and
API keys.

Approval is an additional control, not a replacement for endpoint policy:
`real` remains restricted to local endpoints and requires human approval for
each request; `synthetic` network use requires an explicit `synthetic_auto`
approval and reason (or human approval). Both approval modes validate the caller's
preview hash under the request transition lock. Claim freshness also checks the
claim's underlying material version before sending. Transport exceptions can
occur after delivery, so they retain the send lock and block repeat sends; no
automated recovery is provided. This request gate, regex redaction, and logging
allowlist reduce exposure but do not establish HIPAA compliance.

## The 18 Safe Harbor categories (45 CFR 164.514(b))

`SAFE_HARBOR_18` in `psychtool/core/redact.py` encodes the complete list:

1. Names
2. Geographic subdivisions smaller than a state (street, city, county, precinct, ZIP)
3. Dates (other than year) directly related to an individual, and ages over 89
4. Telephone numbers
5. Fax numbers
6. Email addresses
7. Social Security numbers
8. Medical record numbers
9. Health plan beneficiary numbers
10. Account numbers
11. Certificate/license numbers
12. Vehicle identifiers and serial numbers
13. Device identifiers and serial numbers
14. Web URLs
15. IP addresses
16. Biometric identifiers (finger/voice prints)
17. Full-face photographs and comparable images
18. Any other unique identifying number, characteristic, or code

## Detection coverage and honesty

The engine is regex-based, so it covers only machine-detectable categories.
`name` is detected only from the caller-supplied `known_names` list;
`biometric_identifier` and `full_face_photo` are binary media and are not in
plain text; `other_unique_identifier` is context-dependent. These are documented
as out of scope for automatic text redaction and must be supplied externally
(named-entity recognition, image/audio analysis, or a caller allowlist).

## Rules the engine must not silently drop

- ZIP codes: only the first three digits may be retained, and only when the
  geography has more than 20,000 people per the most recent census.
- Dates: keep the year; strip month/day.
- Ages: 89 and under may stay; 90 and over must be grouped as "90 or older".
- Free text: identifiers must be removed wherever they are recognizable, not
  just from structured fields.
- "Actual knowledge": if the holder knows the remainder could re-identify the
  individual, Safe Harbor does not apply regardless of the scan.
- The token map is reversible by design, but the strict model-egress path does
  not retain it for reconstruction; it must never be sent to a model or
  persisted alongside PHI.

## Extension point

Append a `(kind, regex)` tuple to `_PATTERNS` in `psychtool/core/redact.py` to
teach the engine a new category without touching call sites. Order matters:
most distinctive patterns (SSN before telephone) run first.

## Sources

- HHS-002 (authoritative): Methods for De-identification
  https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html
- HHS-001 (cloud/BAA): Guidance on HIPAA & Cloud Computing
  https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html
- HIPAA Journal (secondary, AI-focused):
  https://www.hipaajournal.com/hipaa-healthcare-data-and-artificial-intelligence/
  and https://www.hipaajournal.com/de-identification-protected-health-information/
