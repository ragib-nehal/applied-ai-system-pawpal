# Phase 2 Cleanup — Removal Plan

_Authored 2026-04-29. Companion to the `CLEANUP BACKLOG` block at the top of `backend/pawpal_backend/services/legacy_scheduler.py` and the `LEGACY_ARCHIVE` markers throughout it._

This plan describes how to convert the 12 soft-deactivated symbols in `backend/pawpal_backend/services/legacy_scheduler.py` into full deletions. Read this together with the `CLEANUP BACKLOG` block in source — that block is the live registry; this document is the procedure.

## 1. Calibration

The original framing called for deleting "Tier A" blocks. Per Task 4's classification, **this batch has zero Tier A items** — every one of the 12 archived symbols is referenced by `docs/Mermaid.js` (the UML class diagram), which makes them all Tier B. So this plan covers two phases, not one:

- **Phase 1: B → A** — strip the UML reference (the only external consumer) so the symbol becomes a true Tier A.
- **Phase 2: A → deleted** — apply the three gates (no new callers / replacement covered by tests / roadmap final), then delete.

Nothing in this batch is currently eligible for Phase 2; everything must transit Phase 1 first.

## 2. Phase 1 procedure (B → A)

For each Tier B symbol (or cohort, see §5), in a single small PR:

1. Delete the symbol's row from `docs/Mermaid.js` (UML class diagram).
2. Move its line in `backend/pawpal_backend/services/legacy_scheduler.py`'s `CLEANUP BACKLOG` block from the Tier B list up into Tier A.
3. Update its inline header from `(Tier B)` to `(Tier A)`. Drop the `Last consumer: docs/Mermaid.js:<line>` line; replace with `Last consumer: none (UML reference removed in <commit-sha>)`.
4. Run `pytest test/`, `python3 main.py`, and the AppTest smoketest.

Phase 1 is also where **Gate 3 (roadmap finality) gets logged.** The PR description should record the sign-off, e.g. _"Confirmed with @ragibn that owner preferences/constraints will not return to the roadmap."_ Once a row is in Tier A, Gate 3 is considered satisfied.

## 3. Phase 2 — the three deletion gates

### Gate 1 — No new call sites have appeared

Single sweep at the start of each deletion PR; no CI guardrail needed for a project this size.

```bash
git grep -nE \
  "get_energy_level|add_special_need|display_info|\.preferences\b|\.constraints\b|set_preference|is_available|is_feasible|\.generate_schedule\b|resolve_conflict|is_overbooked" \
  -- '*.py' '*.md' 'docs/'
```

Restricted to symbols still archived at sweep time. Expected output: zero hits outside `backend/pawpal_backend/services/legacy_scheduler.py` itself. Any hit halts the deletion and triggers a root-cause sweep.

### Gate 2 — Tests cover replacement behavior

| Archived symbol | Replacement | Existing coverage | Action before delete |
|---|---|---|---|
| `Pet.get_energy_level` | direct field `pet.energy_level` | every test reads the field | none |
| `Pet.add_special_need` | `pet.special_needs.append(…)` | trivial list op; not test-worthy | none |
| `Pet.display_info` | Streamlit field rendering | AppTest smoketest exercises it | none |
| `Owner.preferences` / `.constraints` / `.set_preference` / `.is_available` | feature scoped out — no replacement | n/a | none |
| `Owner.__init__` preferences/constraints state | kwargs accepted but ignored | not asserted today | optional: 1-line test that `Owner(name='x', available_time_per_day=60, preferences={'k':1}, constraints=['x'])` does not raise |
| `Schedule.is_feasible` | `len(owner_scheduler.detect_time_conflicts()) == 0` | `test_no_conflict_*`, `test_conflict_detected_*` | none |
| `Scheduler.generate_schedule` | `OwnerScheduler.generate_consolidated_schedule` | all four `OwnerScheduler` tests | none |
| `OwnerScheduler.is_overbooked` | `len(detect_time_conflicts()) > 0` | `test_conflict_detected_when_pets_exceed_daily_limit` | none |
| **`OwnerScheduler.resolve_conflict`** | **drop-list pattern via `get_dropped_tasks()`** | **GAP** — `get_dropped_tasks` is never directly asserted; existing test only checks the _absence_ of the dropped task in `get_daily_summary` | **add `test_get_dropped_tasks_reports_skipped_tasks_when_over_budget`** (see §4) |

### Gate 3 — App roadmap confirms deprecation is final

Bundled into Phase 1 PRs as described in §2. By the time an item reaches Tier A, this gate is already passed.

## 4. Required new test (Gate 2 prerequisite for the OwnerScheduler cohort)

