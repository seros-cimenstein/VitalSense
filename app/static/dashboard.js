/* VitalSense dashboard — vanilla JS client. */

// ----- auth -----------------------------------------------------------------

const TOKEN_KEY = "vs_token";

function getToken() { return localStorage.getItem(TOKEN_KEY); }

function authHeaders() {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

function handleUnauthorized() {
  localStorage.removeItem(TOKEN_KEY);
  window.location.replace("/login");
}

if (!getToken()) { window.location.replace("/login"); }

// ----- api ------------------------------------------------------------------

const api = {
  async get(path) {
    const r = await fetch(`/api${path}`, { headers: { ...authHeaders() } });
    if (r.status === 401) { handleUnauthorized(); return null; }
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (r.status === 401) { handleUnauthorized(); return null; }
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`${r.status} ${path}: ${text}`);
    }
    return r.json();
  },
  async put(path, body) {
    const r = await fetch(`/api${path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
    });
    if (r.status === 401) { handleUnauthorized(); return null; }
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  },
  async patch(path, body) {
    const r = await fetch(`/api${path}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
    });
    if (r.status === 401) { handleUnauthorized(); return null; }
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  },
  async delete(path) {
    const r = await fetch(`/api${path}`, {
      method: "DELETE",
      headers: { ...authHeaders() },
    });
    if (r.status === 401) { handleUnauthorized(); return; }
    if (!r.ok) throw new Error(`${r.status} ${path}`);
  },
};

// state
let activePatient = null;
let pollHandle = null;
let streamHandle = null;
let countdownHandle = null;
let allDoctors = [];
const STREAM_INTERVAL_MS = 2500;

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
  stopTelemetryStream();
  stopCountdown();
  activePatient = await api.get(`/patients/${id}`);
  emptyState.hidden = true;
  patientView.hidden = false;
  thresholdCard.hidden = false;
  await refreshPatients();
  renderPatient();
  await Promise.all([refreshTimeline(), refreshContacts()]);
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

  const [events, records, status] = await Promise.all([
    api.get(`/events/${activePatient.id}?limit=30`),
    api.get(`/records/${activePatient.id}?limit=30`),
    api.get(`/patients/${activePatient.id}/status`),
  ]);
  renderRiskStatus(status);
  renderTrendChart(records.slice().reverse());

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

  verBanner.hidden = !status.verification_pending;
  if (status.verification_pending) {
    startCountdown(status.verification_deadline);
  } else {
    stopCountdown();
  }

  // status text
  if (status.summary === "SOS escalation is active") {
    $("status-text").textContent = "SOS active";
  } else if (status.risk_level === "critical") {
    $("status-text").textContent = "critical vitals";
  } else if (status.verification_pending) {
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
  await refreshSnapshot();
}

function renderRiskStatus(status) {
  const panel = $("risk-panel");
  panel.classList.remove("risk-normal", "risk-warning", "risk-critical");
  panel.classList.add(`risk-${status.risk_level}`);
  $("risk-level").textContent = status.risk_level;
  $("risk-score").textContent = `${status.risk_score}/100`;
  $("risk-summary").textContent = status.summary;
  $("risk-meter-fill").style.width = `${status.risk_score}%`;
  $("call-state").textContent = status.call_attempted ? "call: placed" : "call: waiting";
  $("family-state").textContent = `family: ${status.family_notifications_sent}`;
  $("doctor-state").textContent = `doctor: ${status.doctor_notifications_sent}`;
}

