"""Deterministic legacy scheduler — the fallback engine for the RAG pipeline.

This module is invoked when the RAG pipeline (services/rag_pipeline.py) cannot
produce a valid LLM-generated schedule. The full path:

    Streamlit / FastAPI request
      -> RAGPipeline.run()
        -> Ollama LLM generates schedule (services/ollama_client.py)
        -> validator (services/validator.py) checks citations,
           time-budget, critical medication tasks
        -> if invalid: one repair pass with errors appended to the prompt
        -> if still invalid: services/fallback_scheduler.py builds
           Owner / Pet / Task here and runs
           OwnerScheduler.generate_consolidated_schedule().

The fallback response is returned with model_provider='deterministic-fallback',
validation_status='fallback', and used_fallback=True so the UI / metrics can
flag it as a non-LLM result.

See also:
- services/fallback_scheduler.py — the bridge that calls into this module.
- services/rag_pipeline.py — the caller that decides when to invoke the bridge.
- CLAUDE.md "Deterministic fallback" section — high-level architecture note.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_PREFERRED_TIME_INVALID = 24 * 60 + 1  # minutes; sorts after any valid clock time


def _preferred_time_sort_minutes(value: object) -> int:
    """Parse preferred_time to minutes since midnight; invalid / empty sorts last."""
    if isinstance(value, list):
        if not value:
            return _PREFERRED_TIME_INVALID
        return min(_preferred_time_sort_minutes(v) for v in value)

    raw = " ".join(str(value or "").split())
    m = re.match(r"^(\d{1,2})\s*:\s*(\d{2})$", raw)
    if not m:
        return _PREFERRED_TIME_INVALID
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return _PREFERRED_TIME_INVALID
    return h * 60 + mi


# ─────────────────────────────────────────────────────────────────────────────
# CLEANUP BACKLOG — DO NOT HARD-DELETE WITHOUT MIGRATING DOCS FIRST
# ─────────────────────────────────────────────────────────────────────────────
# The symbols below are soft-deactivated (see LEGACY_ARCHIVE_START blocks) and
# raise NotImplementedError if called. They are kept on their classes so the
# docs/Mermaid.js UML class diagram does not lie about the public API surface.
# Before removing any of them, update docs/Mermaid.js in the same change.
#
# Tier A — zero external consumers, safe to delete next pass:
#   (none in this batch — every item below is referenced by the UML diagram)
#
# Tier B — referenced by docs/Mermaid.js, UML migration required first:
#   Pet.get_energy_level                       docs/Mermaid.js:13
#   Pet.add_special_need                       docs/Mermaid.js:14
#   Pet.display_info                           docs/Mermaid.js:16
#   Owner._preferences / _constraints state    docs/Mermaid.js:23-24
#   Owner.preferences         (property)       docs/Mermaid.js:23
#   Owner.constraints         (property)       docs/Mermaid.js:24
#   Owner.set_preference                       docs/Mermaid.js:26
#   Owner.is_available                         docs/Mermaid.js:27
#   Schedule.is_feasible                       docs/Mermaid.js:57
#   Scheduler.generate_schedule                docs/Mermaid.js:67
#   OwnerScheduler.resolve_conflict            docs/Mermaid.js:82
#   OwnerScheduler.is_overbooked               docs/Mermaid.js:84
#
# Each block has inline metadata (Why / Last consumer / Reactivate).
# Promotion-to-deletion checklist for any Tier B item:
#   1. Remove the matching entry from docs/Mermaid.js.
#   2. Delete the stub method + its LEGACY_ARCHIVE block here.
#   3. Drop its row from this backlog.
#   4. Re-run pytest and main.py to confirm no surprise consumers.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Pet:
    name: str
    species: str
    age: int
    energy_level: str
    special_needs: list = field(default_factory=list)
    tasks: list = field(default_factory=list)
    owner: Optional['Owner'] = field(default=None, repr=False)

    def get_energy_level(self) -> str:
        """[DEPRECATED — soft-deactivated 2026-04-29] Originally returned the pet's energy level."""
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: trivial getter; energy_level is already a public dataclass field
        #        and is read directly as `pet.energy_level` in app.py / main.py.
        #   Last consumer: docs/Mermaid.js:13 (UML diagram entry).
        #   Reactivate: replace the NotImplementedError stub with `return self.energy_level`.
        # return self.energy_level
        # LEGACY_ARCHIVE_END
        raise NotImplementedError("Pet.get_energy_level is soft-deactivated; see LEGACY_ARCHIVE block above.")

    def add_special_need(self, need: str) -> None:
        """[DEPRECATED — soft-deactivated 2026-04-29] Originally appended a special need to the pet's list."""
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: never wired to UI or CLI; special_needs is mutated directly via
        #        the dataclass field (e.g. `pet.special_needs.append(...)`).
        #   Last consumer: docs/Mermaid.js:14 (UML diagram entry).
        #   Reactivate: replace the NotImplementedError stub with `self.special_needs.append(need)`.
        # self.special_needs.append(need)
        # LEGACY_ARCHIVE_END
        raise NotImplementedError("Pet.add_special_need is soft-deactivated; see LEGACY_ARCHIVE block above.")

    def add_task(self, task: 'Task') -> None:
        """Append a task to the pet's task list."""
        self.tasks.append(task)

    def display_info(self) -> str:
        """[DEPRECATED — soft-deactivated 2026-04-29] Originally returned a formatted string with the pet's details."""
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: pretty-printer superseded by Streamlit rendering pet fields
        #        individually; no caller in app.py, main.py, or test/.
        #   Last consumer: docs/Mermaid.js:16 (UML diagram entry).
        #   Reactivate: replace the NotImplementedError stub with the f-string body
        #        in the commented lines below.
        # needs = ", ".join(self.special_needs) if self.special_needs else "None"
        # return (
        #     f"Name: {self.name}\n"
        #     f"Species: {self.species}\n"
        #     f"Age: {self.age}\n"
        #     f"Energy Level: {self.energy_level}\n"
        #     f"Special Needs: {needs}"
        # )
        # LEGACY_ARCHIVE_END
        raise NotImplementedError("Pet.display_info is soft-deactivated; see LEGACY_ARCHIVE block above.")


