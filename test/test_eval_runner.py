import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.eval_runner import Scenario, build_scenarios, compute_metrics
from backend.pawpal_backend.schemas import PetInput, RetrievalRecordInput, ScheduleRequest, TaskInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scenario(name="s1", expects_critical=None):
    request = ScheduleRequest(
        owner_name="Tester",
        available_time_per_day=60,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=3,
                tasks=[TaskInput(title="Walk", duration_minutes=20, priority="low", frequency="daily")],
            )
        ],
    )
    return Scenario(name=name, request=request, expects_critical=expects_critical or [])


_DEFAULT_CITATIONS = [{"record_id": "r1", "section": "s", "snippet": "snip"}]


def _schedule_item(pet="Buddy", day="Monday", time="08:00", title="Walk", citations=_DEFAULT_CITATIONS):
    return {
        "pet": pet,
        "day": day,
        "time": time,
        "title": title,
        "duration_minutes": 20,
        "priority": "low",
        "reason": "reason",
        "citations": citations,
    }


def _payload(schedule=None, validation_errors=None, used_fallback=False):
    return {
        "schedule": schedule or [],
        "guidance": [],
        "dropped_tasks": [],
        "retrieval_context_count": 0,
        "model_provider": "test",
        "validation_status": "valid",
        "validation_errors": validation_errors or [],
        "used_fallback": used_fallback,
    }


# ---------------------------------------------------------------------------
# build_scenarios
# ---------------------------------------------------------------------------

def test_build_scenarios_returns_two_scenarios():
    scenarios = build_scenarios()
    assert len(scenarios) == 2


def test_build_scenarios_names_are_baseline_and_tight_budget():
    scenarios = build_scenarios()
    names = [s.name for s in scenarios]
    assert "baseline" in names
    assert "tight_budget" in names


def test_build_scenarios_baseline_has_buddy_medication_critical():
    scenarios = build_scenarios()
    baseline = next(s for s in scenarios if s.name == "baseline")
    assert ("Buddy", "Medication") in baseline.expects_critical


def test_build_scenarios_tight_budget_has_reduced_time():
    scenarios = build_scenarios()
    tight = next(s for s in scenarios if s.name == "tight_budget")
    assert tight.request.available_time_per_day == 20


def test_build_scenarios_baseline_has_retrieval_records():
    scenarios = build_scenarios()
    baseline = next(s for s in scenarios if s.name == "baseline")
    assert len(baseline.request.retrieval_records) > 0


# ---------------------------------------------------------------------------
# compute_metrics — empty input
# ---------------------------------------------------------------------------

def test_compute_metrics_empty_results():
    metrics = compute_metrics([])
    assert metrics.total_runs == 0
    assert metrics.violation_rate == 0.0
    assert metrics.citation_coverage_rate == 0.0
    assert metrics.critical_task_recall == 0.0
    assert metrics.consistency_rate == 0.0
    assert metrics.fallback_frequency == 0.0


# ---------------------------------------------------------------------------
# compute_metrics — violation rate
# ---------------------------------------------------------------------------

def test_violation_rate_zero_when_no_errors():
    results = [
        (_scenario(), _payload(validation_errors=[])),
        (_scenario(), _payload(validation_errors=[])),
    ]
    metrics = compute_metrics(results)
    assert metrics.violation_rate == 0.0


def test_violation_rate_one_when_all_have_errors():
    results = [
        (_scenario(), _payload(validation_errors=["err1"])),
        (_scenario(), _payload(validation_errors=["err2"])),
    ]
    metrics = compute_metrics(results)
    assert metrics.violation_rate == 1.0


def test_violation_rate_partial():
    results = [
        (_scenario(), _payload(validation_errors=["err1"])),
        (_scenario(), _payload(validation_errors=[])),
    ]
    metrics = compute_metrics(results)
    assert metrics.violation_rate == 0.5


# ---------------------------------------------------------------------------
# compute_metrics — fallback frequency
# ---------------------------------------------------------------------------

def test_fallback_frequency_zero_when_no_fallback():
    results = [(_scenario(), _payload(used_fallback=False))]
    metrics = compute_metrics(results)
    assert metrics.fallback_frequency == 0.0


def test_fallback_frequency_one_when_all_fallback():
    results = [
        (_scenario(), _payload(used_fallback=True)),
        (_scenario(), _payload(used_fallback=True)),
    ]
    metrics = compute_metrics(results)
    assert metrics.fallback_frequency == 1.0


def test_fallback_frequency_partial():
    results = [
        (_scenario(), _payload(used_fallback=True)),
        (_scenario(), _payload(used_fallback=False)),
    ]
    metrics = compute_metrics(results)
    assert metrics.fallback_frequency == 0.5


