# M1 acceptance report (PT-15 / GROK-45)

Date: 2026-11-25, America/Chicago. Synthetic data only. This report does not start PT-21, PT-22, or PT-24, and it does not attempt a live Vertex call.

Every claim below is tied to a test in this repository, a CI run of this pull request, or a commit SHA. Where a CI run URL is not yet filled in, the claim refers to the `ci` workflow on the commit that last updated this file (added in a follow-up once the first run exists).

## Count

Acceptance criteria were counted from the Given/When/Then bullets under PRD R1–R16 (`prd.md` lines 66–194, Working Backwards tree, not this repository):

| Requirement | AC count | Milestone |
| --- | ---: | --- |
| R1 | 3 | M1 |
| R2 | 3 | M1 |
| R3 | 2 | M1 |
| R4 | 3 | M1 |
| R5 | 2 | M1 |
| R6 | 2 | M1 |
| R7 | 9 | M1 |
| R8 | 2 | M1 |
| R9 | 3 | M1 |
| R10 | 3 | M1 |
| R11 | 4 | M1 |
| R12 | 3 | M2 |
| R13 | 2 | M1 |
| R14 | 3 | M2 |
| R15 | 2 | M1 |
| R16 | 2 | M1 |
| **Total** | **48** | **42 M1 / 6 M2** |

This matches the ticket and tech-design §7 (PT-15): 42 of 48 in scope; R12 and R14 are M2. The matrix is checked by `tests/test_m1_ac_matrix.py::test_matrix_counts_match_the_prd` and `tests/test_m1_ac_matrix.py::test_every_m1_row_is_pass_with_a_real_test`.

## Result tally

- In scope (M1): 42
- Passing: 42 (each row below lists the proving tests)
- Excluded (M2: R12 × 3, R14 × 3): 6
- Gaps in M1 proofs: none found after writing the two R15 tests listed in the matrix. The export clauses of R3-AC1 and R10-AC2 are not exercisable in M1 because export was deferred (Q7); isolation and Unverified-on-save are proved, and `web/e2e/workspace.e2e.ts::Q7: there is no Export entry in the UI` records that there is no Export UI.

M1 also rejects scans and images with a fixed explanation (`tests/test_upload_api.py::test_r12_scans_and_images_rejected_with_fixed_explanation` and the upload e2e). That is supporting work, not a pass of the M2 R12 ACs.

## AC matrix

