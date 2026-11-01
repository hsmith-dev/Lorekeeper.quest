---
status: final
created: 2026-10-31
workflow: bmad-create-epics-and-stories, step 4 (final validation), autonomous
document: _bmad-output/planning-artifacts/epics.md
result: PASS (all checks pass after the merge fixes)
---

# Epics validation report

**Result: PASS.** All step-4 checks pass on the merged `epics.md` (19 epics, 155 stories: 154 from the batches plus the optional E0-Access.14). The raw batch outputs failed three checks: one forward dependency, one 23-story dependency cycle, cross-batch dependencies in B2 and B3 written as contract names instead of story ids, and wrong story ids that the dependency checks couldn't catch. Each failure was fixed in `epics.md` and is listed under "Fixes made". The checks are scripted: they parse every story's `Dependencies` line, build the graph, sort it topologically and search the story text for each requirement id.

| Check | Raw batches | Merged `epics.md` |
| --- | --- | --- |
| Requirement ids covered by at least one story | 158 / 158 | **158 / 158** (27 AR, 15 CI, 5 DS, 6 EV, 55 FR, 1 LIC, 11 NFR, 6 SPIKE, 32 UX-DR) |
| Stories with As a / I want / So that, Given/When/Then ACs and a Covers line | 154 / 154 | **155 / 155** |
| Dependency ids that don't resolve to a story | 0 among parsable ids, but B2/B3 cross-batch dependencies were contract names; the raw parse found 426 edges against 559 after the merge | **0** |
| Forward dependencies inside an epic | 1 (E0-LLM.2 → E0-LLM.5) | **0** |
| Dependency cycles | 1 cycle through 23 stories (E0-LLM.2–.6, E4.5–E4.11, E5.1/.2/.5–.7, E6.2–E6.7) | **0** (Kahn topological sort over 559 hard edges) |
| Cross-epic dependencies that don't point backward in the build DAG | not checkable (missing edges) | **0** (against the plan §4 DAG plus amendments A-1 to A-3) |
| Stories not session-sized | 0 (S 25, M 99, L 30, no XL) | **0** (S 26, M 99, L 30, no XL) |
| Wrong cross-batch story ids (manual check) | 13 references in B4, 3 in B6, 1 in B1 | **0** |

## 1. FR coverage

Every FR, NFR, UX-DR, AR, CI, EV, DS, SPIKE and LIC id in the Requirements Inventory appears in at least one story's text, and in each case the epic-level FR Coverage Map agrees. The table lists the covering stories for FRs and NFRs (the first six, then a count).

