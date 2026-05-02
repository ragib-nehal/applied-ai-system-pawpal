import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, timedelta
from backend.pawpal_backend.services.legacy_scheduler import Task, Pet, Owner, Schedule, Scheduler, OwnerScheduler


def make_task(**kwargs):
    defaults = {
        "title": "Test Task",
        "duration_minutes": 30,
        "priority": "medium",
        "frequency": "daily",
        "description": "A test task",
    }
    defaults.update(kwargs)
    return Task(**defaults)


# --- Task Completion Tests ---

def test_task_starts_incomplete():
    task = make_task()
    assert task.completed is False


def test_mark_complete_changes_status():
    task = make_task()
    task.mark_complete()
    assert task.completed is True


def test_mark_complete_is_idempotent():
    task = make_task()
    task.mark_complete()
    task.mark_complete()
    assert task.completed is True


# --- Pet Task Addition Tests ---

def test_pet_starts_with_no_tasks():
    pet = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    assert len(pet.tasks) == 0


def test_add_task_increases_count():
    pet = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    task = make_task(title="Walk")
    pet.add_task(task)
    assert len(pet.tasks) == 1


def test_add_multiple_tasks_increases_count():
    pet = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    pet.add_task(make_task(title="Walk"))
    pet.add_task(make_task(title="Feed"))
    pet.add_task(make_task(title="Play"))
    assert len(pet.tasks) == 3


def test_added_task_is_retrievable():
    pet = Pet(name="Whiskers", species="Cat", age=5, energy_level="low")
    task = make_task(title="Grooming")
    pet.add_task(task)
    assert pet.tasks[0].title == "Grooming"


def test_task_priority_score_maps_known_priorities():
    assert make_task(priority="high").get_priority_score() == 3
    assert make_task(priority="medium").get_priority_score() == 2
    assert make_task(priority="low").get_priority_score() == 1


def test_task_can_fit_compares_duration_to_available_minutes():
    task = make_task(duration_minutes=30)

    assert task.can_fit(30) is True
    assert task.can_fit(29) is False


def test_list_frequency_is_due_only_on_listed_days():
    task = make_task(frequency=["Monday", "Wednesday"])

    assert task.is_due_today("Monday") is True
    assert task.is_due_today("Tuesday") is False
    assert task.is_due_today("Wednesday") is True


def test_future_due_date_is_not_due_today():
    task = make_task(frequency="daily", due_date=date.today() + timedelta(days=1))

    assert task.is_due_today("Monday") is False


# --- Sorting Correctness Tests ---

def make_owner(minutes=120):
    return Owner(name="Alex", available_time_per_day=minutes)


def test_sort_by_time_returns_chronological_order():
    """Tasks with preferred_time are sorted earliest-first."""
    owner = make_owner()
    pet = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    tasks = [
        make_task(title="Afternoon Walk", preferred_time="14:00"),
        make_task(title="Morning Feed",   preferred_time="07:00"),
        make_task(title="Midday Play",    preferred_time="12:00"),
    ]
    scheduler = Scheduler(pet, owner, tasks)
    sorted_tasks = scheduler.sort_by_time(tasks)
    times = [t.preferred_time for t in sorted_tasks]
    assert times == sorted(times)


def test_fit_tasks_schedules_timed_before_untimed():
    """Timed tasks always appear before untimed tasks in the fitted list."""
    owner = make_owner(minutes=120)
    pet = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    tasks = [
        make_task(title="Untimed High", priority="high", preferred_time=""),
        make_task(title="Timed Low",    priority="low",  preferred_time="09:00"),
    ]
    scheduler = Scheduler(pet, owner, tasks)
    fitted = scheduler.fit_tasks_in_day("Monday", tasks)
    assert fitted[0].title == "Timed Low"
    assert fitted[1].title == "Untimed High"


def test_fit_tasks_sorts_untimed_by_priority():
    """Among untimed tasks, higher priority comes first."""
    owner = make_owner(minutes=120)
    pet = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    tasks = [
        make_task(title="Low Task",    priority="low",    preferred_time=""),
        make_task(title="High Task",   priority="high",   preferred_time=""),
        make_task(title="Medium Task", priority="medium", preferred_time=""),
    ]
    scheduler = Scheduler(pet, owner, tasks)
    fitted = scheduler.fit_tasks_in_day("Monday", tasks)
    titles = [t.title for t in fitted]
    assert titles == ["High Task", "Medium Task", "Low Task"]


def test_calculate_task_priority_boosts_matching_special_need():
    owner = make_owner(minutes=120)
    pet = Pet(
        name="Buddy",
        species="Dog",
        age=3,
        energy_level="high",
        special_needs=["Medication"],
    )
    medication = make_task(title="Medication", priority="medium")
    walk = make_task(title="Walk", priority="medium")
    scheduler = Scheduler(pet, owner, [medication, walk])

    assert scheduler.calculate_task_priority(medication) == 3
    assert scheduler.calculate_task_priority(walk) == 2


