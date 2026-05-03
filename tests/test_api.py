"""HTTP API tests — exercise the FastAPI surface end-to-end."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_sos, reset_graph
from app.auth import DEMO_PATIENT_ID, create_access_token, create_snapshot_access_token
from app.db.repository import reset_repository
from app.main import app


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    """Reset the repo + DI graph before every test so they don't share data."""
    monkeypatch.setenv("VITALSENSE_REPOSITORY", "memory")
    reset_repository()
    reset_graph()
    yield
    reset_repository()
    reset_graph()


@pytest.fixture
def auth_headers():
    token = create_access_token("admin")
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def client(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=auth_headers,
    ) as test_client:
        yield test_client


async def create_patient(client: AsyncClient, **overrides) -> str:
    body = {
        "name": "X",
        "contact_number": "y",
        "age": 30,
        "height_cm": 170,
        "weight_kg": 70,
    }
    body.update(overrides)
    response = await client.post("/api/patients", json=body)
    assert response.status_code == 201
    return response.json()["id"]


async def login_as(username: str, password: str) -> dict:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as public_client:
        response = await public_client.post(
            "/api/auth/login",
            data={"username": username, "password": password},
        )
    assert response.status_code == 200
    return response.json()


def headers_for(token_response: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_response['access_token']}"}


@pytest.mark.asyncio
async def test_health_endpoint(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_dashboard_serves_html(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "VitalSense" in r.text


@pytest.mark.asyncio
async def test_auth_login_flow():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as public_client:
        denied = await public_client.get("/api/patients")
        assert denied.status_code == 401

        login = await public_client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "admin"},
        )
        assert login.status_code == 200
        assert login.json()["role"] == "admin"
        token = login.json()["access_token"]

        allowed = await public_client.get(
            "/api/patients",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert allowed.status_code == 200
        assert allowed.json() == []


@pytest.mark.asyncio
async def test_role_logins_return_scoped_profiles():
    expected = {
        "admin": {"password": "admin", "role": "admin", "patient_id": None},
        "patient": {"password": "patient", "role": "patient", "patient_id": DEMO_PATIENT_ID},
        "doctor": {"password": "doctor", "role": "doctor", "patient_id": None},
        "relative": {"password": "relative", "role": "family", "patient_id": DEMO_PATIENT_ID},
    }

    for username, details in expected.items():
        auth = await login_as(username, details["password"])
        assert auth["username"] == username
        assert auth["role"] == details["role"]
        assert auth["patient_id"] == details["patient_id"]

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers_for(auth),
        ) as scoped_client:
            me = await scoped_client.get("/api/auth/me")
            assert me.status_code == 200
            assert me.json()["role"] == details["role"]


@pytest.mark.asyncio
async def test_patient_login_sees_only_linked_demo_patient():
    patient_auth = await login_as("patient", "patient")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers_for(patient_auth),
    ) as patient_client:
        seeded = await patient_client.post("/api/demo/seed")
        assert seeded.status_code == 201

        patients = await patient_client.get("/api/patients")
        assert patients.status_code == 200
        assert [p["id"] for p in patients.json()] == [DEMO_PATIENT_ID]

        denied = await patient_client.post("/api/patients", json={
            "name": "Private",
            "contact_number": "+90-555-1212",
            "age": 44,
            "height_cm": 170,
            "weight_kg": 70,
        })
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_doctor_login_can_tune_assigned_patient_only():
    doctor_auth = await login_as("doctor", "doctor")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers_for(doctor_auth),
    ) as doctor_client:
        seeded = await doctor_client.post("/api/demo/seed")
        assert seeded.status_code == 201

        r = await doctor_client.put(f"/api/patients/{DEMO_PATIENT_ID}/thresholds", json={
            "heart_rate_min": 58,
            "heart_rate_max": 118,
            "temperature_min": 36.0,
            "temperature_max": 38.3,
        })
        assert r.status_code == 200
        assert r.json()["thresholds"]["heart_rate_min"] == 58

        denied = await doctor_client.post("/api/doctors", json={
            "name": "Dr. Other",
            "contact_number": "+90-555-3333",
            "specialty": "Neurology",
        })
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_relative_login_is_read_only_for_linked_patient():
    relative_auth = await login_as("relative", "relative")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers=headers_for(relative_auth),
    ) as relative_client:
        seeded = await relative_client.post("/api/demo/seed")
        assert seeded.status_code == 201

        status_response = await relative_client.get(f"/api/patients/{DEMO_PATIENT_ID}/status")
        assert status_response.status_code == 200

        telemetry = await relative_client.post(f"/api/telemetry/{DEMO_PATIENT_ID}", json={
            "heart_rate": 80,
            "body_temperature": 36.7,
        })
        assert telemetry.status_code == 403

        verify = await relative_client.post(f"/api/verify/{DEMO_PATIENT_ID}")
        assert verify.status_code == 403