async function refreshSnapshot() {
  if (!activePatient) return;
  const snapshot = await api.get(`/snapshot/${activePatient.id}`);
  $("snapshot-reason").textContent = snapshot.reason;
  $("snapshot-record-count").textContent = snapshot.recent_records.length;
  $("snapshot-time").textContent = new Date(snapshot.triggered_at).toLocaleTimeString();

  const list = $("snapshot-records");
  list.innerHTML = "";
  const records = snapshot.recent_records.slice(0, 5);
  if (!records.length) {
    list.innerHTML = `<p class="hint">No telemetry records yet.</p>`;
    return;
  }
  for (const record of records) {
    const item = document.createElement("div");
    item.className = "snapshot-record";
    item.innerHTML = `
      <span>${new Date(record.timestamp).toLocaleTimeString()}</span>
      <strong>${record.heart_rate} bpm</strong>
      <strong>${Number(record.body_temperature).toFixed(1)} °C</strong>
      <span>${record.daily_steps} steps</span>
    `;
    list.appendChild(item);
  }
}

function startCountdown(deadline) {
  if (countdownHandle) clearInterval(countdownHandle);
  updateCountdown(deadline);
  countdownHandle = setInterval(() => updateCountdown(deadline), 500);
}

function stopCountdown() {
  if (countdownHandle) clearInterval(countdownHandle);
  countdownHandle = null;
  $("verification-countdown").textContent = "—";
}

function updateCountdown(deadline) {
  if (!deadline) {
    $("verification-countdown").textContent = "verification pending";
    return;
  }
  const remaining = Math.max(0, Math.ceil((new Date(deadline) - new Date()) / 1000));
  $("verification-countdown").textContent = `${remaining}s left before SOS escalation`;
}

function renderTrendChart(records) {
  const canvas = $("trend-chart");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  $("trend-count").textContent = `${records.length} readings`;

  ctx.fillStyle = "#fffaf2";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(26, 42, 46, 0.08)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i += 1) {
    const y = (height / 4) * i;
    ctx.beginPath();
    ctx.moveTo(36, y);
    ctx.lineTo(width - 16, y);
    ctx.stroke();
  }

  if (records.length < 2) {
    ctx.fillStyle = "#8a9396";
    ctx.font = "14px Manrope, sans-serif";
    ctx.fillText("Push or stream telemetry to build a trend.", 36, height / 2);
    return;
  }

  drawSeries(ctx, records, {
    key: "heart_rate",
    color: "#0f4c4f",
    min: 40,
    max: 160,
    top: 22,
    bottom: height - 34,
    left: 36,
    right: width - 18,
  });
  drawSeries(ctx, records, {
    key: "body_temperature",
    color: "#c84a3b",
    min: 35,
    max: 41,
    top: 22,
    bottom: height - 34,
    left: 36,
    right: width - 18,
  });

  ctx.font = "12px Manrope, sans-serif";
  ctx.fillStyle = "#0f4c4f";
  ctx.fillText("Heart rate", 36, 18);
  ctx.fillStyle = "#c84a3b";
  ctx.fillText("Temperature", 120, 18);
}

