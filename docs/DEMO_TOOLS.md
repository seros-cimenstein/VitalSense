# Demo and Development Tools

VitalSense includes small command-line tools for exercising the system without
starting FastAPI or configuring Firebase. They all use the in-memory repository
and are safe to run locally.

## End-to-end demo

```bash
python scripts/demo.py
```

Runs Ahmet's SOS story with a short real timer:

- creates a patient, family contact, and on-call doctor
- pushes normal telemetry
- pushes a heart-rate spike
- waits for the verification timeout
- prints the SOS audit trail and doctor snapshot

Use this when presenting the full narrative flow.

## Deterministic scenario runner

```bash
python scripts/scenario_runner.py
python scripts/scenario_runner.py normal confirm timeout fever
```

Runs repeatable engine scenarios with a manual timer. This makes it useful for
quick local checks because timeout scenarios finish immediately.

Scenarios:

| Scenario | Behavior |
|---|---|
| `normal` | One healthy reading, no events. |
| `confirm` | Threshold breach, verification sent, patient confirms. |
| `timeout` | Heart-rate breach, verification times out, SOS fires. |
| `fever` | Temperature breach, verification times out, SOS fires. |

## Snapshot exporter

```bash
python scripts/export_snapshot.py timeout
python scripts/export_snapshot.py fever --output /tmp/fever-snapshot.json
```

Exports a JSON doctor handoff payload containing:

- patient profile and thresholds
- doctor and family contacts
- latest health snapshot
- audit events
- notification attempts
- pending verification state

Use this when you need a sample payload for demos, frontend work, or external
API consumers.

## Load simulation

```bash
python scripts/load_simulation.py
python scripts/load_simulation.py --readings 1000 --spike-every 25
python scripts/load_simulation.py --readings 80 --spike-every 20 --no-timeout
```

Pushes a deterministic burst of telemetry through the core engine and prints a
summary:

- total readings
- elapsed seconds and readings per second
- records stored
- total events
- threshold breaches
- SOS escalations
- notification attempts
- pending verification state

Use `--no-timeout` when you want to inspect the behavior of a still-pending
verification window.