@pytest.mark.asyncio
async def test_create_and_get_patient(client):
    r = await client.post("/api/patients", json={
        "name": "Selin Aydın",
        "contact_number": "+90-555-1000",
        "age": 28,
        "height_cm": 168.0,
        "weight_kg": 60.0,
    })
    assert r.status_code == 201
    pid = r.json()["id"]

    r = await client.get(f"/api/patients/{pid}")
    assert r.status_code == 200
    assert r.json()["name"] == "Selin Aydın"


@pytest.mark.asyncio
async def test_get_unknown_patient_404(client):
    r = await client.get("/api/patients/does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_thresholds(client):
    pid = await create_patient(client)

    r = await client.put(f"/api/patients/{pid}/thresholds", json={
        "heart_rate_min": 60,
        "heart_rate_max": 110,
        "temperature_min": 36.0,
        "temperature_max": 38.0,
    })
    assert r.status_code == 200
    assert r.json()["thresholds"]["heart_rate_max"] == 110


@pytest.mark.asyncio
async def test_telemetry_normal_path(client):
    pid = await create_patient(client)

    r = await client.post(f"/api/telemetry/{pid}", json={
        "heart_rate": 80,
        "body_temperature": 36.7,
        "daily_steps": 100,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["breach"] is False
    assert body["verification_pending"] is False


@pytest.mark.asyncio
async def test_telemetry_breach_starts_verification(client):
    pid = await create_patient(client)

    r = await client.post(f"/api/telemetry/{pid}", json={
        "heart_rate": 160,
        "body_temperature": 36.7,
    })
    body = r.json()
    assert body["breach"] is True
    assert body["verification_pending"] is True

    r = await client.post(f"/api/verify/{pid}")
    assert r.json() == {"confirmed": True}


@pytest.mark.asyncio
async def test_patient_status_reports_risk_and_countdown(client):
    pid = await create_patient(client, name="Risk")

    await client.post(f"/api/telemetry/{pid}", json={
        "heart_rate": 150,
        "body_temperature": 36.7,
    })

    r = await client.get(f"/api/patients/{pid}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["risk_level"] in {"warning", "critical"}
    assert body["verification_pending"] is True
    assert body["seconds_remaining"] is not None
    assert body["latest_record"]["heart_rate"] == 150


@pytest.mark.asyncio
async def test_patient_export_contains_linked_data(client):
    doctor_response = await client.post("/api/doctors", json={
        "name": "Dr. Export",
        "contact_number": "+90-555-4444",
        "specialty": "Internal Medicine",
    })
    assert doctor_response.status_code == 201
    doctor_id = doctor_response.json()["id"]
    pid = await create_patient(client, name="Export", doctor_id=doctor_id)

    await client.post("/api/family", json={
        "name": "Relative Export",
        "contact_number": "+90-555-9999",
        "relationship": "son",
        "patient_id": pid,
    })
    await client.post(f"/api/telemetry/{pid}", json={
        "heart_rate": 150,
        "body_temperature": 36.7,
    })

    r = await client.get(f"/api/patients/{pid}/export")
    assert r.status_code == 200
    body = r.json()
    assert body["patient"]["id"] == pid
    assert body["doctor"]["id"] == doctor_id
    assert len(body["family"]) == 1
    assert len(body["recent_records"]) == 1
    assert any(e["type"] == "threshold_breach" for e in body["recent_events"])


@pytest.mark.asyncio
async def test_sos_snapshot_base_url_can_be_configured(client, monkeypatch):
    monkeypatch.setenv("VITALSENSE_SNAPSHOT_BASE_URL", "https://example.test/snapshots")
    reset_graph()
    sos = await get_sos()
    assert sos._snapshot_base_url == "https://example.test/snapshots"


@pytest.mark.asyncio
async def test_telemetry_for_unknown_patient_404(client):
    r = await client.post("/api/telemetry/nope", json={
        "heart_rate": 80,
        "body_temperature": 36.7,
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_invalid_telemetry_rejected(client):
    pid = await create_patient(client)

    r = await client.post(f"/api/telemetry/{pid}", json={
        "heart_rate": 999,
        "body_temperature": 36.7,
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_snapshot_endpoint(client):
    pid = await create_patient(client, name="Snap", age=40)

    await client.post(
        f"/api/telemetry/{pid}",
        json={"heart_rate": 80, "body_temperature": 36.7},
    )
    r = await client.get(f"/api/snapshot/{pid}")
    assert r.status_code == 200
    assert r.json()["patient"]["id"] == pid
    assert len(r.json()["recent_records"]) >= 1


@pytest.mark.asyncio
async def test_shared_snapshot_requires_valid_token(client):
    pid = await create_patient(client, name="Shared Snap", age=40)
    await client.post(
        f"/api/telemetry/{pid}",
        json={"heart_rate": 82, "body_temperature": 36.8},
    )

    token = create_snapshot_access_token(pid)
    wrong_patient_token = create_snapshot_access_token("different-patient")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as public_client:
        denied = await public_client.get(
            f"/api/snapshot/{pid}/shared",
            params={"token": wrong_patient_token},
        )
        assert denied.status_code == 401

        allowed = await public_client.get(
            f"/api/snapshot/{pid}/shared",
            params={"token": token},
        )
        assert allowed.status_code == 200
        assert allowed.json()["patient"]["id"] == pid

        page = await public_client.get(f"/doctor/snapshot/{pid}", params={"token": token})
        assert page.status_code == 200
        assert "doctor handoff" in page.text


@pytest.mark.asyncio
async def test_wearable_device_ingestion_uses_device_key(client, monkeypatch):
    monkeypatch.setenv("VITALSENSE_DEVICE_API_KEY", "device-secret")
    pid = await create_patient(client, name="Device")

    payload = {
        "heart_rate": 150,
        "body_temperature": 36.7,
        "daily_steps": 420,
    }
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as public_client:
        missing = await public_client.post(f"/api/wearable/{pid}/telemetry", json=payload)
        assert missing.status_code == 401

        wrong = await public_client.post(
            f"/api/wearable/{pid}/telemetry",
            json=payload,
            headers={"X-VitalSense-Device-Key": "wrong"},
        )
        assert wrong.status_code == 403

        ok = await public_client.post(
            f"/api/wearable/{pid}/telemetry",
            json=payload,
            headers={"X-VitalSense-Device-Key": "device-secret"},
        )
        assert ok.status_code == 200
        body = ok.json()
        assert body["source"] == "wearable_device_bridge"
        assert body["breach"] is True
        assert body["verification_pending"] is True


@pytest.mark.asyncio
async def test_force_sos_endpoint(client):
    pid = await create_patient(client, name="Escalate", age=40)
    await client.post(
        f"/api/telemetry/{pid}",
        json={"heart_rate": 145, "body_temperature": 36.7},
    )

    r = await client.post(f"/api/sos/{pid}/force")
    assert r.status_code == 200
    assert r.json()["patient"]["id"] == pid

    status = (await client.get(f"/api/patients/{pid}/status")).json()
    assert status["sos_active"] is True
    assert status["call_attempted"] is True


@pytest.mark.asyncio
async def test_register_family_member(client):
    pid = await create_patient(client, name="Fam", age=50)

    r = await client.post("/api/family", json={
        "name": "Daughter",
        "contact_number": "+90-555-9999",
        "relationship": "daughter",
        "patient_id": pid,
    })
    assert r.status_code == 201
    assert r.json()["patient_id"] == pid


@pytest.mark.asyncio
async def test_seed_demo_creates_complete_scenario(client):
    r = await client.post("/api/demo/seed")
    assert r.status_code == 201
    patient = r.json()
    assert patient["name"] == "Ahmet Yilmaz"
    assert patient["doctor_id"] is not None

    family = (await client.get(f"/api/family/{patient['id']}")).json()
    records = (await client.get(f"/api/records/{patient['id']}")).json()
    events = (await client.get(f"/api/events/{patient['id']}")).json()
    assert len(family) == 1
    assert len(records) >= 5
    assert any(e["type"] == "threshold_breach" for e in events)