| Req | Stories |
| --- | --- |
| FR-1 | E0-Jobs.1, E0-Jobs.2, E0-Jobs.3, E0-Jobs.4, E0-Jobs.5, E1.8 (+2) |
| FR-2 | E0-Jobs.6, E0-Jobs.7, E0-Jobs.9, E0-Jobs.10, E0-UX.5 |
| FR-3 | E1.2, E1.10, E0-LLM.1, E0-LLM.4 |
| FR-4 | E0-WorldCore.2, E0-WorldCore.4, E0-WorldCore.5 |
| FR-5 | E0-Access.14, E0-WorldCore.2, E0-WorldCore.5, E0-WorldCore.6, E0-WorldCore.7, E0-WorldCore.10 |
| FR-6 | E0-Journal.2, E0-Journal.3, E0-Journal.4, E0-WorldCore.8, E1.3, E7.3 |
| FR-7 | E0-Access.1, E0-Access.2, E0-Access.4, E0-Access.6, E0-Access.10, E0-Access.12 (+2) |
| FR-8 | E0-QA.13, E0-Access.2, E0-Access.3, E0-Access.4, E0-Access.5, E0-Access.6 (+13) |
| FR-9 | E0a.1, E0a.2, E0-QA.13, E0-QA.14, E0-Access.1, E0-Access.4 (+4) |
| FR-10 | E0-Access.13, E8.1, E8.4, E9.1 |
| FR-11 | E0-WorldCore.1, E0-WorldCore.5, E0-WorldCore.10 |
| FR-12 | E0-WorldCore.7, E0-WorldCore.11, E1.2, E1.7 |
| FR-13 | E1.2, E1.3 |
| FR-14 | E0-WorldCore.4, E1.2, E1.4, E1.5, E1.10 |
| FR-15 | E1.1, E1.3, E1.4, E1.5, E1.6, E1.7 |
| FR-16 | E0-WorldCore.3, E0-WorldCore.5, E0-WorldCore.11, E1.4 |
| FR-17 | E0-WorldCore.9, E0-WorldCore.11 |
| FR-18 | E0-Jobs.5, E1.1, E1.3, E1.8 |
| FR-19 | E2.2, E2.3, E2.4 |
| FR-20 | E2.3, E2.4 |
| FR-21 | E2.1, E2.2, E2.5 |
| FR-22 | E2.6 |
| FR-23 | E3.1, E3.3 |
| FR-24 | E3.2, E3.4, E3.5, E3.6 |
| FR-25 | E3.2, E3.3, E3.4, E3.5 |
| FR-26 | E4.1, E4.2, E4.3, E4.4, E4.9 |
| FR-27 | E4.5, E4.9 |
| FR-28 | E4.6 |
| FR-29 | E0-LLM.3, E4.2, E4.7, E4.11 |
| FR-30 | E4.10, E4.11 |
| FR-31 | E5.1, E5.2 |
| FR-32 | E5.4, E5.5, E5.6 |
| FR-33 | E5.3, E5.4, E5.6 |
| FR-34 | E7.1, E5.1, E5.5, E5.6 |
| FR-35 | E6.2, E6.3 |
| FR-36 | E6.1, E6.2, E6.4, E6.5, E6.6, E6.7 |
| FR-37 | E6.2, E6.3, E6.6 |
| FR-38 | E6.4 |
| FR-39 | E6.7 |
| FR-40 | E7.1, E7.2, E7.4, E7.9, E3.2, E3.4 |
| FR-41 | E0-Access.9, E7.6, E7.7, E5.5, E8.4 |
| FR-42 | E1.3, E7.3, E7.8 |
| FR-43 | E0-QA.14, E0-Access.7, E0-Access.8, E7.5 |
| FR-44 | E0-Access.10, E0-Access.12, E7.4 |
| FR-45 | E8.1, E8.2, E8.3, E8.4, E8.5 |
| FR-46 | E8.2, E8.3 |
| FR-47 | E8.4, E8.5 |
| FR-48 | E8.1, E8.4, E8.5 |
| FR-49 | E9.1, E9.4 |
| FR-50 | E9.2, E9.3, E9.4, E9.5 |
| FR-51 | E9.2, E9.3, E9.4, E9.5 |
| FR-52 | E10.1, E10.2, E10.4, E10.5 |
| FR-53 | E10.3, E10.4, E10.5, E10.6 |
| FR-54 | E10.1, E10.3, E10.4 |
| FR-55 | E1.5, E10.7 |
| NFR-1 | E0-QA.12, E0-Platform.1, E0-Platform.3, E0-Platform.4, E0-Platform.5, E0-Platform.7 (+9) |
| NFR-2 | E0-QA.15, E0-Platform.4, E0-Platform.6, E0-Platform.7, E0-Platform.10, E4.5 (+3) |
| NFR-3 | E0-Platform.2, E0-Platform.3, E0-Platform.4, E0-Platform.5, E0-Platform.6, E4.2 (+1) |
| NFR-4 | E0-QA.2, E0-QA.6, E0-QA.7, E0-QA.8, E0-QA.9, E0-Platform.2 (+7) |
| NFR-5 | E0-QA.11, E0-QA.13, E0-QA.14, E0-Access.13, E0-Access.14, E0-Platform.1 (+23) |
| NFR-6 | E0-QA.15, E0-Platform.10, E1.3, E1.10, E2.3, E2.7 (+10) |
| NFR-7 | E0-Access.8, E0-WorldCore.3, E1.2, E1.4, E2.1, E2.2 (+9) |
| NFR-8 | E0-QA.4, E0-QA.5, E0-QA.6, E0-Access.1, E0-Platform.8, E0-Platform.9 (+7) |
| NFR-9 | E0-Jobs.2, E0-Jobs.3, E0-Journal.1, E0-Journal.2, E1.3, E1.7 (+3) |
| NFR-10 | E0-Jobs.10, E0-Journal.4, E0-WorldCore.10, E0-WorldCore.11, E1.5, E1.6 (+27) |
| NFR-11 | E0-Jobs.5, E1.8 |

