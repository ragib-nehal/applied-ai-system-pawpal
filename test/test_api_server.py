import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from backend.pawpal_backend import api_server
from backend.pawpal_backend.schemas import Citation, RAGScheduleResponse, ScheduledTask


def test_health_returns_ok():
    client = TestClient(api_server.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_schedule_endpoint_runs_pipeline(monkeypatch):
    class FakePipeline:
        def __init__(self):
            self.seen_payload = None

        def run(self, payload):
            self.seen_payload = payload
            return RAGScheduleResponse(
                schedule=[
                    ScheduledTask(
                        pet="Buddy",
                        day="Monday",
                        time="08:00",
                        title="Medication",
                        duration_minutes=10,
                        priority="high",
                        reason="Test response",
                        citations=[
                            Citation(record_id="r1", section="medical_history", snippet="Medication context")
                        ],
                    )
                ],
                guidance=[],
                dropped_tasks=[],
                model_provider="test",
                validation_status="valid",
            )

    fake_pipeline = FakePipeline()
    monkeypatch.setattr(api_server, "pipeline", fake_pipeline)
    client = TestClient(api_server.app)

    response = client.post(
        "/schedule",
        json={
            "owner_name": "Alex",
            "available_time_per_day": 60,
            "pets": [
                {
                    "name": "Buddy",
                    "species": "Dog",
                    "age": 3,
                    "tasks": [
                        {
                            "title": "Medication",
                            "duration_minutes": 10,
                            "priority": "high",
                            "frequency": "daily",
                        }
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["schedule"][0]["title"] == "Medication"
    assert fake_pipeline.seen_payload.owner_name == "Alex"
    assert fake_pipeline.seen_payload.pets[0].name == "Buddy"


def test_admin_reset_wipes_stores_and_rebuilds_pipeline(monkeypatch):
    calls = []

    class ReplacementPipeline:
        pass

    def fake_reset_all():
        calls.append("reset")

    monkeypatch.setattr(api_server, "reset_all", fake_reset_all)
    monkeypatch.setattr(api_server, "RAGPipeline", ReplacementPipeline)
    client = TestClient(api_server.app)

    response = client.post("/admin/reset")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "Local SQLite + Chroma stores wiped.",
    }
    assert calls == ["reset"]
    assert isinstance(api_server.pipeline, ReplacementPipeline)
