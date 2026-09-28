from fastapi.testclient import TestClient

from powerplant.main import app

client = TestClient(app)


def test_root_reports_api_is_running() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Powerplant Production Planner API"}


def test_openapi_schema_is_available() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Powerplant Production Planner"