The checklist's AC-completeness review was sampled, not exhaustive: every FR listed above was checked for at least one story that names it in `Covers` **and** has an AC exercising it. Cuttable FRs (FR-30, FR-39, FR-50, FR-51, FR-55) each sit in their own stories (E4.10/E4.11, E6.7, E9.2/E9.3/E9.5, E10.7), so a cut never removes part of a story.

## 2. Architecture implementation

- **Starter template:** none. This is a brownfield expansion, and the spine names no starter, so there is no "set up from template" story.
- **Tables created when first needed:** yes, with two deliberate exceptions fixed by AD-19. F2-jobs-files creates `jobs`, `data_backfills`, `stored_files` and `derived_sources` in one revision (E0-Jobs.1, B2 Decision 9), and F3-world creates the seven World Model tables in one revision (E0-WorldCore.2). Every feature table is created by the first story that needs it (E1.1, E2.1, E4.1, E4.2, E5.1, E6.1, E9.2, E9.3, E10.1, E10.3). Later columns arrive with the story that needs them (E4.11 `live_segments.speaker`, E0-WorldCore.7 unique index).
- **One owner per table:** each table has one owning epic in the spine boundary map plus "Boundary map additions" in `epics.md`. `user_settings` is an existing table, and E9 owns only its two new columns.

## 3. Story quality

- Every story has the template's user story and Given/When/Then ACs, a `Covers` line naming requirement ids, technical notes, `Dependencies` and a `Size`.
- Session sizing: no story is XL. The 30 L stories were each checked to stay within one context (one route file, or one table set plus its service). The batches had already split oversized estimates: E0-Access 8 → 13, E0-QA 7 → 15, E0-Platform 6 → 10, E0-Jobs 6 → 10, E4 7 → 11 and E6 5 → 7.
- Forward dependencies: none (section 5).
- Done stories (E0a.1, E0-QA.1, E0-QA.2, E0-QA.3) keep their ids for traceability and are marked `done` in `sprint-status.yaml`.

## 4. Epic structure

- **User value:** every epic title and goal is a user outcome, including the foundation epics (D-2). E0-QA, E0-Platform, E0-Jobs and E0-LLM are platform outcomes ("trustworthy merges", "runs offline in 16 GB", "Jobs with visible progress", "reliable local LLM"). They are kept separate because the spine's boundary map and CI's table-owner check depend on that split.
- **File churn:** the files that more than one epic edits are listed in `epics.md` "Boundary map additions › Files more than one epic edits". Every case is an additive mount, a one-line registration or a class-only change (B3-D16, B4-D4, B4-D9, B6-6). No core file is restructured by two epics, so consolidating epics isn't warranted. The repeated touches on `campaigns.py` (E0-Access, then E8.1/E9.1 delegations) are intentional: E0-Access fixes the FR-10 scope first and the feature epics then move the bodies into their services.
- **Epic independence:** after Phase 0, each feature epic works without the others. The only hard cross-lane edges are E1 → E2 (7 edges, by design: E2 is lane A after E1), E1 → E7.8 (promotion; E7.8 is the last E7 story and soft for E7.9), E1.5 → E10.7 (FR-55, cut 2), and E7.1 → E3.4, E5.6, E9.5 and E10.4 (Portal slot registry, amendment A-2). E7.1 needs only Phase 0, so these don't couple lanes in time.

