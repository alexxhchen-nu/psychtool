# Web Egress Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: executing-plans or subagent-driven-development. Execute the bounded components with one integration owner.

**Goal:** Complete upload → claim review → prepare → exact preview approval → single send → explicit section save in the existing Web app.

**Architecture:** Keep the current visual system and FastAPI contracts. Extract shared TypeScript types/API helpers; isolate upload and request review components. Key the workspace and section editor by their identities to prevent asynchronous results crossing cases or sections. Disable context changes during mutations and preserve unsaved editor content when refreshing claims/materials.

**Tech Stack:** React 19, TypeScript, Vite, Bun tests; existing FastAPI and Python tests.

**Spec:** `docs/superpowers/specs/2026-11-08-web-egress-workbench-design.md`

## Global Constraints

- No new UI framework; preserve paper/forest visual system.
- Only synthetic/public development materials. No compliance or authentication claims.
- Prepare must whitelist template_id, template_version, section_id, claim_ids, instructions, purpose; never route/redact/source refs.
- Approve binds exact server content_hash; approval and send are separate clicks.
- sessionStorage stores request ID only. Include template/version in key to avoid cross-template collisions.
- 422 output block and 502/unknown delivery never offer same-request resend. Recovery GET cannot recover output text; say so.
- Generated text becomes an unsaved draft requiring fresh section review, including when replacing previously approved content.
- Known names reach the local Web server; auto-detection is incomplete and never establishes HIPAA compliance.

## Review Focus

- Async operations completing after context changes: keyed components plus synchronous in-flight guard; late output cannot enter another editor.
- Refresh after send-start: remove resumable request ID before POST so reload cannot restore a send button for an uncertain request; remain fail-closed if storage cannot remove.
- Changing selected claims while reviewing: invalidate local request readiness and require Prepare again; retain terminal send outcomes.
- Updating materials/claims must refresh lists without resetting unsaved section text.
- Raw API errors may contain input values: fixed safe messages only; never render server detail or blocked body.

### Task 1: Shared contracts and API
**Files:** `web/src/types.ts`, `web/src/api.ts`.
- [x] Extract existing DTOs; add exact upload/egress response types from backend.
- [x] Provide encoded workspace URLs and typed request helpers with safe status-only errors.
- [x] Whitelist prepare and approval bodies; multipart upload lets the browser set the boundary.

### Task 2: Material upload
**Files:** `web/src/components/MaterialUploadPanel.tsx`, `web/src/upload.ts`, `web/tests/upload.test.ts`.
**Interface:** props workspaceId, onUploaded(result), onReview(materialId), onBusyChange(busy).
- [x] Validate anonymous slug, .txt/.md/.pdf/.png/.jpg/.jpeg, <=10 MiB; visible labels for file/title/provider/date.
- [x] Upload once; display version, passage count and category-only findings, plus manual-review reminder.
- [x] Refresh material list and hand selected material to intake; retain user input on failure.
- [x] Cover size/type/slug boundaries; verify with actual browser upload.

### Task 3: Staged request review
**Files:** `web/src/egress-state.ts`, `web/src/components/EgressReviewPanel.tsx`, `web/tests/egress-state.test.ts`.
**Interface:** props workspaceId, templateId, templateVersion, sectionId, sectionTitle, claimIds, sourceRevision, onGenerated(text, claimIds), onBusyChange(busy), disabled.
- [x] Pure reducer gates approve/send and handles stale, output-blocked, uncertain, sent states.
- [x] Component owns prepare/recover/approve/send; show exact preview, full hash, provider/model/tier, source refs and categories.
- [x] Reviewer + confirmation for real; explicit synthetic reason + confirmation for synthetic.
- [x] Synchronous busy guard, safe storage access and alive/generation guard. Clear resumable ID before send; same-request send never retried after uncertain delivery.
- [x] Tests cover illegal transitions, 400 recoverable approval, 403 policy denial, 409 invalidation, 422/502 terminal safety and recovery restrictions.

### Task 4: Integration and verification
**Files:** `web/src/App.tsx`, `web/src/App.css`, `WORKLOG.md`, spec status and implementation notes.
- [x] Remove retired generation calls and duplicate Generate buttons; integrate request panel and explicit save.
- [x] Integrate upload, refresh claims/materials, clear stale suggestions on selection changes, fixed safe errors and names explanation.
- [x] Run Bun tests/build and Python suite. Browser exercise synthetic and real local-test-provider flow, restoration, explicit-save boundary, stale and blocked/uncertain outcomes, desktop/mobile and keyboard.
- [x] Record actual checks and environmental limits; implementation committed and pushed as `f12ec40`.

## Execution decision

The user requested resume after the next-step workbench proposal. Proceed with the existing design and current checkout; no new worktree or unrelated backend changes. UI keeps its existing English product language; user-facing progress reports remain Chinese. The pending spec's `empty → draft` example is tightened to always reset generated replacement content to draft, because carrying prior approval to new text would be misleading.
