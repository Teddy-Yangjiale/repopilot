from pathlib import Path

from fastapi.testclient import TestClient

from repopilot.api import app
from repopilot.container import get_orchestrator
from tests.test_orchestrator import build_orchestrator


def test_health() -> None:
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_investigation_api(sample_repo: Path, tmp_path: Path) -> None:
    app.dependency_overrides.clear()
    get_orchestrator.cache_clear()
    import repopilot.api as api_module

    test_orchestrator = build_orchestrator(tmp_path)
    original = api_module.get_orchestrator
    api_module.get_orchestrator = lambda: test_orchestrator
    try:
        response = TestClient(app).post(
            "/v1/tasks/investigate",
            json={
                "repo_path": str(sample_repo),
                "question": "How does ReActAgent finish?",
                "keywords": ["ReActAgent", "Finish"],
            },
        )
    finally:
        api_module.get_orchestrator = original

    assert response.status_code == 200
    assert response.json()["task"]["stage"] == "completed"