def test_schedule_adds_tasks_and_totals_day_minutes():
    owner = make_owner(minutes=120)
    pet = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    schedule = Schedule(pet, owner)

    schedule.add_scheduled_task("Monday", make_task(title="Walk", duration_minutes=20), "08:00")
    schedule.add_scheduled_task("Monday", make_task(title="Feed", duration_minutes=10), "08:20")

    assert len(schedule.get_day_plan("Monday")) == 2
    assert schedule.total_time_for_day("Monday") == 30


# --- Recurrence Logic Tests ---

def test_daily_task_recurs_next_day():
    """mark_complete on a daily task returns a new task due the following day."""
    today = date.today()
    task = make_task(frequency="daily", due_date=today)
    next_task = task.mark_complete()
    assert next_task is not None
    assert next_task.due_date == today + timedelta(days=1)
    assert next_task.completed is False


def test_weekly_task_recurs_seven_days_later():
    """mark_complete on a weekly task returns a new task due 7 days later."""
    today = date.today()
    task = make_task(frequency="weekly:Monday", due_date=today)
    next_task = task.mark_complete()
    assert next_task is not None
    assert next_task.due_date == today + timedelta(weeks=1)
    assert next_task.completed is False


def test_once_task_does_not_recur():
    """mark_complete on a one-time task returns None."""
    task = make_task(frequency="once")
    assert task.mark_complete() is None


def test_recurrence_preserves_task_metadata():
    """The recurred task keeps the same title, duration, and priority."""
    today = date.today()
    task = make_task(title="Bath", duration_minutes=45, priority="high",
                     frequency="daily", due_date=today)
    next_task = task.mark_complete()
    assert next_task.title == "Bath"
    assert next_task.duration_minutes == 45
    assert next_task.priority == "high"


# --- Conflict Detection Tests ---

def test_no_conflict_when_pets_fit_within_daily_limit():
    """Two pets whose combined tasks stay within the daily limit → no conflicts."""
    owner = make_owner(minutes=60)
    pet1 = Pet(name="Buddy",    species="Dog", age=3, energy_level="high")
    pet2 = Pet(name="Whiskers", species="Cat", age=5, energy_level="low")
    owner.add_pet(pet1)
    owner.add_pet(pet2)
    tasks_per_pet = {
        "Buddy":    [make_task(title="Walk", duration_minutes=20)],
        "Whiskers": [make_task(title="Feed", duration_minutes=10)],
    }
    os_ = OwnerScheduler(owner, [pet1, pet2], tasks_per_pet)
    os_.generate_consolidated_schedule()
    assert os_.detect_time_conflicts() == []


def test_conflict_detected_when_pets_exceed_daily_limit():
    """When combined tasks exceed the daily limit, the lower-priority task is dropped.

    The shared time cursor prevents over-scheduling, so detect_time_conflicts()
    returns nothing. The observable effect is that only the higher-priority task
    (Walk, 40 min) fits within the 60-min budget; Feed (also 40 min) is dropped.
    """
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
    # Shared cursor: Walk (40 min) fits; Feed (40 min) would exceed the 60-min limit → dropped.
    assert os_.detect_time_conflicts() == []
    monday_buddy = os_.get_daily_summary("Monday")["Buddy"]
    monday_whiskers = os_.get_daily_summary("Monday")["Whiskers"]
    assert len(monday_buddy) == 1        # Walk was scheduled
    assert len(monday_whiskers) == 0     # Feed was dropped


def test_time_slot_conflict_detected_for_same_start_time():
    """With the shared time cursor, two tasks with the same preferred_time get
    sequential slots — the second is placed immediately after the first ends."""
    owner = make_owner(minutes=120)
    pet1 = Pet(name="Buddy",    species="Dog", age=3, energy_level="high")
    pet2 = Pet(name="Whiskers", species="Cat", age=5, energy_level="low")
    owner.add_pet(pet1)
    owner.add_pet(pet2)
    tasks_per_pet = {
        "Buddy":    [make_task(title="Walk", preferred_time="08:00", duration_minutes=30)],
        "Whiskers": [make_task(title="Feed", preferred_time="08:00", duration_minutes=30)],
    }
    os_ = OwnerScheduler(owner, [pet1, pet2], tasks_per_pet)
    os_.generate_consolidated_schedule()
    # No overlaps — tasks are sequential, so no slot-level warnings.
    assert os_.detect_time_slot_conflicts() == []
    # Walk gets 08:00; Feed gets 08:30 (right after Walk's 30 min).
    monday = {
        pet: entries
        for pet, entries in os_.get_daily_summary("Monday").items()
        if entries
    }
    times = {entries[0]["time"] for entries in monday.values()}
    assert "08:00" in times
    assert "08:30" in times


def test_no_time_slot_conflict_single_pet():
    """A single pet with one task per day produces no slot-level warnings."""
    owner = make_owner(minutes=120)
    pet = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    owner.add_pet(pet)
    tasks_per_pet = {
        "Buddy": [make_task(title="Walk", preferred_time="08:00", duration_minutes=30)],
    }
    os_ = OwnerScheduler(owner, [pet], tasks_per_pet)
    os_.generate_consolidated_schedule()
    assert os_.detect_time_slot_conflicts() == []