class Owner:
    def __init__(self, name: str, available_time_per_day: int, preferences: dict = None, constraints: list = None):
        self._name = name
        self._pets: list[Pet] = []
        self._available_time_per_day = available_time_per_day
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: kwargs were accepted but never read by any caller; the backing
        #        state is unused since all four accessor methods (preferences,
        #        constraints, set_preference, is_available) had zero consumers.
        #        Kwargs remain in the signature so existing call sites that
        #        pass `preferences=...` or `constraints=...` don't crash.
        #   Last consumer: docs/Mermaid.js:23-24 (UML private fields).
        #   Reactivate: uncomment both `self._preferences` / `self._constraints`
        #        assigns below. This is a PREREQUISITE for reactivating the four
        #        accessor methods (Owner.preferences/.constraints/.set_preference/.is_available).
        # self._preferences = preferences if preferences is not None else {}
        # self._constraints = constraints if constraints is not None else []
        # LEGACY_ARCHIVE_END
        # preferences/constraints kwargs are accepted but discarded; accessors are also archived.

    @property
    def name(self) -> str:
        """Return the owner's name."""
        return self._name

    @property
    def pets(self) -> list[Pet]:
        """Return the list of pets owned."""
        return self._pets

    @property
    def preferences(self) -> dict:
        """[DEPRECATED — soft-deactivated 2026-04-29] Originally returned the owner's scheduling preferences."""
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: getter for state that no caller reads.
        #   Last consumer: docs/Mermaid.js:23 (UML private field).
        #   Reactivate: requires Owner.__init__ state to be restored first;
        #        then replace the NotImplementedError stub with `return self._preferences`.
        # return self._preferences
        # LEGACY_ARCHIVE_END
        raise NotImplementedError("Owner.preferences is soft-deactivated; see LEGACY_ARCHIVE block above.")

    @property
    def constraints(self) -> list:
        """[DEPRECATED — soft-deactivated 2026-04-29] Originally returned the owner's time slot constraints."""
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: getter for state that no caller reads.
        #   Last consumer: docs/Mermaid.js:24 (UML private field).
        #   Reactivate: requires Owner.__init__ state to be restored first;
        #        then replace the NotImplementedError stub with `return self._constraints`.
        # return self._constraints
        # LEGACY_ARCHIVE_END
        raise NotImplementedError("Owner.constraints is soft-deactivated; see LEGACY_ARCHIVE block above.")

    def get_available_time(self) -> int:
        """Return the owner's available minutes per day."""
        return self._available_time_per_day

    def set_preference(self, key: str, value) -> None:
        """[DEPRECATED — soft-deactivated 2026-04-29] Originally set a scheduling preference by key."""
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: mutator for the unused preferences state.
        #   Last consumer: docs/Mermaid.js:26 (UML method).
        #   Reactivate: requires Owner.__init__ state to be restored first;
        #        then replace the NotImplementedError stub with `self._preferences[key] = value`.
        # self._preferences[key] = value
        # LEGACY_ARCHIVE_END
        raise NotImplementedError("Owner.set_preference is soft-deactivated; see LEGACY_ARCHIVE block above.")

    def is_available(self, time_slot: str) -> bool:
        """[DEPRECATED — soft-deactivated 2026-04-29] Originally returned True if a time slot was not in the owner's constraints."""
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: time-slot constraint check was scoped out — neither Scheduler
        #        nor OwnerScheduler consult owner constraints during fitting.
        #   Last consumer: docs/Mermaid.js:27 (UML method).
        #   Reactivate: requires Owner.__init__ state to be restored first;
        #        then replace the NotImplementedError stub with `return time_slot not in self._constraints`.
        # return time_slot not in self._constraints
        # LEGACY_ARCHIVE_END
        raise NotImplementedError("Owner.is_available is soft-deactivated; see LEGACY_ARCHIVE block above.")

    def add_pet(self, pet: Pet) -> None:
        """Add a pet to the owner's list and link the owner back to the pet."""
        self._pets.append(pet)
        pet.owner = self