Drop into `test/test_pawpal.py` near the existing conflict tests:

```python
def test_get_dropped_tasks_reports_skipped_tasks_when_over_budget():
    """Tasks that don't fit the shared daily budget should appear in get_dropped_tasks()."""
    owner = make_owner(minutes=60)
    pet1 = Pet(name="Buddy",    species="Dog", age=3, energy_level="high")
    pet2 = Pet(name="Whiskers", species="Cat", age=5, energy_level="low")
    owner.add_pet(pet1)
    owner.add_pet(pet2)
    tasks_per_pet = {
        "Buddy":    [make_task(title="Walk", duration_minutes=40, priority="high")],
        "Whiskers": [make_task(title="Feed", duration_minutes=40, priority="low")],
    }
    os_ = OwnerScheduler(owner, [pet1, pet2], tasks_per_pet)
    os_.generate_consolidated_schedule()
    dropped = os_.get_dropped_tasks()
    monday_drops = dropped.get("Monday", [])
    assert len(monday_drops) == 1
    assert monday_drops[0]["pet"] == "Whiskers"
    assert monday_drops[0]["task"].title == "Feed"
```

This makes the drop-list contract explicit and unblocks the Cohort-D deletion below.

## 5. Deletion cohorts (Phase 2 batching)

Ordered low-risk first. Each cohort = one PR.

| # | Cohort | Symbols | Risk | Notes |
|---|---|---|---|---|
| **B** | Pet legacy helpers | `Pet.get_energy_level`, `Pet.add_special_need`, `Pet.display_info` | low — no replacement needed; pure dead code | smallest cohort, do first |
| **C** | Single-pet scheduler entry point | `Scheduler.generate_schedule` | low — superseded path, isolated | the `Scheduler` class itself stays alive (its helpers are still used by `OwnerScheduler`) |
| **D** | Stale conflict-resolution surface | `Schedule.is_feasible`, `OwnerScheduler.is_overbooked`, `OwnerScheduler.resolve_conflict` | medium — depends on §4 test landing first | block on Gate 2 test from §4 |
| **A** | Owner preferences/constraints feature | `Owner.preferences`, `Owner.constraints`, `Owner.set_preference`, `Owner.is_available`, **and** the `preferences=`/`constraints=` kwargs from `Owner.__init__` | **breaking** to the constructor signature | run last; commit body + CHANGELOG note required; this is the one cohort where a downstream caller passing `preferences=...` would now `TypeError` |

Cohort A's blast radius is the largest — removing the kwargs is API-breaking even though the kwargs are currently no-ops. Acceptable for an internal/course project; flag in the PR.

## 6. Per-cohort deletion checklist (template)

```
PHASE 2 DELETION — Cohort <X>
Symbols: <list>

Preconditions (all must pass before merging):
[ ] All symbols in this cohort are in Tier A (UML rows already removed)
[ ] Gate 1: git grep sweep returns zero hits outside legacy_scheduler.py
[ ] Gate 2: replacement tests listed and green:
      - <test_name_1>
      - <test_name_2>
[ ] Gate 3: roadmap sign-off recorded in the originating Phase-1 PR

Deletion steps:
[ ] Delete each NotImplementedError stub method
[ ] Delete the LEGACY_ARCHIVE_START/END block above each
[ ] Remove the corresponding rows from CLEANUP BACKLOG (top of legacy_scheduler.py)
[ ] If CLEANUP BACKLOG is now empty, delete the entire header block
[ ] Verify pytest: <N>/<N> passing
[ ] Verify main.py runs end-to-end
[ ] Verify Streamlit AppTest smoketest passes
[ ] Commit body lists every deleted symbol; flag breaking changes if any
```

## 7. Stop conditions

- **Gate 1 fails** (a new caller surfaced) → don't delete. Either reactivate the symbol from its `LEGACY_ARCHIVE` body, or refactor the caller to use the replacement.
- **Gate 2 fails** (replacement test red or missing) → write/fix the test in a separate PR before the deletion PR.
- **Gate 3 reverses** (a feature comes back onto the roadmap) → reactivate from the archived body, restore the UML row, drop from the cleanup backlog. Do this before any deletion PR proceeds.

---

**TL;DR:** No item in this batch is delete-eligible yet because the UML still references all 12. Strategy: do small B→A PRs (which double as the roadmap sign-off step), batch the Phase-2 deletions into 4 cohorts ordered B→C→D→A, and add one new test (`test_get_dropped_tasks_reports_skipped_tasks_when_over_budget`) before Cohort D. Cohort A is the only breaking change.
