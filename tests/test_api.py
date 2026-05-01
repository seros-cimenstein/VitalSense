"""HTTP API tests — exercise the FastAPI surface end-to-end."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import reset_graph
from app.auth import create_access_token
from app.db.repository import reset_repository
from app.main import app


@pytest.fixture(autouse=True)
def _fresh_state():
    """Reset the repo + DI graph before every test so they don't share data."""
    reset_repository()
    reset_graph()
    yield
    reset_repository()
    reset_graph()


@pytest.fixture
def auth_headers():
    token = create_access_token("admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(auth_headers):
    return TestClient(app, headers=auth_headers)


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_dashboard_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "VitalSense" in r.text


def test_create_and_get_patient(client):
    r = client.post("/api/patients", json={
        "name": "Selin Aydın",
        "contact_number": "+90-555-1000",
        "age": 28,
        "height_cm": 168.0,
        "weight_kg": 60.0,
    })
    assert r.status_code == 201
    pid = r.json()["id"]

    r = client.get(f"/api/patients/{pid}")
    assert r.status_code == 200
    assert r.json()["name"] == "Selin Aydın"


def test_get_unknown_patient_404(client):
    r = client.get("/api/patients/does-not-exist")
    assert r.status_code == 404


def test_update_thresholds(client):
    pid = client.post("/api/patients", json={
        "name": "X", "contact_number": "y", "age": 30,
        "height_cm": 170, "weight_kg": 70,
    }).json()["id"]

    r = client.put(f"/api/patients/{pid}/thresholds", json={
        "heart_rate_min": 60,
        "heart_rate_max": 110,
        "temperature_min": 36.0,
        "temperature_max": 38.0,
    })
    assert r.status_code == 200
    assert r.json()["thresholds"]["heart_rate_max"] == 110


def test_telemetry_normal_path(client):
    pid = client.post("/api/patients", json={
        "name": "X", "contact_number": "y", "age": 30,
        "height_cm": 170, "weight_kg": 70,
    }).json()["id"]

    r = client.post(f"/api/telemetry/{pid}", json={
        "heart_rate": 80, "body_temperature": 36.7, "daily_steps": 100,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["breach"] is False
    assert body["verification_pending"] is False


def test_telemetry_breach_starts_verification(client):
    pid = client.post("/api/patients", json={
        "name": "X", "contact_number": "y", "age": 30,
        "height_cm": 170, "weight_kg": 70,
    }).json()["id"]

    r = client.post(f"/api/telemetry/{pid}", json={
        "heart_rate": 160, "body_temperature": 36.7,
    })
    body = r.json()
    assert body["breach"] is True
    assert body["verification_pending"] is True

    # /verify should cancel
    r = client.post(f"/api/verify/{pid}")
    assert r.json() == {"confirmed": True}


def test_patient_status_reports_risk_and_countdown(client):
    pid = client.post("/api/patients", json={
        "name": "Risk", "contact_number": "y", "age": 30,
        "height_cm": 170, "weight_kg": 70,
    }).json()["id"]

    client.post(f"/api/telemetry/{pid}", json={
        "heart_rate": 150, "body_temperature": 36.7,
    })

    r = client.get(f"/api/patients/{pid}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["risk_level"] in {"warning", "critical"}
    assert body["verification_pending"] is True
    assert body["seconds_remaining"] is not None
    assert body["latest_record"]["heart_rate"] == 150


def test_telemetry_for_unknown_patient_404(client):
    r = client.post("/api/telemetry/nope", json={
        "heart_rate": 80, "body_temperature": 36.7,
    })
    assert r.status_code == 404


def test_invalid_telemetry_rejected(client):
    pid = client.post("/api/patients", json={
        "name": "X", "contact_number": "y", "age": 30,
        "height_cm": 170, "weight_kg": 70,
    }).json()["id"]

    # Heart rate way out of physical range — Pydantic validation rejects it
    r = client.post(f"/api/telemetry/{pid}", json={
        "heart_rate": 999, "body_temperature": 36.7,
    })
    assert r.status_code == 422


def test_snapshot_endpoint(client):
    pid = client.post("/api/patients", json={
        "name": "Snap", "contact_number": "y", "age": 40,
        "height_cm": 170, "weight_kg": 70,
    }).json()["id"]

    client.post(f"/api/telemetry/{pid}", json={"heart_rate": 80, "body_temperature": 36.7})
    r = client.get(f"/api/snapshot/{pid}")
    assert r.status_code == 200
    assert r.json()["patient"]["id"] == pid
    assert len(r.json()["recent_records"]) >= 1


def test_force_sos_endpoint(client):
    pid = client.post("/api/patients", json={
        "name": "Escalate", "contact_number": "y", "age": 40,
        "height_cm": 170, "weight_kg": 70,
    }).json()["id"]
    client.post(f"/api/telemetry/{pid}", json={"heart_rate": 145, "body_temperature": 36.7})

    r = client.post(f"/api/sos/{pid}/force")
    assert r.status_code == 200
    assert r.json()["patient"]["id"] == pid

    status = client.get(f"/api/patients/{pid}/status").json()
    assert status["sos_active"] is True
    assert status["call_attempted"] is True


def test_register_family_member(client):
    pid = client.post("/api/patients", json={
        "name": "Fam", "contact_number": "y", "age": 50,
        "height_cm": 170, "weight_kg": 70,
    }).json()["id"]

    r = client.post("/api/family", json={
        "name": "Daughter",
        "contact_number": "+90-555-9999",
        "relationship": "daughter",
        "patient_id": pid,
    })
    assert r.status_code == 201
    assert r.json()["patient_id"] == pid


def test_seed_demo_creates_complete_scenario(client):
    r = client.post("/api/demo/seed")
    assert r.status_code == 201
    patient = r.json()
    assert patient["name"] == "Ahmet Yilmaz"
    assert patient["doctor_id"] is not None

    family = client.get(f"/api/family/{patient['id']}").json()
    records = client.get(f"/api/records/{patient['id']}").json()
    events = client.get(f"/api/events/{patient['id']}").json()
    assert len(family) == 1
    assert len(records) >= 5
    assert any(e["type"] == "threshold_breach" for e in events)