Proof cells use `path::test-name`, with multiple proofs separated by ` ;; ` (not a single semicolon, because some test titles contain `; `). Pytest names are function names; Playwright and bun names are the test title strings.<!-- ac-matrix -->
| ID | Requirement | Scope | Proof | Result |
| --- | --- | --- | --- | --- |
| R1-AC1 | Opening the work page and confirming a new case name creates that case and enters its workspace, with no command line or technical configuration. | M1 | tests/test_create_case_api.py::test_create_case_creates_workspace ;; web/e2e/walking-skeleton.e2e.ts::walking skeleton: case -> paste -> evidence -> egress -> save -> reload | pass |
| R1-AC2 | Switching between existing cases shows only the current case's materials, evidence, and drafts. | M1 | tests/test_case_isolation.py::test_r1_ac2_switching_cases_shows_only_current_case_data ;; web/e2e/case-switch.e2e.ts::case switch: each case shows only its own material and evidence | pass |
| R1-AC3 | If the service is not running, the page explains in plain language that the writing workspace is not running on this computer, and tells her to double-click Start Psychtool and reload, or to ask the person who installed it. | M1 | tests/test_ui_copy.py::test_service_not_running_copy_is_byte_exact_with_adr_0023 ;; web/e2e/error-copy.e2e.ts::service not running: plain-language message when the workspace cannot be reached | pass |
| R2-AC1 | An approved .txt or .md upload appears in the case material list and can be used to extract evidence. | M1 | tests/test_upload_api.py::test_r2_ac1_txt_upload_appears_in_list_and_yields_suggestions ;; web/e2e/upload.e2e.ts::upload: R2-AC3 confirmation gate, R2-AC1 .md upload + suggestions, R12 pdf explanation, R2-AC2 unchanged case | pass |
| R2-AC2 | A file over 10 MiB, or a disallowed type, is rejected with a reason and does not partially write. | M1 | tests/test_upload_api.py::test_r2_ac2_oversized_upload_rejected_with_reason ;; web/e2e/upload.e2e.ts::upload: R2-AC3 confirmation gate, R2-AC1 .md upload + suggestions, R12 pdf explanation, R2-AC2 unchanged case | pass |
| R2-AC3 | The first upload of a case requires her confirmation that only synthetic or separately approved materials will be used. | M1 | tests/test_upload_api.py::test_r2_ac3_upload_refused_before_confirmation ;; web/e2e/upload.e2e.ts::upload: R2-AC3 confirmation gate, R2-AC1 .md upload + suggestions, R12 pdf explanation, R2-AC2 unchanged case | pass |
| R3-AC1 | When cases A and B have similar materials, evidence and drafts of A never contain content that can only have come from B. The PRD also mentions export; export is deferred to M2 (Q7), so that clause is not exercisable in M1. Proven here: isolation of materials, evidence, claims, and drafts. | M1 | tests/test_case_isolation.py::test_r3_ac1_similar_materials_never_leak_b_content ;; web/e2e/case-switch.e2e.ts::case switch: each case shows only its own material and evidence ;; web/e2e/workspace.e2e.ts::Q7: there is no Export entry in the UI | pass |
| R3-AC2 | A fact that exists only in the model's general knowledge, not in the case materials, is not presented as a sourced fact. Unsourced generated sentences are marked Unverified. | M1 | tests/test_citecheck.py::test_unsourced_sentence_is_unverified ;; web/e2e/citecheck.e2e.ts::History: unsourced generated sentences are Unverified and the mark survives save and reload | pass |
| R4-AC1 | Each extracted evidence item includes the verbatim quote plus material, version, and paragraph or character range. | M1 | tests/test_evidence_api.py::test_r4_ac1_evidence_items_have_quote_and_range ;; web/e2e/evidence.e2e.ts::R4-AC1 R4-AC2 R4-AC3 evidence items list quote, material, version, paragraph and range; click highlights; both accounts kept | pass |
| R4-AC2 | Clicking an evidence item scrolls to and highlights the exact quote in the source, matching the excerpt. | M1 | web/e2e/evidence.e2e.ts::R4-AC2 click scrolls the source paragraph into view and highlights the exact quote | pass |
| R4-AC3 | Two conflicting accounts of the same matter are both kept, each with its own source, and are never merged into one settled statement. | M1 | tests/test_evidence_api.py::test_r4_ac3_conflicting_accounts_both_kept ;; web/e2e/evidence.e2e.ts::R4-AC1 R4-AC2 R4-AC3 evidence items list quote, material, version, paragraph and range; click highlights; both accounts kept | pass |
| R5-AC1 | A categorized item shows the category name and a short reason (at most two lines) that points at visible source text, not merely 'based on context'. | M1 | tests/test_evidence_categories_api.py::test_r5_ac1_item_shows_category_and_verbatim_reason ;; web/e2e/categories.e2e.ts::R5-AC1 categorized item shows category chip, separate role chip and a reason quoting visible source text | pass |
| R5-AC2 | If the system cannot decide a category, the item is marked Uncategorized, not a guessed category. | M1 | tests/test_evidence_categories_api.py::test_r5_ac2_undecidable_item_is_uncategorized ;; web/e2e/categories.e2e.ts::R5-AC2 undecidable item is Uncategorized, not a guess | pass |
| R6-AC1 | When she changes a category or dimension in one step, the item shows the new label; citing sentences lose their verified state; an approved section returns to Needs review; she does not have to recreate the case or re-upload materials. | M1 | tests/test_evidence_cascade.py::test_r6_ac1_category_change_invalidates_citing_claim_and_section ;; tests/test_evidence_cascade.py::test_r7_ac4_dimension_change_invalidates_citing_claims ;; web/e2e/correction.e2e.ts::R6: category correction shows the server toast, keeps unsaved text, invalidates prepared egress | pass |
| R6-AC2 | If she has unsaved edits when a correction completes, the unsaved text stays and is not silently overwritten or discarded. | M1 | web/e2e/correction.e2e.ts::R6: category correction shows the server toast, keeps unsaved text, invalidates prepared egress | pass |
| R7-AC1 | Dimension names come only from the list she uploaded, not from a built-in official list. | M1 | tests/test_dimensions_api.py::test_r7_ac1_names_come_only_from_her_upload ;; web/e2e/dimensions.e2e.ts::R7-AC1 R7-AC6 dimension group headers equal her list names only, with the disclaimer and no diagnosis language | pass |
| R7-AC2 | If she has not uploaded a list, the case shows the empty state and no dimension is invented from built-in knowledge. | M1 | tests/test_dimensions_api.py::test_r7_ac2_no_list_means_no_dimension ;; web/e2e/dimensions.e2e.ts::R7-AC2 a case without a list shows the empty state and no mapped chips | pass |
| R7-AC3 | A mapped item shows the dimension name, a reason of at most 140 characters quoting visible text, and a clickable source range. | M1 | tests/test_dimensions_api.py::test_r7_ac3_mapped_item_reason_and_source_range ;; web/e2e/dimensions.e2e.ts::R7-AC3 reason quotes visible text and clicks highlight the evidence and list sources | pass |
| R7-AC4 | She can confirm, change, or clear a dimension in one step; a real change cascades as in R6, without re-upload. | M1 | tests/test_dimensions_api.py::test_r7_ac4_change_dimension_in_one_step ;; tests/test_evidence_cascade.py::test_r7_ac4_dimension_change_invalidates_citing_claims ;; web/e2e/dimensions.e2e.ts::R7-AC4 Change to… assigns the new dimension, marks Confirmed by you, and survives reload | pass |
| R7-AC5 | An unsure mapping is marked Needs review and never a guessed dimension. | M1 | tests/test_dimensions_api.py::test_r7_ac5_unsure_mapping_is_needs_review_never_guessed ;; web/e2e/dimensions.e2e.ts::R7-AC5 an ambiguous item shows "Dimension · Needs review" and never a guessed dimension | pass |
| R7-AC6 | No diagnosis-style language appears; every dimension view shows 'This is not a diagnosis. The diagnosis is yours.' | M1 | tests/test_dimensions_api.py::test_r7_ac6_no_diagnosis_language_and_disclaimer_everywhere ;; web/e2e/dimensions.e2e.ts::R7-AC1 R7-AC6 dimension group headers equal her list names only, with the disclaimer and no diagnosis language | pass |
| R7-AC7 | Mapping data never enters sections, drafts, or egress payloads, and never auto-fills a diagnosis or impressions section. | M1 | tests/test_dimensions_api.py::test_r7_ac7_mapping_never_enters_sections_drafts_or_egress | pass |
| R7-AC8 | No criteria text or criterion-number citations appear unless she uploaded that DSM text. | M1 | tests/test_dimensions_api.py::test_r7_ac8_no_criteria_citations_without_uploaded_dsm_text | pass |
| R7-AC9 | A mapping cites only a range from her upload, labelled with its source, and does not add un-uploaded manual paragraphs. | M1 | tests/test_dimensions_api.py::test_r7_ac9_mapping_cites_only_her_uploaded_range_with_source_label | pass |
| R8-AC1 | Clicking evidence or a cited claim fills the right-column source card; the draft editor stays visible and is not covered by a pop-up. | M1 | web/e2e/workspace.e2e.ts::R8-AC1 R8-AC2: clicking evidence or a cited claim fills the right-column source card; the editor stays visible; no invented page | pass |
| R8-AC2 | The source card shows only locations the material really has and never invents a page number. | M1 | web/e2e/workspace.e2e.ts::R8-AC1 R8-AC2: clicking evidence or a cited claim fills the right-column source card; the editor stays visible; no invented page | pass |
| R9-AC1 | A successful generation places unsaved text in the section editor, and each factual sentence can point at the evidence used. | M1 | web/e2e/section-edit.e2e.ts::History: generated text is unsaved, claims stay attached, save survives switch and reload | pass |
| R9-AC2 | After a successful save, reopening the section shows the saved text. | M1 | tests/test_sections_api.py::test_put_section_persists ;; web/e2e/section-edit.e2e.ts::History: generated text is unsaved, claims stay attached, save survives switch and reload | pass |
| R9-AC3 | Diagnosis, impression, and recommendation sections are written only by her: never sent to the model and never auto-filled. | M1 | tests/test_sections.py::test_build_section_request_input_refuses_clinician_authored_sections ;; tests/test_egress_api.py::test_prepare_refuses_clinician_authored_sections_without_writing_egress ;; web/e2e/section-edit.e2e.ts::Clinical Impressions and Recommendations are written by her, never generated | pass |
| R10-AC1 | An unsourced factual sentence in the editor is clearly marked Unverified and does not look like a sourced sentence. | M1 | tests/test_citecheck.py::test_unsourced_sentence_is_unverified ;; web/e2e/citecheck.e2e.ts::History: unsourced generated sentences are Unverified and the mark survives save and reload | pass |
| R10-AC2 | The Unverified mark survives save (and would survive export). The PRD also mentions export; that clause is not exercisable in M1 (Q7). | M1 | tests/test_citecheck.py::test_unsourced_sentence_is_unverified ;; web/e2e/citecheck.e2e.ts::History: unsourced generated sentences are Unverified and the mark survives save and reload ;; web/e2e/workspace.e2e.ts::Q7: there is no Export entry in the UI | pass |
| R10-AC3 | If she marks an Unverified sentence as her own judgment, it is treated as a judgment and is no longer presented as a material fact. | M1 | tests/test_citecheck.py::test_my_judgment_is_preserved_without_evidence ;; web/e2e/citecheck.e2e.ts::History: marking an Unverified sentence as My judgment survives save | pass |
| R11-AC1 | Prepare does not call the model; she is shown the complete outgoing text, the destination, and source versions. | M1 | tests/test_egress_api.py::test_prepare_returns_review_preview_without_calling_transport ;; web/e2e/walking-skeleton.e2e.ts::walking skeleton: case -> paste -> evidence -> egress -> save -> reload | pass |
| R11-AC2 | Sending an unapproved request is refused and the model is not called. | M1 | tests/test_gateway.py::test_send_rejects_unapproved_request_before_transport | pass |
| R11-AC3 | After she separately confirms send, the request is sent only once; success lands unsaved, unapproved text in the editor. | M1 | tests/test_gateway.py::test_send_approved_transports_exact_approved_envelope_once ;; tests/test_gateway.py::test_second_send_is_rejected_before_transport ;; web/e2e/walking-skeleton.e2e.ts::walking skeleton: case -> paste -> evidence -> egress -> save -> reload | pass |
| R11-AC4 | If delivery is uncertain or the output is blocked, there is no same-request retry, and blocked incomplete text is not treated as a usable draft. | M1 | tests/test_egress_api.py::test_output_pii_is_blocked_without_echoing_provider_body ;; tests/test_gateway.py::test_known_name_only_output_is_blocked_and_not_persisted ;; web/tests/egress-state.test.ts::422 and uncertain delivery prohibit same-request retries | pass |
| R12-AC1 | M2: a score from scan recognition must not enter confirmed evidence or the drafting set until she confirms it. Out of M1 scope. M1 only rejects scans and images with a fixed explanation (no server OCR). | M2 | tests/test_upload_api.py::test_r12_scans_and_images_rejected_with_fixed_explanation | excluded (M2) |
| R12-AC2 | M2: an uncertain recognition is marked uncertain and must not auto-fill a 'most likely' complete number. Out of M1 scope. | M2 | — | excluded (M2) |
| R12-AC3 | M2: her corrected number is what enters the evidence list and can be traced back to the page or excerpt. Out of M1 scope. | M2 | — | excluded (M2) |
| R13-AC1 | A paragraph that looks like protected test content (items, norms, or scoring rules) is held back before any write, is not sent to the model, and she is told it cannot be used. | M1 | tests/test_r13_upload.py::test_r13_ac1_upload_blocks_norm_table_paragraph ;; web/e2e/protected.e2e.ts::R13-AC1 norm table paragraph is held back | pass |
| R13-AC2 | When the checker is unsure or fails, the whole upload is rejected (fail-closed). A release or appeal path is Open and is not provided in M1. | M1 | tests/test_r13_upload.py::test_r13_ac2_check_error_rejects_whole_upload | pass |
| R14-AC1 | M2: export of saved drafts and a source index. Out of M1 scope (Q7). | M2 | web/e2e/workspace.e2e.ts::Q7: there is no Export entry in the UI | excluded (M2) |
| R14-AC2 | M2: Unverified sentences remain marked in an export. Out of M1 scope (Q7). | M2 | web/e2e/workspace.e2e.ts::Q7: there is no Export entry in the UI | excluded (M2) |
| R14-AC3 | M2: unsaved text is not exported as a final draft without her knowledge. Out of M1 scope (Q7). | M2 | web/e2e/workspace.e2e.ts::Q7: there is no Export entry in the UI | excluded (M2) |
| R15-AC1 | Until review is complete, the privacy notice is visible on the work page, on upload, and when preparing egress, and cannot be switched off to claim HIPAA compliance. | M1 | tests/test_privacy_copy.py::test_r15_ac1_privacy_banner_constant_is_the_approved_text ;; web/e2e/privacy.e2e.ts::R15: privacy banner stays visible on work, upload and paste surfaces; UI does not claim HIPAA compliance ;; web/e2e/walking-skeleton.e2e.ts::walking skeleton: case -> paste -> evidence -> egress -> save -> reload | pass |
| R15-AC2 | The UI must not claim '符合 HIPAA', 'HIPAA compliant', or '已保护全部患者隐私' (or the equivalent). The approved banner states that the prototype is not HIPAA compliant yet. | M1 | tests/test_privacy_copy.py::test_r15_ac2_shipped_ui_does_not_claim_hipaa_compliance ;; web/e2e/privacy.e2e.ts::R15: privacy banner stays visible on work, upload and paste surfaces; UI does not claim HIPAA compliance | pass |
| R16-AC1 | Once she has opened the work page the agreed way, the flow create case, upload, review evidence, generate and edit a section, and save does not require the command line or technical configuration. Launcher scripts cover starting without the CLI; a real Finder/Explorer double-click is listed under NOT VERIFIED. | M1 | tests/test_launcher.py::test_command_starts_fake_uv_then_opens_browser ;; tests/test_launcher.py::test_command_opens_browser_when_server_already_running ;; web/e2e/walking-skeleton.e2e.ts::walking skeleton: case -> paste -> evidence -> egress -> save -> reload | pass |
| R16-AC2 | Error messages (including offline and save failure) use plain language and say what she can do next. Offline and save-failure use the fixed Q5 wording, and existing editor text stays. | M1 | tests/test_ui_copy.py::test_offline_copy_is_byte_exact_with_tech_design_q5 ;; tests/test_ui_copy.py::test_save_failure_copy_is_byte_exact_with_tech_design_q5 ;; web/e2e/error-copy.e2e.ts::offline: Q5 copy appears and existing editor text stays ;; web/e2e/error-copy.e2e.ts::save failure: Q5 copy appears and the editor text is still there | pass |
|
<!-- /ac-matrix -->

