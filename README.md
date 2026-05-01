---
title: VitalSense
emoji: 🫀
colorFrom: red
colorTo: blue
sdk: docker
pinned: false
---

# VitalSense

> Transforming passive wearable data into active, life-saving protection.

VitalSense is a real-time health monitoring system that bridges wearable telemetry (heart rate, body temperature) with automated emergency response. When a patient's vitals breach personalized thresholds, the system sends a verification prompt; if no response arrives in time, it automatically alerts family members and shares a health snapshot with the on-call doctor.

**Team Vital** — Sida Kılıçaslan, Onur Ateş, Şeref Çimen, Hasan Deniz Karagöl

---

## Architecture at a glance

- **Event-driven core** — telemetry streams flow into the `AnomalyDetectionEngine`, which routes critical events to the `SOSService`.
- **Layered profile management** — users, doctors, family, and threshold configuration go through a standard service/repository layer.
- **Adapter pattern for wearables** — Apple, Samsung, and simulated BLE watches are normalized behind the `StandardWearable` interface, so the engine never touches vendor-specific SDKs.
- **Firebase Firestore** for persistence (with an in-memory fallback so the project runs without credentials).
- **FastAPI** REST API + a minimal HTML/JS dashboard.

```
Wearable ──▶ Adapter ──▶ AnomalyEngine ──▶ (verify) ──▶ SOSService ──▶ Family SMS + Doctor Snapshot
                                │
                                ▼
                           Firestore
```

## Project layout

```
vitalsense/
├── app/
│   ├── adapters/          # StandardWearable + Apple/Samsung/Simulated adapters
│   ├── core/              # AnomalyDetectionEngine, thresholds, verification
│   ├── models/            # Pydantic models: User, Patient, Doctor, HealthRecord...
│   ├── services/          # SOSService, NotificationService, PatientService
│   ├── db/                # Firestore client + in-memory fallback
│   ├── api/               # FastAPI routes
│   ├── templates/         # Dashboard HTML
│   ├── static/            # Dashboard CSS/JS
│   └── main.py            # FastAPI entrypoint
├── tests/                 # pytest suite
├── scripts/
│   ├── demo.py            # End-to-end SOS demo (Ahmet's scenario)
│   ├── scenario_runner.py # Deterministic core scenarios
│   ├── export_snapshot.py # JSON doctor handoff payload exporter
│   └── load_simulation.py # Telemetry burst/load simulation
├── requirements.txt
└── README.md
```

## Quick start

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Run the demo (no Firebase needed — uses in-memory store)
python scripts/demo.py

# Optional: run deterministic scenarios and tooling
python scripts/scenario_runner.py timeout
python scripts/export_snapshot.py fever --output /tmp/fever-snapshot.json
python scripts/load_simulation.py --readings 1000 --spike-every 25

# 3. Run the tests
pytest -v

# 4. Start the API + dashboard
uvicorn app.main:app --reload
# open http://localhost:8000
```

## Firebase setup (optional)

The project runs out-of-the-box with an in-memory store. To use real Firestore:

1. Create a Firebase project at https://console.firebase.google.com
2. Generate a service account key (Project Settings → Service Accounts).
3. Save the JSON as `firebase-credentials.json` at the repo root, or set:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
   export VITALSENSE_USE_FIRESTORE=1
   ```

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/patients` | Register a patient |
| `GET`  | `/api/patients/{id}` | Fetch profile + thresholds |
| `PUT`  | `/api/patients/{id}/thresholds` | Update personalized thresholds |
| `POST` | `/api/telemetry/{patient_id}` | Push a vitals reading from a wearable |
| `POST` | `/api/verify/{patient_id}` | Patient confirms they're OK |
| `GET`  | `/api/snapshot/{patient_id}` | Doctor pulls a health snapshot |
| `GET`  | `/api/events/{patient_id}` | Recent anomaly/SOS events |

## Selected design pattern: Adapter

The `StandardWearable` interface defines `get_heart_rate()` and `get_temperature()`. Concrete adapters wrap vendor APIs with incompatible method names (`fetch_pulse`, `read_heart_sensor`, `fetch_raw_sensor_data`) and translate them into the standard form. Adding a new device is a one-class change — the engine code stays untouched.

## Testing

```bash
pytest                  # full suite
pytest -v --tb=short    # verbose
pytest tests/test_anomaly_engine.py  # single file
```

The suite covers: adapter conformance, threshold evaluation, verification timeout, SOS flow, and API routes.

See `docs/DEMO_TOOLS.md` for the full demo/tooling guide.
