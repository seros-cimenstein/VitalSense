# Architecture: how the code maps to the progress report

This doc walks through each section of the progress report and points to the
files that implement it.

## §1.3 — Architecture diagrams

The hybrid event-driven + layered architecture maps to:

| Report component | Code |
|---|---|
| Event Producers (Smartwatches, simulators) | `app/adapters/` (Apple, Samsung, Simulated) |
| Event Router (Anomaly Detection Engine) | `app/core/anomaly_engine.py` |
| Event Consumers (SOS, Doctor Connect) | `app/services/sos_service.py`, `app/services/notification_service.py` |
| Data Storage (Firebase / PostgreSQL) | `app/db/repository.py` (`FirestoreRepository`, `InMemoryRepository`) |
| Layered Architecture (User/Profile Service) | `app/api/routes.py` + `app/db/repository.py` (patient/doctor/family CRUD) |
| API Gateway | `app/main.py` + `app/api/routes.py` (FastAPI) |

## §1.4 — UML class diagram

| Class in diagram | Module |
|---|---|
| `User` (abstract) | `app/models/__init__.py` |
| `Patient` | `app/models/__init__.py` (with `bmi` property) |
| `Doctor` | `app/models/__init__.py` |
| `FamilyMember` | `app/models/__init__.py` |
| `WearableDevice` (interface) | `app/adapters/base.py` (`StandardWearable`) |
| `HealthRecord` | `app/models/__init__.py` |
| `PersonalizedThresholds` | `app/models/__init__.py` |
| `AnomalyDetectionEngine` | `app/core/anomaly_engine.py` |
| `SOSService` | `app/services/sos_service.py` |

## §1.4 — Sequence diagram

The "Wearable → App → Engine → SOS → Family/Doctor" flow plays out in:

1. `AnomalyDetectionEngine.process_record` — receives the telemetry, persists, evaluates.
2. `_on_breach` — logs `THRESHOLD_BREACH` + `VERIFICATION_SENT`, starts the timer.
3. `confirm_verification` — patient says "I'm OK"; cancels the timer; logs `VERIFICATION_CONFIRMED`.
4. `_on_timeout` (if no confirmation) — calls `SOSService.initiate_emergency_protocol`.
5. `SOSService` — notifies family (SMS), notifies on-call doctor (snapshot link), logs every step.

The end-to-end run is in `scripts/demo.py`.

## §1.5 — Adapter pattern

The report's UML for the Adapter pattern maps 1:1:

| Report | Code |
|---|---|
| `StandardWearable` (target interface) | `app/adapters/base.py::StandardWearable` |
| `AppleHealthAPI` (adaptee) | `app/adapters/apple.py::AppleHealthAPI` (`fetch_pulse`, `read_body_temp`) |
| `SamsungHealthAPI` (adaptee) | `app/adapters/samsung.py::SamsungHealthAPI` (`read_heart_sensor`, `read_temperature_sensor`) |
| `SimulatedBLEWatch` (adaptee) | `app/adapters/simulated.py::SimulatedBLEWatch` (`fetch_raw_sensor_data` returns JSON) |
| `AppleHealthAdapter` | `app/adapters/apple.py::AppleHealthAdapter` |
| `SamsungWatchAdapter` | `app/adapters/samsung.py::SamsungWatchAdapter` |
| `SimulatedWatchAdapter` | `app/adapters/simulated.py::SimulatedWatchAdapter` |

The `VitalSenseClient` in the report's diagram corresponds to the
`AnomalyDetectionEngine`, which only sees the `StandardWearable` interface.
Adding a Garmin (or any other) device is a single new adapter class — zero
changes to the engine.

## Verification window (Ahmet's scenario)

Production default is 60 seconds (`DEFAULT_VERIFICATION_TIMEOUT_SECONDS` in
`app/core/anomaly_engine.py`). Tests pass in a stub `ImmediateTimer` to make
the timeout deterministic. The demo script overrides to 2 seconds so it
finishes quickly.