@dataclass
class Task:
    title: str
    duration_minutes: int
    priority: str
    frequency: str
    description: str
    preferred_time: str | list = ""
    pet_requirements: list = field(default_factory=list)
    completed: bool = False
    due_date: date | None = None

    def mark_complete(self) -> 'Task | None':
        """Mark the task as completed and return a new Task for the next occurrence.

        Returns a new Task (with completed=False) for recurring frequencies:
          - "daily"         → due_date advances by 1 day
          - "weekly:<Day>"  → due_date advances by 7 days
          - "once"          → returns None (no recurrence)
        """
        self.completed = True
        base = self.due_date if self.due_date is not None else date.today()
        if self.frequency == "daily":
            next_due = base + timedelta(days=1)
        elif self.frequency.startswith("weekly:"):
            next_due = base + timedelta(weeks=1)
        else:
            return None
        return Task(
            title=self.title,
            duration_minutes=self.duration_minutes,
            priority=self.priority,
            frequency=self.frequency,
            description=self.description,
            preferred_time=self.preferred_time,
            pet_requirements=list(self.pet_requirements),
            completed=False,
            due_date=next_due,
        )

    def get_priority_score(self) -> int:
        """Return a numeric priority score: high=3, medium=2, low=1."""
        scores = {"high": 3, "medium": 2, "low": 1}
        return scores.get(self.priority.lower(), 0)

    def can_fit(self, available_minutes: int) -> bool:
        """Return True if the task duration fits within the available minutes."""
        return self.duration_minutes <= available_minutes

    def is_due_today(self, day: str) -> bool:
        """Return True if the task should be scheduled on the given day.

        If due_date is set, the task is only eligible on or after that date.
        """
        if self.due_date is not None and date.today() < self.due_date:
            return False
        if self.frequency == "daily":
            return True
        if self.frequency == "once":
            if self.due_date is None:
                return False
            if date.today() != self.due_date:
                return False
            return day == DAYS[self.due_date.weekday()]
        # supports "weekly:Monday" or a list of days like ["Monday", "Wednesday"]
        if isinstance(self.frequency, list):
            return day in self.frequency
        if self.frequency.startswith("weekly:"):
            return day == self.frequency.split(":")[1]
        return False