## R7 internal acceptance checklist

This is the internal bar in PRD §5 (mapped items have a reason and a source; unsure items need review; mappings are never written as a diagnosis; no un-uploaded manual text). Dimension correctness is not an external success gate unless the PRFAQ is changed. The developer spot-check script (`scripts/spotcheck.py`) prints pass/fail for the same items on synthetic data; it is not the still-Open PRD §5 product-success gate.

| Checklist item | Proof | Result |
| --- | --- | --- |
| Mapped items have a reason quoting visible text and a source range | `tests/test_dimensions_api.py::test_r7_ac3_mapped_item_reason_and_source_range`; `web/e2e/dimensions.e2e.ts::R7-AC3 reason quotes visible text and clicks highlight the evidence and list sources`; spot-check `R7-MAPPED-REASON` | pass |
| Unsure items are marked Needs review and never a guessed dimension | `tests/test_dimensions_api.py::test_r7_ac5_unsure_mapping_is_needs_review_never_guessed`; `web/e2e/dimensions.e2e.ts::R7-AC5 an ambiguous item shows "Dimension · Needs review" and never a guessed dimension`; spot-check `R7-UNSURE` | pass |
| Mappings are never written as a diagnosis; the fixed disclaimer is present | `tests/test_dimensions_api.py::test_r7_ac6_no_diagnosis_language_and_disclaimer_everywhere`; `web/e2e/dimensions.e2e.ts::R7-AC1 R7-AC6 dimension group headers equal her list names only, with the disclaimer and no diagnosis language`; spot-check `R7-NOT-DX` | pass |
| No un-uploaded manual / criterion-number text | `tests/test_dimensions_api.py::test_r7_ac8_no_criteria_citations_without_uploaded_dsm_text`; `tests/test_dimensions_api.py::test_r7_ac9_mapping_cites_only_her_uploaded_range_with_source_label`; spot-check `R7-NO-MANUAL` and `R7-SOURCE-LABEL` | pass |
| Names come only from her upload; no list means no invented dimension | `tests/test_dimensions_api.py::test_r7_ac1_names_come_only_from_her_upload`; `tests/test_dimensions_api.py::test_r7_ac2_no_list_means_no_dimension` | pass |
| Mapping data never enters sections, drafts, or egress | `tests/test_dimensions_api.py::test_r7_ac7_mapping_never_enters_sections_drafts_or_egress` | pass |

