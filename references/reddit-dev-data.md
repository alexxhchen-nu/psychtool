# Reddit as a development research source

Checked 2026-11-08. Reddit posts have **not** been imported into psychtool.

Use public discussion only to identify broad narrative patterns worth testing:
conflicting informants, uncertain onset, missing dates, source attribution, and
irrelevant details. Write entirely new synthetic case materials from these
patterns. Do not copy post text, usernames, URLs, distinctive histories, or
private health details into fixtures or model prompts.

For model evaluation, freeze synthetic inputs and expected claims before a
run. Compare baseline passage suggestions, model-assisted suggestions, and
section generation on source support, omission, attribution, temporal errors,
and cross-case leakage. Model training/fine-tuning is a separate decision.

Reddit's current Data API Terms do not grant a general right to use user
content for training an AI model; its developer guidance also calls for
explicit consent. Re-check these terms before changing the dataset policy.

- https://redditinc.com/policies/data-api-terms
- https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data
