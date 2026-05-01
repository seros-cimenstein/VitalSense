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
  async patch(path, body) {
    const r = await fetch(`/api${path}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  },
  async delete(path) {
    const r = await fetch(`/api${path}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`${r.status} ${path}`);
  },
};

// state
let activePatient = null;
let pollHandle = null;
let allDoctors = [];

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