function drawSeries(ctx, records, opts) {
  const span = Math.max(1, records.length - 1);
  const yFor = (value) => {
    const pct = (clamp(value, opts.min, opts.max) - opts.min) / (opts.max - opts.min);
    return opts.bottom - pct * (opts.bottom - opts.top);
  };
  ctx.strokeStyle = opts.color;
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  records.forEach((record, index) => {
    const x = opts.left + (index / span) * (opts.right - opts.left);
    const y = yFor(record[opts.key]);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = opts.color;
  records.forEach((record, index) => {
    const x = opts.left + (index / span) * (opts.right - opts.left);
    const y = yFor(record[opts.key]);
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  });
}

function eventClass(type) {
  if (["sos_triggered", "threshold_breach", "family_notified", "doctor_notified"].includes(type))
    return "ev-warn";
  if (type === "verification_confirmed") return "ev-ok";
  if (type === "call_attempted") return "ev-call";
  return "";
}

function startPolling() {
  if (pollHandle) clearInterval(pollHandle);
  pollHandle = setInterval(refreshTimeline, 2000);
}

// ----- doctors ----------------------------------------------------------

async function refreshDoctors() {
  allDoctors = await api.get("/doctors");
  const list = $("doctor-list");
  list.innerHTML = "";
  if (!allDoctors.length) {
    list.innerHTML = `<li class="hint" style="padding:6px 0">no doctors registered</li>`;
    return;
  }
  for (const d of allDoctors) {
    const li = document.createElement("li");
    li.className = "contact-item";
    li.innerHTML = `
      <div class="ci-main">
        <span class="ci-name">${escapeHtml(d.name)}</span>
        <span class="ci-badge ci-badge-doctor">doctor</span>
        <button class="ci-remove" title="Delete doctor">×</button>
      </div>
      <div class="ci-meta">${escapeHtml(d.specialty)}${d.on_call_status ? ' · <span class="oncall-pill">on-call</span>' : ''}</div>
      <div class="ci-phone">${escapeHtml(d.contact_number)}</div>
    `;
    li.querySelector(".ci-remove").addEventListener("click", async () => {
      if (!confirm(`Delete Dr. ${d.name}? This cannot be undone.`)) return;
      await api.delete(`/doctors/${d.id}`);
      await refreshDoctors();
      if (activePatient) await refreshContacts();
    });
    list.appendChild(li);
  }
}

function populateDoctorSelect() {
  const sel = $("np-doctor");
  sel.innerHTML = `<option value="">— none —</option>`;
  for (const d of allDoctors) {
    const opt = document.createElement("option");
    opt.value = d.id;
    opt.textContent = `${d.name} · ${d.specialty}`;
    sel.appendChild(opt);
  }
}

// ----- contacts (per patient) -------------------------------------------

async function refreshContacts() {
  if (!activePatient) return;
  const family = await api.get(`/family/${activePatient.id}`);
  const content = $("contacts-content");
  content.innerHTML = "";

  const doctor = allDoctors.find((d) => d.id === activePatient.doctor_id);

  if (doctor) {
    content.appendChild(doctorContactCard(doctor));
  } else {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No doctor assigned.";
    content.appendChild(p);
  }

  for (const m of family) {
    content.appendChild(familyContactCard(m));
  }

  if (!doctor && !family.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.style.marginTop = "4px";
    p.textContent = "No contacts linked yet. Use the buttons above to add.";
    content.appendChild(p);
  }
}

function doctorContactCard(doctor) {
  const div = document.createElement("div");
  div.className = "contact-item";
  div.innerHTML = `
    <div class="ci-main">
      <span class="ci-name">${escapeHtml(doctor.name)}</span>
      <span class="ci-badge ci-badge-doctor">doctor</span>
      <button class="ci-remove" title="Unassign doctor">×</button>
    </div>
    <div class="ci-meta">${escapeHtml(doctor.specialty)}${doctor.on_call_status ? ' · <span class="oncall-pill">on-call</span>' : ''}</div>
    <div class="ci-phone">${escapeHtml(doctor.contact_number)}</div>
  `;
  div.querySelector(".ci-remove").addEventListener("click", async () => {
    if (!confirm(`Unassign Dr. ${doctor.name} from this patient?`)) return;
    activePatient = await api.patch(`/patients/${activePatient.id}/doctor`, { doctor_id: null });
    await refreshContacts();
  });
  return div;
}

function familyContactCard(member) {
  const div = document.createElement("div");
  div.className = "contact-item";
  div.innerHTML = `
    <div class="ci-main">
      <span class="ci-name">${escapeHtml(member.name)}</span>
      <span class="ci-badge ci-badge-family">family</span>
      <button class="ci-remove" title="Remove">×</button>
    </div>
    <div class="ci-meta">${escapeHtml(member.relationship)}</div>
    <div class="ci-phone">${escapeHtml(member.contact_number)}</div>
  `;
  div.querySelector(".ci-remove").addEventListener("click", async () => {
    if (!confirm(`Remove ${member.name}?`)) return;
    await api.delete(`/family/${member.id}`);
    await refreshContacts();
  });
  return div;
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
  await pushSimulatedReading({ jitter: false });
});

$("stream-telemetry").addEventListener("click", () => {
  if (!activePatient) return;
  if (streamHandle) {
    stopTelemetryStream();
  } else {
    startTelemetryStream();
  }
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    $("sim-hr").value = chip.dataset.hr;
    $("sim-temp").value = chip.dataset.temp;
  });
});

