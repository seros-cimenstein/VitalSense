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
- **Adapter pattern for wearables** — Apple, Samsung, simulated BLE watches, and external device bridge payloads are normalized before reaching the anomaly engine.
- **SQLite** for default persistence, with optional Firebase Firestore and in-memory backends.
- **FastAPI** REST API + a minimal HTML/JS dashboard.

```
Wearable ──▶ Adapter ──▶ AnomalyEngine ──▶ (verify) ──▶ SOSService ──▶ Family SMS + Doctor Snapshot
                                │
                                ▼
                           SQLite / Firestore
```

## Project layout

```
vitalsense/
├── app/
│   ├── adapters/          # StandardWearable + Apple/Samsung/Simulated adapters
│   ├── core/              # AnomalyDetectionEngine, thresholds, verification
│   ├── models/            # Pydantic models: User, Patient, Doctor, HealthRecord...
│   ├── services/          # SOSService, NotificationService, PatientService
│   ├── db/                # SQLite, Firestore, and in-memory repositories
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

Default demo logins:

| Role | Username | Password | Access |
|---|---|---|---|
| Admin | `admin` | `admin` | Full patient, doctor, family, threshold, and demo controls |
| Patient | `patient` | `patient` | Linked patient view, verification, telemetry demo, SOS |
| Doctor | `doctor` | `doctor` | Assigned patient monitoring, threshold tuning, SOS |
| Relative | `relative` | `relative` | Read-only linked patient monitoring |

## Data persistence

VitalSense uses SQLite by default and stores data at `data/vitalsense.db`.
Set `VITALSENSE_DB_PATH` to choose another file. On hosted environments with
persistent storage, point it at that mounted volume, for example:

```bash
export VITALSENSE_DB_PATH=/data/vitalsense.db
```

Available repository backends:

```bash
export VITALSENSE_REPOSITORY=sqlite     # default
export VITALSENSE_REPOSITORY=memory     # ephemeral demos/tests
export VITALSENSE_REPOSITORY=firestore  # Firebase backend
```

The dashboard also has an `export` button on each patient profile. It downloads
a JSON bundle containing the patient profile, assigned doctor, relatives, recent
telemetry records, and recent events.

Doctor SOS notifications include a signed patient snapshot link. Set this in
production if the app is deployed somewhere else:

```bash
export VITALSENSE_SNAPSHOT_BASE_URL=https://your-domain.example/doctor/snapshot
```

External wearable or mobile bridge ingestion uses a device API key. Change the
default before exposing the bridge beyond a classroom demo:

```bash
export VITALSENSE_DEVICE_API_KEY=replace-with-a-random-secret
```

## Firebase setup (optional)

The project runs out-of-the-box with SQLite. To use real Firestore:

1. Create a Firebase project at https://console.firebase.google.com
2. Generate a service account key (Project Settings → Service Accounts).
3. Save the JSON as `firebase-credentials.json` at the repo root, or set:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
   export VITALSENSE_REPOSITORY=firestore
   ```

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/patients` | Register a patient |
| `GET`  | `/api/patients/{id}` | Fetch profile + thresholds |
| `GET`  | `/api/patients/{id}/export` | Export patient profile, contacts, records, and events |
| `PUT`  | `/api/patients/{id}/thresholds` | Update personalized thresholds |
| `POST` | `/api/telemetry/{patient_id}` | Push a vitals reading from a wearable |
| `POST` | `/api/wearable/{patient_id}/telemetry` | Push device telemetry with `X-VitalSense-Device-Key` |
| `POST` | `/api/verify/{patient_id}` | Patient confirms they're OK |
| `GET`  | `/api/snapshot/{patient_id}` | Doctor pulls a health snapshot |
| `GET`  | `/api/snapshot/{patient_id}/shared` | Tokenized snapshot payload for SOS doctor links |
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

See `docs/MIDTERM_DELIVERABLES.md` for the midterm report checklist,
diagram drafts, user stories, and presentation outline.

See `docs/AI_CHAT.md` for the proposed AI health chat integration plan.