class Schedule:
    def __init__(self, pet: Pet, owner: Owner):
        self._pet = pet
        self._owner = owner
        self._weekly_plan: dict[str, list[Task]] = {}
        self._generated_at: datetime = None
        self._explanation: str = ""
        self._conflicts: list = []

    def get_day_plan(self, day: str) -> list[Task]:
        """Return the list of scheduled task entries for the given day."""
        return self._weekly_plan.get(day, [])

    def total_time_for_day(self, day: str) -> int:
        """Return the total scheduled minutes for the given day."""
        return sum(entry["task"].duration_minutes for entry in self.get_day_plan(day))

    def add_scheduled_task(self, day: str, task: Task, time: str) -> None:
        """Add a task entry with a time slot to the given day's plan."""
        if day not in self._weekly_plan:
            self._weekly_plan[day] = []
        self._weekly_plan[day].append({"task": task, "time": time})

    def is_feasible(self) -> bool:
        """[DEPRECATED — soft-deactivated 2026-04-29] Originally returned True if no day exceeded the owner's daily time limit."""
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: feasibility predicate replaced by OwnerScheduler.detect_time_conflicts,
        #        which reports overages explicitly instead of returning a single bool.
        #   Last consumer: docs/Mermaid.js:57 (UML method); no runtime callers.
        #   Reactivate: replace the NotImplementedError stub with the two-line body
        #        below. Preferred at call sites:
        #        `len(owner_scheduler.detect_time_conflicts()) == 0`.
        # available = self._owner.get_available_time()
        # return all(self.total_time_for_day(day) <= available for day in self._weekly_plan)
        # LEGACY_ARCHIVE_END
        raise NotImplementedError("Schedule.is_feasible is soft-deactivated; see LEGACY_ARCHIVE block above.")

    def get_explanation(self) -> str:
        """Return the scheduling explanation log."""
        return self._explanation

    def set_explanation(self, explanation: str) -> None:
        """Set the scheduling explanation log."""
        self._explanation = explanation

    def get_conflicts(self) -> list:
        """Return the list of detected scheduling conflicts."""
        return self._conflicts


class Scheduler:
    def __init__(self, pet: Pet, owner: Owner, all_tasks: list[Task]):
        self._pet = pet
        self._owner = owner
        self._all_tasks = all_tasks

    def generate_schedule(self) -> Schedule:
        """[DEPRECATED — soft-deactivated 2026-04-29] Originally built a weekly Schedule for a single pet (superseded by OwnerScheduler.generate_consolidated_schedule)."""
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: single-pet entry point superseded by
        #        OwnerScheduler.generate_consolidated_schedule, which handles 1+ pets
        #        with a shared daily time budget. The Scheduler class itself stays
        #        alive because its helpers (calculate_task_priority, fit_tasks_in_day,
        #        sort_by_time, explain_scheduling_decision) are still called by
        #        OwnerScheduler.
        #   Last consumer: docs/Mermaid.js:67 (UML method); no runtime callers.
        #   Reactivate: not recommended — OwnerScheduler is the canonical path.
        #        If genuinely needed, restore the body from the commented block below.
        # schedule = Schedule(self._pet, self._owner)
        # for day in DAYS:
        #     due_today = [t for t in self._all_tasks if t.is_due_today(day)]
        #     fitted = self.fit_tasks_in_day(day, due_today)
        #     time_cursor = 8 * 60  # 08:00 in minutes
        #     for task in fitted:
        #         time_str = f"{time_cursor // 60:02d}:{time_cursor % 60:02d}"
        #         schedule.add_scheduled_task(day, task, time_str)
        #         explanation = self.explain_scheduling_decision(task, day, time_str)
        #         schedule.set_explanation(schedule.get_explanation() + explanation + "\n")
        #         time_cursor += task.duration_minutes
        # schedule._generated_at = datetime.now()
        # return schedule
        # LEGACY_ARCHIVE_END
        raise NotImplementedError("Scheduler.generate_schedule is soft-deactivated; see LEGACY_ARCHIVE block above.")

    def calculate_task_priority(self, task: Task) -> int:
        """Return the task's priority score, boosted if it matches a pet special need."""
        score = task.get_priority_score()
        if task.title.lower() in [need.lower() for need in self._pet.special_needs]:
            score += 1
        return score

    def fit_tasks_in_day(self, day: str, available_tasks: list[Task]) -> list[Task]:
        """Return a greedy list of tasks that fit within the owner's daily time limit.

        Tasks with a preferred_time are anchored first (sorted by time), then remaining
        tasks fill in by priority. Completed tasks are excluded.
        """
        pending = [t for t in available_tasks if not t.completed]
        timed = self.sort_by_time([t for t in pending if t.preferred_time])
        untimed = sorted(
            [t for t in pending if not t.preferred_time],
            key=lambda t: self.calculate_task_priority(t),
            reverse=True,
        )
        ordered = timed + untimed
        fitted = []
        remaining = self._owner.get_available_time()
        for task in ordered:
            if task.can_fit(remaining):
                fitted.append(task)
                remaining -= task.duration_minutes
        return fitted

    def sort_by_time(self, tasks: list[Task]) -> list[Task]:
        """Return tasks sorted by preferred_time (HH:MM). Tasks without a time sort last."""
        return sorted(tasks, key=lambda t: _preferred_time_sort_minutes(t.preferred_time))

    def explain_scheduling_decision(self, task: Task, day: str, time: str) -> str:
        """Return a human-readable string explaining why a task was placed on a given day and time."""
        return (
            f"[{day} {time}] '{task.title}' scheduled "
            f"(priority={task.get_priority_score()}, duration={task.duration_minutes}min)"
        )