The nine R7 ACs are also rows in the matrix above, all passing.

## Spot-check script

Run from the repository root, with the dev extra (uses a throwaway database; synthetic data only; prints pass/fail; writes no report export):

```bash
uv run --extra dev python scripts/spotcheck.py
```

Proved by `tests/test_spotcheck.py::test_spotcheck_passes_on_synthetic_data`. The ten printed items are `SPOT-SOURCE`, `SPOT-NO-INVENTED`, `SPOT-CATEGORY-REASON`, `SPOT-NO-GUESS`, `SPOT-ISOLATION`, `R7-MAPPED-REASON`, `R7-UNSURE`, `R7-NOT-DX`, `R7-NO-MANUAL`, and `R7-SOURCE-LABEL`.

This script is a developer aid. The classification table, the number of items to spot-check, and the definition of "category correct" remain Open in the PRD / tech-design §8.2 and must not be treated as an automatic product-success gate.

## Verification

Commands were run on this branch and, after the pull request is opened, on a fresh clone. Exact counts and CI URLs belong in the "Verification record" section once those runs finish.

```bash
uv run --extra dev pytest -q
cd web && bun test && bun run build && bun run e2e
uv run --extra dev python scripts/spotcheck.py
```

Screenshot diffs must stay under 2% (masked chrome). Visual regression: `web/e2e/visual.e2e.ts::screenshot diff vs the prototype is under 2% per viewport (masked chrome/layout/theme)`.

