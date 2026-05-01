from __future__ import annotations

from dataclasses import dataclass

from backend.pawpal_backend.schemas import PetInput, ReliabilityMetrics, RetrievalRecordInput, ScheduleRequest, TaskInput
from backend.pawpal_backend.services.rag_pipeline import RAGPipeline


@dataclass
class Scenario:
    name: str
    request: ScheduleRequest
    expects_critical: list[tuple[str, str]]


def build_scenarios() -> list[Scenario]:
    base_request = ScheduleRequest(
        owner_name="EvalOwner",
        available_time_per_day=90,
        pets=[
            PetInput(
                name="Buddy",
                species="Dog",
                age=4,
                energy_level="high",
                tasks=[
                    TaskInput(title="Medication", duration_minutes=10, priority="high", frequency="daily"),
                    TaskInput(title="Walk", duration_minutes=30, priority="high", frequency="daily"),
                ],
            )
        ],
        retrieval_records=[
            RetrievalRecordInput(
                record_id="buddy-history-1",
                pet_name="Buddy",
                section="medical_history",
                content="Medication must be scheduled daily in the morning.",
            )
        ],
    )
    tight_budget = base_request.model_copy(deep=True)
    tight_budget.available_time_per_day = 20
    return [
        Scenario("baseline", base_request, [("Buddy", "Medication")]),
        Scenario("tight_budget", tight_budget, [("Buddy", "Medication")]),
    ]


def compute_metrics(results: list[tuple[Scenario, dict]]) -> ReliabilityMetrics:
    total_runs = len(results)
    violations = 0
    citation_hits = 0
    citation_total = 0
    critical_hits = 0
    critical_total = 0
    fallback_count = 0
    consistency_hits = 0

    baseline_signatures = {}

    for scenario, payload in results:
        validation_errors = payload.get("validation_errors", [])
        if validation_errors:
            violations += 1
        if payload.get("used_fallback"):
            fallback_count += 1

        schedule = payload.get("schedule", [])
        signature = tuple((x["pet"], x["day"], x["time"], x["title"]) for x in schedule)
        if scenario.name not in baseline_signatures:
            baseline_signatures[scenario.name] = signature
            consistency_hits += 1
        elif baseline_signatures[scenario.name] == signature:
            consistency_hits += 1

        for item in schedule:
            citation_total += 1
            if item.get("citations"):
                citation_hits += 1

        for guidance in payload.get("guidance", []):
            citation_total += 1
            if guidance.get("citations"):
                citation_hits += 1

        for pet_name, title in scenario.expects_critical:
            critical_total += 1
            if any(s["pet"] == pet_name and s["title"] == title for s in schedule):
                critical_hits += 1

    def safe_rate(n: int, d: int) -> float:
        return round((n / d), 3) if d else 0.0

    return ReliabilityMetrics(
        total_runs=total_runs,
        violation_rate=safe_rate(violations, total_runs),
        citation_coverage_rate=safe_rate(citation_hits, citation_total),
        critical_task_recall=safe_rate(critical_hits, critical_total),
        consistency_rate=safe_rate(consistency_hits, total_runs),
        fallback_frequency=safe_rate(fallback_count, total_runs),
    )


def run_eval(repeats: int = 3) -> ReliabilityMetrics:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    pipeline = RAGPipeline()
    scenarios = build_scenarios()
    outputs = []
    for scenario in scenarios:
        for _ in range(repeats):
            result = pipeline.run(scenario.request)
            outputs.append((scenario, result.model_dump()))
    return compute_metrics(outputs)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the PawPal RAG eval harness.")
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="How many times to run each scenario (used to compute consistency_rate). Default: 3.",
    )
    args = parser.parse_args()

    metrics = run_eval(repeats=args.repeats)
    print(metrics.model_dump_json(indent=2))