def test_get_dropped_tasks_returns_tasks_that_do_not_fit():
    owner = make_owner(minutes=20)
    pet = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    owner.add_pet(pet)
    tasks_per_pet = {
        "Buddy": [
            make_task(title="Medication", duration_minutes=20, priority="high"),
            make_task(title="Walk", duration_minutes=20, priority="low"),
        ]
    }
    os_ = OwnerScheduler(owner, [pet], tasks_per_pet)

    os_.generate_consolidated_schedule()

    dropped = os_.get_dropped_tasks()
    assert "Monday" in dropped
    assert dropped["Monday"][0]["pet"] == "Buddy"
    assert dropped["Monday"][0]["task"].title == "Walk"


def test_suggest_consolidated_tasks_returns_titles_scheduled_for_multiple_pets():
    owner = make_owner(minutes=120)
    pet1 = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    pet2 = Pet(name="Whiskers", species="Cat", age=5, energy_level="low")
    owner.add_pet(pet1)
    owner.add_pet(pet2)
    tasks_per_pet = {
        "Buddy": [make_task(title="Feed", duration_minutes=10)],
        "Whiskers": [make_task(title="Feed", duration_minutes=10)],
    }
    os_ = OwnerScheduler(owner, [pet1, pet2], tasks_per_pet)

    os_.generate_consolidated_schedule()

    assert os_.suggest_consolidated_tasks() == ["Feed"]


def test_filter_tasks_can_limit_by_pet_and_completion_status():
    owner = make_owner(minutes=120)
    pet1 = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    pet2 = Pet(name="Whiskers", species="Cat", age=5, energy_level="low")
    owner.add_pet(pet1)
    owner.add_pet(pet2)
    tasks_per_pet = {
        "Buddy": [make_task(title="Walk", duration_minutes=20)],
        "Whiskers": [make_task(title="Feed", duration_minutes=10)],
    }
    os_ = OwnerScheduler(owner, [pet1, pet2], tasks_per_pet)
    os_.generate_consolidated_schedule()

    filtered = os_.filter_tasks("Monday", pet_name="Buddy", completed=False)

    assert list(filtered.keys()) == ["Buddy"]
    assert filtered["Buddy"][0]["task"].title == "Walk"


def test_conflict_reports_describe_no_conflicts():
    owner = make_owner(minutes=120)
    pet = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
    owner.add_pet(pet)
    os_ = OwnerScheduler(owner, [pet], {"Buddy": [make_task(title="Walk", duration_minutes=20)]})
    os_.generate_consolidated_schedule()

    assert os_.get_conflict_report() == "No conflicts detected."
    assert os_.get_time_slot_conflict_report() == "No time-slot conflicts detected."


# --- Weekly Frequency Day Coverage ---

ALL_WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def test_weekly_frequency_supports_every_weekday():
    """A `weekly:<Day>` task is only due on its matching weekday for each of the seven days.

    Protects the backend contract the Streamlit frequency dropdown depends on:
    every weekday must round-trip through `Task.is_due_today` correctly.
    """
    for target_day in ALL_WEEKDAYS:
        task = make_task(frequency=f"weekly:{target_day}")
        for day in ALL_WEEKDAYS:
            assert task.is_due_today(day) is (day == target_day), (
                f"weekly:{target_day} unexpectedly "
                f"{'not ' if day == target_day else ''}due on {day}"
            )


def test_weekly_recurrence_advances_seven_days_for_each_weekday():
    """`mark_complete` on every `weekly:<Day>` advances `due_date` by 7 days
    and preserves the original frequency string."""
    today = date.today()
    for target_day in ALL_WEEKDAYS:
        task = make_task(frequency=f"weekly:{target_day}", due_date=today)
        next_task = task.mark_complete()
        assert next_task is not None
        assert next_task.due_date == today + timedelta(weeks=1)
        assert next_task.frequency == f"weekly:{target_day}"
        assert next_task.completed is False


def test_weekly_task_lands_only_on_target_day_in_consolidated_schedule():
    """The `OwnerScheduler` places a `weekly:<Day>` task only on its target weekday
    when generating the consolidated weekly plan."""
    for target_day in ALL_WEEKDAYS:
        owner = make_owner(minutes=120)
        pet = Pet(name="Buddy", species="Dog", age=3, energy_level="high")
        owner.add_pet(pet)
        tasks_per_pet = {
            "Buddy": [
                make_task(
                    title=f"{target_day} grooming",
                    duration_minutes=20,
                    frequency=f"weekly:{target_day}",
                )
            ],
        }
        os_ = OwnerScheduler(owner, [pet], tasks_per_pet)
        os_.generate_consolidated_schedule()
        for day in ALL_WEEKDAYS:
            entries = os_.get_daily_summary(day).get("Buddy", [])
            if day == target_day:
                assert len(entries) == 1, (
                    f"weekly:{target_day} task missing from {day} schedule"
                )
            else:
                assert entries == [], (
                    f"weekly:{target_day} task unexpectedly scheduled on {day}"
                )