## NOT VERIFIED

The following were not verified in PT-15 and must not be read as passing:

### Real desktop launchers

- A real double-click of `launchers/Start Psychtool.command` in macOS Finder, including Gatekeeper and the quarantine attribute.
- A real double-click of `launchers/Start Psychtool.cmd` in Windows Explorer, including SmartScreen.
- Official CI remains ubuntu-only. Alex said he will try a real double-click himself. Scripted launcher coverage is in `tests/test_launcher.py` (see R16-AC1) and is not a substitute for those checks. See ADR 0023.

### Live Vertex chapter

- A live Vertex AI "generate one chapter" check is deferred to PT-24 / GROK-56. This run used FakeTransport only and did not request, create, or use Google Cloud credentials.

### 待验证 items waiting on the psychologist

Grep of the ADRs and of tech-design / PRD (Working Backwards tree):

- **ADR 0021 recommendation-guard word list**, still 待验证. Remaining false-positive candidates, left unchanged by PT-23 pending her ruling: "the results suggest", "should be noted", "advisory", "suggestion".
- **ADR 0023 / tech-design §7 service-not-running copy**, accepted by Alex on 2026-11-25 and added to tech-design §7 as 待验证: "The writing workspace isn't running on this computer. Double-click Start Psychtool, then reload this page. If that doesn't help, ask the person who installed it."
- **tech-design §8.3 / PRD assumptions** (not confirmed with her):
  - The heaviest time sink is pre-work (matching, classifying, checking).
  - She needs DSM-5 dimension mapping (M1 implements it; the need itself is 待验证).
  - She is willing to use a local web app rather than tools already embedded in Q-global.
  - The 50% time-reduction threshold is attainable (baseline unmeasured). Time halved is a success bar, not a measured result.
  - Her materials are mostly copyable text (if they are mostly scans, M1 value drops).
  - The target-user profile in the PRD (a neuropsychologist, as recounted by Alex) is itself 待验证; she has not used psychtool and has not been interviewed.