function startTelemetryStream() {
  pushSimulatedReading({ jitter: true });
  streamHandle = setInterval(() => pushSimulatedReading({ jitter: true }), STREAM_INTERVAL_MS);
  $("stream-telemetry").textContent = "stop stream";
  $("push-telemetry").disabled = true;
  document.querySelector(".simulator-actions").classList.add("streaming");
}

function stopTelemetryStream() {
  if (!streamHandle) return;
  clearInterval(streamHandle);
  streamHandle = null;
  $("stream-telemetry").textContent = "start stream";
  $("push-telemetry").disabled = false;
  document.querySelector(".simulator-actions").classList.remove("streaming");
}

async function pushSimulatedReading({ jitter }) {
  if (!activePatient) return;

  const body = buildSimulatedReading(jitter);
  await api.post(`/telemetry/${activePatient.id}`, body);

  $("sim-hr").value = body.heart_rate;
  $("sim-temp").value = body.body_temperature.toFixed(1);
  $("sim-steps").value = body.daily_steps;
  await refreshTimeline();
}

function buildSimulatedReading(jitter) {
  const baseHr = parseInt($("sim-hr").value, 10);
  const baseTemp = parseFloat($("sim-temp").value);
  const baseSteps = parseInt($("sim-steps").value || "0", 10);

  if (!jitter) {
    return {
      heart_rate: baseHr,
      body_temperature: baseTemp,
      daily_steps: baseSteps,
    };
  }

  return {
    heart_rate: clamp(baseHr + randomInt(-3, 3), 0, 300),
    body_temperature: clamp(roundOne(baseTemp + randomFloat(-0.12, 0.12)), 20, 45),
    daily_steps: Math.max(0, baseSteps + randomInt(0, 18)),
  };
}

function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomFloat(min, max) {
  return Math.random() * (max - min) + min;
}

