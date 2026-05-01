/* VitalSense dashboard — vanilla JS client. */

const api = {
  async get(path) {
    const r = await fetch(`/api${path}`);
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`${r.status} ${path}: ${text}`);
    }
    return r.json();
  },
  async put(path, body) {
    const r = await fetch(`/api${path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  },
};

// state
let activePatient = null;
let pollHandle = null;

// element refs
const $ = (id) => document.getElementById(id);
const patientList = $("patient-list");
const emptyState = $("empty-state");
const patientView = $("patient-view");
const thresholdCard = $("threshold-card");
const verBanner = $("verification-banner");

// ----- patients ---------------------------------------------------------

async function refreshPatients() {
  const patients = await api.get("/patients");
  patientList.innerHTML = "";
  if (!patients.length) {
    patientList.innerHTML = `<li class="hint">no patients yet</li>`;
    return;
  }
  for (const p of patients) {
    const li = document.createElement("li");
    li.className = "patient-item";
    if (activePatient && p.id === activePatient.id) li.classList.add("active");
    li.innerHTML = `
      <div>
        <div class="pi-name">${escapeHtml(p.name)}</div>
        <div class="pi-meta">${p.age}y · ${p.location || "—"}</div>
      </div>
    `;
    li.addEventListener("click", () => selectPatient(p.id));
    patientList.appendChild(li);
  }
}

async function selectPatient(id) {
  activePatient = await api.get(`/patients/${id}`);
  emptyState.hidden = true;
  patientView.hidden = false;
  thresholdCard.hidden = false;
  await refreshPatients();
  renderPatient();
  await refreshTimeline();
  startPolling();
}

function renderPatient() {
  const p = activePatient;
  $("patient-name").textContent = p.name;
  $("patient-meta").textContent =
    `${p.age}y · ${p.height_cm}cm · ${p.weight_kg}kg · ${p.location || "—"}`;
  // BMI calc client-side (matches Patient.bmi)
  const h = p.height_cm / 100;
  const bmi = h > 0 ? (p.weight_kg / (h * h)).toFixed(1) : "—";
  $("patient-bmi").textContent = bmi;

  // thresholds inputs
  $("hr-min").value = p.thresholds.heart_rate_min;
  $("hr-max").value = p.thresholds.heart_rate_max;
  $("t-min").value = p.thresholds.temperature_min;
  $("t-max").value = p.thresholds.temperature_max;
  $("vital-hr-range").textContent =
    `range ${p.thresholds.heart_rate_min}–${p.thresholds.heart_rate_max} bpm`;
  $("vital-temp-range").textContent =
    `range ${p.thresholds.temperature_min}–${p.thresholds.temperature_max} °C`;
}

// ----- timeline + vitals ------------------------------------------------

async function refreshTimeline() {
  if (!activePatient) return;

  const [events, records] = await Promise.all([
    api.get(`/events/${activePatient.id}?limit=30`),
    api.get(`/records/${activePatient.id}?limit=1`),
  ]);

  // latest record drives vital cards
  if (records.length) {
    const r = records[0];
    $("vital-hr").textContent = r.heart_rate;
    $("vital-temp").textContent = r.body_temperature.toFixed(1);
    $("vital-steps").textContent = r.daily_steps;

    const t = activePatient.thresholds;
    document.querySelectorAll(".vital-card").forEach((c) => c.classList.remove("breach"));
    const hrBreach = r.heart_rate < t.heart_rate_min || r.heart_rate > t.heart_rate_max;
    const tempBreach = r.body_temperature < t.temperature_min || r.body_temperature > t.temperature_max;
    if (hrBreach) document.querySelectorAll(".vital-card")[0].classList.add("breach");
    if (tempBreach) document.querySelectorAll(".vital-card")[1].classList.add("breach");
  }

  // verification pending?
  const pending = events.find((e) => e.type === "verification_sent");
  const confirmed = events.find((e) => e.type === "verification_confirmed");
  const sosFired = events.find((e) => e.type === "sos_triggered");
  // banner shows if the most recent verification_sent is newer than any confirm/sos
  const showBanner =
    pending &&
    (!confirmed || new Date(confirmed.timestamp) < new Date(pending.timestamp)) &&
    (!sosFired || new Date(sosFired.timestamp) < new Date(pending.timestamp));
  verBanner.hidden = !showBanner;

  // status text
  if (sosFired && (!confirmed || new Date(sosFired.timestamp) > new Date(confirmed.timestamp))) {
    $("status-text").textContent = "SOS active";
  } else if (showBanner) {
    $("status-text").textContent = "awaiting verification";
  } else {
    $("status-text").textContent = "monitoring";
  }

  // event list
  const list = $("event-list");
  list.innerHTML = "";
  $("event-count").textContent = `${events.length} events`;
  for (const e of events) {
    const li = document.createElement("li");
    const klass = eventClass(e.type);
    li.className = `event-item ${klass}`;
    const time = new Date(e.timestamp).toLocaleTimeString();
    li.innerHTML = `
      <span class="event-time">${time}</span>
      <span class="event-type">${e.type.replace(/_/g, " ")}</span>
      <span>${escapeHtml(e.message)}</span>
    `;
    list.appendChild(li);
  }
}

function eventClass(type) {
  if (["sos_triggered", "threshold_breach", "family_notified", "doctor_notified"].includes(type))
    return "ev-warn";
  if (type === "verification_confirmed") return "ev-ok";
  return "";
}

function startPolling() {
  if (pollHandle) clearInterval(pollHandle);
  pollHandle = setInterval(refreshTimeline, 2000);
}

// ----- actions ----------------------------------------------------------

$("save-thresholds").addEventListener("click", async () => {
  if (!activePatient) return;
  const body = {
    heart_rate_min: parseInt($("hr-min").value, 10),
    heart_rate_max: parseInt($("hr-max").value, 10),
    temperature_min: parseFloat($("t-min").value),
    temperature_max: parseFloat($("t-max").value),
  };
  activePatient = await api.put(`/patients/${activePatient.id}/thresholds`, body);
  renderPatient();
});

$("push-telemetry").addEventListener("click", async () => {
  if (!activePatient) return;
  const body = {
    heart_rate: parseInt($("sim-hr").value, 10),
    body_temperature: parseFloat($("sim-temp").value),
    daily_steps: parseInt($("sim-steps").value || "0", 10),
  };
  await api.post(`/telemetry/${activePatient.id}`, body);
  await refreshTimeline();
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    $("sim-hr").value = chip.dataset.hr;
    $("sim-temp").value = chip.dataset.temp;
  });
});

$("confirm-ok").addEventListener("click", async () => {
  if (!activePatient) return;
  await api.post(`/verify/${activePatient.id}`);
  await refreshTimeline();
});

// ----- new patient modal ------------------------------------------------

$("new-patient-btn").addEventListener("click", () => {
  $("modal-overlay").hidden = false;
});
$("modal-close").addEventListener("click", () => {
  $("modal-overlay").hidden = true;
});
$("np-save").addEventListener("click", async () => {
  const body = {
    name: $("np-name").value,
    contact_number: $("np-phone").value,
    location: $("np-location").value || null,
    age: parseInt($("np-age").value, 10),
    height_cm: parseFloat($("np-height").value),
    weight_kg: parseFloat($("np-weight").value),
  };
  if (!body.name || !body.contact_number || !body.age) {
    alert("name, phone, and age are required");
    return;
  }
  const created = await api.post("/patients", body);
  $("modal-overlay").hidden = true;
  ["np-name", "np-phone", "np-location", "np-age", "np-height", "np-weight"].forEach(
    (id) => ($(id).value = "")
  );
  await refreshPatients();
  await selectPatient(created.id);
});

// ----- utils ------------------------------------------------------------

function escapeHtml(str) {
  if (str == null) return "";
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

// ----- boot -------------------------------------------------------------

refreshPatients();