### Open product questions (not closed by this report)

- R12 quality gate (when OCR is "good enough") remains Open / M2.
- R13 appeal path and the final intercept copy remain Open.
- The classification table, spot-check sample size, and the definition of "category correct" remain a proposal (须她同意).
- PRFAQ / 5CQ items marked 待验证 that repeat the assumptions above.

### Other limits of this run

- No real patient information was used (A-001). All fixtures and the spot-check seed are synthetic.
- Human-approved localhost model calls under `real` were not changed (ADR 0003).
- Windows and macOS CI runners were not added, per the PT-14 answer.
- CLI `export` exists on the file-workspace path (`tests/test_export.py`) but is not the M1 browser export (Q7). This report does not treat those tests as a pass of R14.

## Verification record

### Local working tree (2026-11-25, America/Chicago)

- `uv run --extra dev pytest -q`: **890 passed** (883 on `3a925cc` plus 7 PT-15 tests: 2 spot-check, 3 matrix, 2 privacy-copy).
- `cd web && bun test`: **236 pass / 0 fail**.
- `bun run build`: passed (tsc + vite).
- `bun run e2e`: **33 passed** (32 on `3a925cc` plus `web/e2e/privacy.e2e.ts`). Screenshot diffs: 1440 0.69%, 1280 0.92%, 1024 1.57% (all under 2%).
- `uv run --extra dev python scripts/spotcheck.py`: **10 passed, 0 failed, 10 items**.
- Mutations (each failed as expected, then restored): typo of `R1-AC1`'s pytest name in the matrix; an `is HIPAA compliant` string added to `web/src/App.tsx`; a fabricated evidence quote injected into the spot-check seed.

### Fresh clone

Verified on a clean clone of `0ceba7d` (branch `pt-15-m1-acceptance`), 2026-11-25, America/Chicago:

- `uv run --extra dev pytest -q`: **890 passed**.
- `cd web && bun test && bun run build && bun run e2e`: **236 pass / 0 fail**, build passed, **33 e2e passed**. Screenshot diffs: 1440 0.69%, 1280 0.92%, 1024 1.57% (all under 2%).
- `uv run --extra dev python scripts/spotcheck.py`: **10 passed, 0 failed, 10 items**.

### CI

CI run URLs for the `ci` workflow of this pull request will be added in a follow-up commit once the first GitHub Actions run exists.