# ---------------------------------------------------------------------------
# compute_metrics — citation coverage
# ---------------------------------------------------------------------------

def test_citation_coverage_zero_when_no_schedule_items():
    results = [(_scenario(), _payload(schedule=[]))]
    metrics = compute_metrics(results)
    assert metrics.citation_coverage_rate == 0.0


def test_citation_coverage_one_when_all_items_have_citations():
    items = [_schedule_item(citations=[{"record_id": "r1", "section": "s", "snippet": "snip"}])]
    results = [(_scenario(), _payload(schedule=items))]
    metrics = compute_metrics(results)
    assert metrics.citation_coverage_rate == 1.0


def test_citation_coverage_zero_when_no_items_have_citations():
    items = [_schedule_item(citations=[])]
    results = [(_scenario(), _payload(schedule=items))]
    metrics = compute_metrics(results)
    assert metrics.citation_coverage_rate == 0.0


# ---------------------------------------------------------------------------
# compute_metrics — critical task recall
# ---------------------------------------------------------------------------

def test_critical_recall_zero_when_critical_task_missing():
    scenario = _scenario(expects_critical=[("Buddy", "Medication")])
    results = [(scenario, _payload(schedule=[_schedule_item(title="Walk")]))]
    metrics = compute_metrics(results)
    assert metrics.critical_task_recall == 0.0


def test_critical_recall_one_when_critical_task_present():
    scenario = _scenario(expects_critical=[("Buddy", "Medication")])
    items = [_schedule_item(pet="Buddy", title="Medication")]
    results = [(scenario, _payload(schedule=items))]
    metrics = compute_metrics(results)
    assert metrics.critical_task_recall == 1.0


def test_critical_recall_zero_when_no_expects_critical():
    # No critical tasks expected means total=0, safe_rate returns 0.0
    scenario = _scenario(expects_critical=[])
    results = [(scenario, _payload(schedule=[_schedule_item()]))]
    metrics = compute_metrics(results)
    assert metrics.critical_task_recall == 0.0


# ---------------------------------------------------------------------------
# compute_metrics — consistency rate
# ---------------------------------------------------------------------------

def test_consistency_first_run_always_hits():
    # First encounter of a scenario name always counts as a consistency hit
    scenario = _scenario(name="baseline")
    items = [_schedule_item()]
    results = [(scenario, _payload(schedule=items))]
    metrics = compute_metrics(results)
    assert metrics.consistency_rate == 1.0


def test_consistency_hit_when_same_signature_repeated():
    # Two runs of same scenario with same schedule = both hit
    scenario1 = _scenario(name="baseline")
    scenario2 = _scenario(name="baseline")
    items = [_schedule_item(pet="Buddy", day="Monday", time="08:00", title="Walk")]
    results = [
        (scenario1, _payload(schedule=items)),
        (scenario2, _payload(schedule=items)),
    ]
    metrics = compute_metrics(results)
    assert metrics.consistency_rate == 1.0


def test_consistency_miss_when_different_schedule_for_same_scenario():
    scenario1 = _scenario(name="baseline")
    scenario2 = _scenario(name="baseline")
    items_a = [_schedule_item(time="08:00")]
    items_b = [_schedule_item(time="09:00")]
    results = [
        (scenario1, _payload(schedule=items_a)),
        (scenario2, _payload(schedule=items_b)),
    ]
    metrics = compute_metrics(results)
    # First run hits (1/2 = 0.5)
    assert metrics.consistency_rate == 0.5


# ---------------------------------------------------------------------------
# compute_metrics — output type is ReliabilityMetrics
# ---------------------------------------------------------------------------

def test_compute_metrics_returns_reliability_metrics():
    from backend.pawpal_backend.schemas import ReliabilityMetrics
    results = [(_scenario(), _payload())]
    metrics = compute_metrics(results)
    assert isinstance(metrics, ReliabilityMetrics)


def test_compute_metrics_total_runs():
    results = [(_scenario(),_payload()), (_scenario(), _payload())]
    metrics = compute_metrics(results)
    assert metrics.total_runs == 2


# ---------------------------------------------------------------------------
# safe_rate boundary: denominator = 0 returns 0.0
# ---------------------------------------------------------------------------

def test_citation_coverage_rate_is_zero_when_no_schedule_items_across_all_runs():
    # Multiple runs, all with empty schedules
    results = [
        (_scenario(), _payload(schedule=[])),
        (_scenario(), _payload(schedule=[])),
    ]
    metrics = compute_metrics(results)
    assert metrics.citation_coverage_rate == 0.0