## 5. Dependency validation

Method: each story's `Dependencies` value was parsed for story ids, with text after "Soft:" and "Consumers" excluded. That gives 559 hard edges over 155 nodes, sorted with Kahn's algorithm. The longest chain is 26 stories. Allowed cross-epic predecessors follow `epics-parallel-plan.md` §4: Wave 0 roots (E0a, E0-QA substrate, E0-Platform, E0-UX, E0-LLM) → E0-Access → E0-Jobs → E0-Journal → E0-WorldCore → Phase 0 exit → feature lanes, with E1 → E2, E1 → E7/E10. The EV-4 probe stories E0-QA.13/.14 may follow E0-Access and E0-LLM (the plan's EV-4 node). Amendments A-1 to A-3 are recorded in `epics.md`.

- Within-epic forward dependencies: **0**.
- Cross-epic dependencies not pointing backward: **0**.
- Cycles: **0**.
- Unresolved ids: **0**.

## Fixes made

1. **Contract names → story ids (RC-30).** Every cross-batch dependency in B2 and B3 now names real stories, with the contract in brackets. Together with fix 5, this takes the graph from 426 to 559 hard edges.
2. **Guessed ids remapped (RC-19, RC-20, RC-21).** B4: E0-WorldCore.4 → .5, .8 → .10, E0-LLM.1 → .2, E1.2/E1.4 → E1.3/E1.4/E1.7. B6: E0-LLM fake → .5, gate → .2, budget → .3. B1: "E0-LLM fake provider (B5)" → E0-LLM.5.
3. **Cycle and forward dependency removed (RC-31).** Prose in E0-LLM.2, E0-LLM.5, E0-LLM.6 and E5.5 Dependencies lines named consumers or later stories, which closed a 23-story cycle (E0-LLM.5 "Consumers: E0-QA.14" against E0-QA.14 → E0-LLM.5) and one forward dependency. The prose is now labelled "Consumers" or "Soft:".
4. **Missing owner capabilities added as ACs (RC-1 to RC-18).** Covers `depends_on_job_id`, the `data_backfills` runner, `put_tree`, error codes and gate class, `as_system`/`ctx_for`, the preview header, `DERIVED_REGISTRY` non-file types, `narrative_only`, `register_resolver`, `mark_dependents_stale` plus the `visibility_floor` exception, the enum name clash, the `hostile` flag, the World tabs registry and preview overflow, promotion extraction, Portal sections and the Keepsakes shell. The full table is in `epics.md` "Cross-batch contract reconciliation".
5. **Hidden ordering made explicit.** E5.6, E9.5 and E10.4 now depend on E7.1 (Portal registry), E0-WorldCore.5 on E0-Access.8 (resolver), E0-Journal.2 on E0-Access.7 (`index_party_fields`), E0-Jobs.3 on E0-LLM.1/.2, and E7.6 on E0-WorldCore.10.
6. **Optional story added:** E0-Access.14 (OD-1 option B), marked pending owner decision, with a conditional AC in E0-WorldCore.2.

## Open items (not blocking)

- **OD-1** legacy NPC/Quest visibility during the upgrade gap. Option A is the default; option B is E0-Access.14. Owner to decide.
- **OD-2** GPU image redistribution under the NVIDIA EULA; **OD-3** confirming the licence exceptions (E0-QA.9, an owner action).
- NFR-6 targets and §7 numbers stay provisional until the x86 re-run (E0-QA.15, E0-Platform.10; D-8).
- `epics-parallel-plan.md` §4 isn't edited. Amendments A-1 to A-3 live in `epics.md`, and `build-waves.md` applies them.

## Workflow close

All checks pass, so the autonomous run chose [C] Complete and set `epics.md` `status: final`. Next: `bmad-sprint-planning` (done, see `_bmad-output/implementation-artifacts/sprint-status.yaml`), then `bmad-build` on wave 1 of `build-waves.md`.