function roundOne(value) {
  return Math.round(value * 10) / 10;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

$("confirm-ok").addEventListener("click", async () => {
  if (!activePatient) return;
  await api.post(`/verify/${activePatient.id}`);
  await refreshTimeline();
});

$("force-sos").addEventListener("click", async () => {
  if (!activePatient) return;
  if (!confirm(`Force SOS escalation for ${activePatient.name}?`)) return;
  await api.post(`/sos/${activePatient.id}/force`);
  await refreshTimeline();
});

$("seed-demo-btn").addEventListener("click", async () => {
  const created = await api.post("/demo/seed");
  await refreshDoctors();
  await refreshPatients();
  await selectPatient(created.id);
});

// ----- new patient modal ------------------------------------------------

$("new-patient-btn").addEventListener("click", () => {
  populateDoctorSelect();
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
    doctor_id: $("np-doctor").value || null,
  };
  if (!body.name.trim() || !body.contact_number.trim()) {
    alert("Name and phone are required.");
    return;
  }
  if (!body.age || isNaN(body.age) || body.age < 1 || body.age > 130) {
    alert("Age must be a number between 1 and 130.");
    return;
  }
  if (!body.height_cm || isNaN(body.height_cm) || body.height_cm < 50 || body.height_cm > 250) {
    alert("Height must be a number between 50 and 250 cm.");
    return;
  }
  if (!body.weight_kg || isNaN(body.weight_kg) || body.weight_kg < 1 || body.weight_kg > 500) {
    alert("Weight must be a number between 1 and 500 kg.");
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

// ----- doctor modal -----------------------------------------------------

$("new-doctor-btn").addEventListener("click", () => { $("modal-doctor").hidden = false; });
$("modal-doctor-close").addEventListener("click", () => { $("modal-doctor").hidden = true; });
$("nd-save").addEventListener("click", async () => {
  const name = $("nd-name").value.trim();
  const phone = $("nd-phone").value.trim();
  const specialty = $("nd-specialty").value.trim();
  if (!name || !phone || !specialty) {
    alert("Name, phone, and specialty are required.");
    return;
  }
  await api.post("/doctors", {
    name,
    contact_number: phone,
    specialty,
    on_call_status: $("nd-oncall").checked,
  });
  $("modal-doctor").hidden = true;
  ["nd-name", "nd-phone", "nd-specialty"].forEach((id) => ($(id).value = ""));
  $("nd-oncall").checked = true;
  await refreshDoctors();
});

// ----- family modal -----------------------------------------------------

$("add-family-btn").addEventListener("click", () => {
  if (!activePatient) { alert("Select a patient first."); return; }
  $("modal-family").hidden = false;
});
$("modal-family-close").addEventListener("click", () => { $("modal-family").hidden = true; });
$("nf-save").addEventListener("click", async () => {
  if (!activePatient) return;
  const name = $("nf-name").value.trim();
  const phone = $("nf-phone").value.trim();
  const relationship = $("nf-relationship").value.trim();
  if (!name || !phone || !relationship) {
    alert("All fields are required.");
    return;
  }
  await api.post("/family", {
    name,
    contact_number: phone,
    relationship,
    patient_id: activePatient.id,
  });
  $("modal-family").hidden = true;
  ["nf-name", "nf-phone", "nf-relationship"].forEach((id) => ($(id).value = ""));
  await refreshContacts();
});

// ----- assign doctor modal ----------------------------------------------

$("change-doctor-btn").addEventListener("click", () => {
  if (!activePatient) { alert("Select a patient first."); return; }
  const sel = $("assign-doctor-select");
  sel.innerHTML = `<option value="">— none —</option>`;
  for (const d of allDoctors) {
    const opt = document.createElement("option");
    opt.value = d.id;
    opt.textContent = `${d.name} · ${d.specialty}`;
    if (d.id === activePatient.doctor_id) opt.selected = true;
    sel.appendChild(opt);
  }
  $("modal-assign-doctor").hidden = false;
});
$("modal-assign-doctor-close").addEventListener("click", () => {
  $("modal-assign-doctor").hidden = true;
});
$("assign-doctor-save").addEventListener("click", async () => {
  if (!activePatient) return;
  const doctorId = $("assign-doctor-select").value || null;
  activePatient = await api.patch(`/patients/${activePatient.id}/doctor`, { doctor_id: doctorId });
  $("modal-assign-doctor").hidden = true;
  await refreshContacts();
});

// ----- delete patient ---------------------------------------------------

$("delete-patient-btn").addEventListener("click", async () => {
  if (!activePatient) return;
  if (!confirm(`Delete ${activePatient.name}? This cannot be undone.`)) return;
  await api.delete(`/patients/${activePatient.id}`);
  activePatient = null;
  stopTelemetryStream();
  stopCountdown();
  if (pollHandle) { clearInterval(pollHandle); pollHandle = null; }
  patientView.hidden = true;
  thresholdCard.hidden = true;
  emptyState.hidden = false;
  await refreshPatients();
});

// ----- logout -----------------------------------------------------------

$("logout-btn").addEventListener("click", () => {
  localStorage.removeItem(TOKEN_KEY);
  window.location.replace("/login");
});

// ----- responsive trend chart -------------------------------------------

function resizeChart() {
  const canvas = $("trend-chart");
  const wrap = canvas.parentElement;
  canvas.width = wrap.clientWidth || 860;
  canvas.height = 260;
}

new ResizeObserver(resizeChart).observe($("trend-chart").parentElement);

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
refreshDoctors();