class OwnerScheduler:
    def __init__(self, owner: Owner, pets: list[Pet], tasks_per_pet: dict[str, list[Task]]):
        self._owner = owner
        self._pets = pets
        self._tasks_per_pet = tasks_per_pet  # {pet.name: [Task, ...]}
        self._schedules: dict[str, Schedule] = {}
        self._dropped_tasks: dict[str, list[dict]] = {}  # {day: [{pet, task}, ...]}

    def generate_consolidated_schedule(self) -> dict[str, Schedule]:
        """Generate and store a Schedule for each pet using a shared time cursor per day.

        All pets' tasks compete for the same daily time budget and are assigned
        sequential start times from a single 08:00 clock, so no two tasks ever
        share a time slot.
        """
        # Create a Scheduler and empty Schedule for every pet up front.
        schedulers: dict[str, Scheduler] = {}
        for pet in self._pets:
            schedulers[pet.name] = Scheduler(pet, self._owner, self._tasks_per_pet.get(pet.name, []))
            self._schedules[pet.name] = Schedule(pet, self._owner)

        for day in DAYS:
            # Collect every (pet, task) pair that is due today across all pets.
            all_due: list[tuple[Pet, Task]] = []
            for pet in self._pets:
                for task in self._tasks_per_pet.get(pet.name, []):
                    if task.is_due_today(day) and not task.completed:
                        all_due.append((pet, task))

            # Timed tasks anchor first (sorted by preferred_time), then remaining
            # tasks fill in by priority score (special-needs boost included).
            timed = sorted(
                [(p, t) for p, t in all_due if t.preferred_time],
                key=lambda x: _preferred_time_sort_minutes(x[1].preferred_time),
            )
            untimed = sorted(
                [(p, t) for p, t in all_due if not t.preferred_time],
                key=lambda x: schedulers[x[0].name].calculate_task_priority(x[1]),
                reverse=True,
            )
            ordered = timed + untimed

            # Greedy fit against a single shared daily limit with one time cursor.
            remaining = self._owner.get_available_time()
            time_cursor = 8 * 60  # 08:00
            self._dropped_tasks[day] = []

            for pet, task in ordered:
                if task.can_fit(remaining):
                    time_str = f"{time_cursor // 60:02d}:{time_cursor % 60:02d}"
                    self._schedules[pet.name].add_scheduled_task(day, task, time_str)
                    explanation = schedulers[pet.name].explain_scheduling_decision(task, day, time_str)
                    prev = self._schedules[pet.name].get_explanation()
                    self._schedules[pet.name].set_explanation(prev + explanation + "\n")
                    remaining -= task.duration_minutes
                    time_cursor += task.duration_minutes
                else:
                    self._dropped_tasks[day].append({"pet": pet.name, "task": task})

        for schedule in self._schedules.values():
            schedule._generated_at = datetime.now()

        return self._schedules

    def detect_time_conflicts(self) -> list[dict]:
        """Return a list of days where total scheduled time across all pets exceeds the owner's limit."""
        conflicts = []
        available = self._owner.get_available_time()
        for day in DAYS:
            total = sum(
                schedule.total_time_for_day(day)
                for schedule in self._schedules.values()
            )
            if total > available:
                conflicts.append({"day": day, "total_minutes": total, "limit": available})
        return conflicts

    def resolve_conflict(self, conflict: dict) -> None:
        """[DEPRECATED — soft-deactivated 2026-04-29] Originally bumped the lowest-priority task from a conflicted day to the next day."""
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: conflict-resolution flow was replaced by the drop-list pattern
        #        (see get_dropped_tasks). The consolidated scheduler now skips
        #        tasks that don't fit instead of bumping them to another day.
        #   Last consumer: docs/Mermaid.js:82 (UML method); no runtime callers.
        #   Reactivate: restore the bump-to-next-day body below if product
        #        direction reverts; otherwise prefer surfacing dropped tasks.
        # day = conflict["day"]
        # next_day = DAYS[(DAYS.index(day) + 1) % len(DAYS)]
        # for schedule in self._schedules.values():
        #     plan = schedule.get_day_plan(day)
        #     if not plan:
        #         continue
        #     # bump the lowest-priority task to the next day
        #     lowest = min(plan, key=lambda e: e["task"].get_priority_score())
        #     plan.remove(lowest)
        #     schedule.add_scheduled_task(next_day, lowest["task"], lowest["time"])
        #     schedule._conflicts.append(conflict)
        #     break
        # LEGACY_ARCHIVE_END
        raise NotImplementedError("OwnerScheduler.resolve_conflict is soft-deactivated; see LEGACY_ARCHIVE block above.")

    def get_daily_summary(self, day: str) -> dict[str, list[Task]]:
        """Return a dict of pet name to scheduled task entries for the given day."""
        return {
            pet_name: schedule.get_day_plan(day)
            for pet_name, schedule in self._schedules.items()
        }

    def is_overbooked(self) -> bool:
        """[DEPRECATED — soft-deactivated 2026-04-29] Originally returned True if any day had more scheduled time than the owner allowed."""
        # LEGACY_ARCHIVE_START — soft-deactivated 2026-04-29 (Tier B)
        #   Why: thin one-line wrapper over detect_time_conflicts; callers that
        #        cared about overbooking now use the explicit conflict list.
        #   Last consumer: docs/Mermaid.js:84 (UML method); no runtime callers.
        #   Reactivate: replace the NotImplementedError stub with `return len(self.detect_time_conflicts()) > 0`.
        # return len(self.detect_time_conflicts()) > 0
        # LEGACY_ARCHIVE_END
        raise NotImplementedError("OwnerScheduler.is_overbooked is soft-deactivated; see LEGACY_ARCHIVE block above.")

    def suggest_consolidated_tasks(self) -> list[str]:
        """Return task titles that appear in more than one pet's schedule."""
        all_titles = [
            entry["task"].title
            for schedule in self._schedules.values()
            for entries in schedule._weekly_plan.values()
            for entry in entries
        ]
        counts = Counter(all_titles)
        return [title for title, count in counts.items() if count > 1]

    def filter_tasks(self, day: str, pet_name: str = None, completed: bool = None) -> dict[str, list]:
        """Return scheduled task entries filtered by pet name and/or completion status.

        Args:
            day: Day name to query (e.g. "Monday").
            pet_name: If provided, only return entries for this pet.
            completed: If True, return only completed tasks; if False, only incomplete; if None, return all.
        """
        summary = self.get_daily_summary(day)
        if pet_name is not None:
            summary = {k: v for k, v in summary.items() if k == pet_name}
        if completed is not None:
            summary = {
                k: [e for e in entries if e["task"].completed == completed]
                for k, entries in summary.items()
            }
        return summary

    def get_conflict_report(self) -> str:
        """Return a formatted string summarizing all scheduling conflicts."""
        conflicts = self.detect_time_conflicts()
        if not conflicts:
            return "No conflicts detected."
        lines = []
        for c in conflicts:
            lines.append(
                f"{c['day']}: {c['total_minutes']} min scheduled, limit is {c['limit']} min "
                f"(over by {c['total_minutes'] - c['limit']} min)"
            )
        return "\n".join(lines)

    def get_dropped_tasks(self) -> dict[str, list[dict]]:
        """Return tasks that were skipped during scheduling because they didn't fit the daily budget.

        Returns {day: [{"pet": pet_name, "task": Task}, ...]} for days that had drops.
        """
        return {day: entries for day, entries in self._dropped_tasks.items() if entries}

    def detect_time_slot_conflicts(self) -> list[str]:
        """Return warning strings for every time slot where 2+ tasks are scheduled simultaneously.

        Checks across all pets so both same-pet and cross-pet overlaps are caught.
        """
        warnings = []
        for day in DAYS:
            slot_map = defaultdict(list)
            for pet_name, slot, title in (
                (pet_name, entry["time"], entry["task"].title)
                for pet_name, schedule in self._schedules.items()
                for entry in schedule.get_day_plan(day)
            ):
                slot_map[slot].append((pet_name, title))
            for slot, entries in slot_map.items():
                if len(entries) > 1:
                    details = ", ".join(f'"{title}" ({pet})' for pet, title in entries)
                    warnings.append(
                        f"WARNING [{day} {slot}]: {len(entries)} tasks overlap — {details}"
                    )
        return warnings

    def get_time_slot_conflict_report(self) -> str:
        """Return a formatted warning report for simultaneous task conflicts."""
        warnings = self.detect_time_slot_conflicts()
        if not warnings:
            return "No time-slot conflicts detected."
        return "\n".join(warnings)
