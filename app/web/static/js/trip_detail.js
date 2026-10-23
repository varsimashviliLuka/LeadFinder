const TRIP_ID = window.TRIP_ID;
const GMAPS_MAX_STOPS = 10; // Google Maps directions links take a destination plus at most 9 waypoints.
const SERVICE_BY_VALUE = Object.fromEntries(window.APP.serviceStatuses.map((s) => [s.value, s]));
const VISIT_OUTCOMES = ["interested", "call_back", "no_answer", "not_interested", "client"];
const VISIT_OUTCOME_LABELS = { no_answer: "Owner / manager not there" };
const OPEN_PILLS = {
  open: ["success", "bi-door-open"],
  closes_soon: ["warning", "bi-hourglass-bottom"],
  closed: ["danger", "bi-door-closed"],
  unknown: ["secondary", "bi-question-circle"],
};
const WORTH_VISITING = ["new", "no_answer", "call_back", "interested"];

let trip = null;
let leads = [];
let visitStop = null;
let firstFit = true;

const stopList = document.getElementById("stop-list");
const visitModal = new bootstrap.Modal(document.getElementById("visit-modal"));

// ---------- Map ----------

const map = L.map("trip-map", { zoomControl: true }).setView([41.7151, 44.8271], 12);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

const leadLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
const stopLayer = L.layerGroup().addTo(map);

function stopIcon(stop, index, isNext) {
  const cls = stop.status !== "pending" ? `done ${stop.status}` : stop.open_state === "closed" ? "closed" : isNext ? "next" : "";
  return L.divIcon({
    className: "",
    html: `<div class="stop-marker ${cls}">${stop.status === "visited" ? '<i class="bi bi-check-lg"></i>' : index + 1}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

function leadPopup(lead) {
  return `<div class="map-popup">
    <div class="fw-semibold">${esc(lead.name)}</div>
    <div class="small text-body-secondary">${esc(lead.category || "")}</div>
    <div class="small my-1">${ratingText(lead.rating, lead.review_count)}</div>
    <div class="d-flex flex-wrap gap-1 mb-2">${statusPill(lead.lead_status)}
      ${lead.nfc_prospect ? '<span class="pill pill-info"><i class="bi bi-credit-card-2-front"></i>NFC prospect</span>' : ""}</div>
    <div class="d-flex gap-1">
      <button class="btn btn-sm btn-primary" data-add="${lead.id}"><i class="bi bi-plus-lg"></i> Add to trip</button>
      <a class="btn btn-sm btn-ghost" href="/businesses/${lead.id}" target="_blank">Open</a>
    </div>
  </div>`;
}

function drawMap() {
  const inTrip = new Set(trip.stops.map((s) => s.business.id));
  const filter = document.getElementById("map-filter").value;
  leadLayer.clearLayers();
  leads
    .filter((l) => !inTrip.has(l.id))
    .filter((l) => (filter === "all" ? true : filter === "none" ? false
      : filter === "nfc" ? l.nfc_prospect && WORTH_VISITING.includes(l.lead_status)
      : WORTH_VISITING.includes(l.lead_status)))
    .forEach((lead) => {
      L.circleMarker([lead.latitude, lead.longitude], {
        radius: 6, weight: 1, color: "#64748b", fillColor: lead.nfc_prospect ? "#38bdf8" : "#94a3b8", fillOpacity: 0.75,
      })
        .bindPopup(leadPopup(lead))
        .addTo(leadLayer);
    });

  stopLayer.clearLayers();
  routeLayer.clearLayers();
  const nextId = trip.stops.find((s) => s.status === "pending")?.id;
  const points = trip.stops.map((s) => [s.business.latitude, s.business.longitude]);
  trip.stops.forEach((stop, i) => {
    L.marker(points[i], { icon: stopIcon(stop, i, stop.id === nextId), zIndexOffset: 1000 })
      .bindPopup(`<div class="map-popup"><div class="fw-semibold">${i + 1}. ${esc(stop.business.name)}</div>
        <div class="small text-body-secondary">Arrive ${fmtClock(stop.eta)} · ${esc(stop.open_text)}</div></div>`)
      .on("click", () => document.getElementById(`stop-${stop.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }))
      .addTo(stopLayer);
  });
  if (trip.optimized && trip.route_geometry?.length) {
    L.polyline(trip.route_geometry, { color: "#6366f1", weight: 5, opacity: 0.85 }).addTo(routeLayer);
  } else if (points.length > 1) {
    L.polyline(points, { color: "#94a3b8", weight: 3, dashArray: "6 8" }).addTo(routeLayer);
  }

  if (firstFit) {
    const bounds = points.length ? points : leads.map((l) => [l.latitude, l.longitude]);
    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 });
    firstFit = false;
  }
}

map.on("popupopen", (e) => {
  e.popup.getElement().querySelector("[data-add]")?.addEventListener("click", async (ev) => {
    const id = Number(ev.currentTarget.dataset.add);
    map.closePopup();
    await addStops([id]);
  });
});

document.getElementById("map-filter").addEventListener("change", drawMap);

// ---------- Google Maps links ----------

function placeParam(b) {
  return `${b.latitude},${b.longitude}`;
}

function navigateHref(b) {
  const params = new URLSearchParams({ api: "1", destination: placeParam(b), travelmode: TRAVEL_MODES[trip.mode].google });
  if (b.place_id?.startsWith("ChIJ")) params.set("destination_place_id", b.place_id);
  return `https://www.google.com/maps/dir/?${params}`;
}

function routeHref(stops) {
  const last = stops[stops.length - 1].business;
  const params = new URLSearchParams({ api: "1", destination: placeParam(last), travelmode: TRAVEL_MODES[trip.mode].google });
  if (stops.length > 1) params.set("waypoints", stops.slice(0, -1).map((s) => placeParam(s.business)).join("|"));
  return `https://www.google.com/maps/dir/?${params}`;
}

function renderGmapsLinks() {
  const el = document.getElementById("gmaps-links");
  const pending = trip.stops.filter((s) => s.status === "pending");
  if (!trip.optimized || !pending.length) {
    el.innerHTML = "";
    return;
  }
  // Even parts, so there's no leftover part with a single stop.
  const size = Math.ceil(pending.length / Math.ceil(pending.length / GMAPS_MAX_STOPS));
  const chunks = [];
  for (let i = 0; i < pending.length; i += size) chunks.push(pending.slice(i, i + size));
  el.innerHTML = chunks
    .map((chunk) => {
      const from = trip.stops.indexOf(chunk[0]) + 1;
      const to = trip.stops.indexOf(chunk[chunk.length - 1]) + 1;
      const label = chunks.length === 1
        ? "Open the route in Google Maps"
        : `Google Maps: stop${from === to ? ` ${from}` : `s ${from}–${to}`}`;
      return `<a class="btn btn-sm btn-outline-secondary" href="${esc(routeHref(chunk))}" target="_blank" rel="noopener noreferrer"
        title="Starts from where you are now"><i class="bi bi-google"></i> ${label}</a>`;
    })
    .join("");
}

// ---------- Stop list ----------

function servicePill(label, icon, value) {
  if (!value) return "";
  const s = SERVICE_BY_VALUE[value];
  return `<span class="pill pill-${s.color}" title="${esc(s.help)}"><i class="bi ${icon}"></i>${esc(`${label}: ${s.label}`)}</span>`;
}

function stopCard(stop, index, isNext) {
  const b = stop.business;
  const [openColor, openIcon] = OPEN_PILLS[stop.open_state];
  const done = stop.status !== "pending";
  const nfc = stop.nfc_reasons.length && !b.service_nfc
    ? `<span class="pill pill-info" data-bs-toggle="tooltip" title="${esc(stop.nfc_reasons.join(" · "))}"><i class="bi bi-credit-card-2-front"></i>NFC prospect</span>`
    : "";
  const result = stop.status === "visited"
    ? `<div class="small mt-2">${statusPill(stop.outcome)} <span class="text-body-secondary">visited ${esc(fmtRelative(stop.visited_at))}</span></div>
       ${stop.note ? `<div class="small text-body-secondary mt-1 text-break">${esc(stop.note)}</div>` : ""}`
    : stop.status === "skipped"
      ? '<div class="small mt-2 text-body-secondary"><i class="bi bi-skip-forward"></i> Skipped</div>'
      : "";
  const actions = done
    ? `<button class="btn btn-sm btn-ghost" data-undo="${stop.id}"><i class="bi bi-arrow-counterclockwise"></i> Undo</button>`
    : `<a class="btn btn-sm ${isNext ? "btn-primary" : "btn-outline-primary"}" href="${esc(navigateHref(b))}" target="_blank" rel="noopener noreferrer">
        <i class="bi bi-cursor-fill"></i> Navigate</a>
       ${b.phone ? `<a class="btn btn-sm btn-outline-secondary" href="${esc(telHref(b.phone))}"><i class="bi bi-telephone"></i> Call</a>` : ""}
       <button class="btn btn-sm ${isNext ? "btn-success" : "btn-outline-success"}" data-visit="${stop.id}"><i class="bi bi-check2-square"></i> Log visit</button>`;
  return `<div class="card stop-card ${done ? "done" : ""} ${isNext ? "next" : ""}" id="stop-${stop.id}">
    <div class="card-body p-3">
      <div class="d-flex gap-2 align-items-start">
        <div class="stop-marker ${done ? `done ${stop.status}` : stop.open_state === "closed" ? "closed" : isNext ? "next" : ""}">${stop.status === "visited" ? '<i class="bi bi-check-lg"></i>' : index + 1}</div>
        <div class="flex-grow-1 min-w-0">
          <a class="fw-semibold text-body text-decoration-none text-break" href="/businesses/${b.id}">${esc(b.name)}</a>
          <div class="small text-body-secondary text-truncate">${esc(b.category || "")}${b.address ? ` · ${esc(b.address)}` : ""}</div>
          <div class="d-flex flex-wrap gap-1 align-items-center mt-1 small">
            <span class="fw-semibold"><i class="bi bi-clock"></i> ${fmtClock(stop.eta)}</span>
            <span class="pill pill-${openColor}"><i class="bi ${openIcon}"></i>${esc(stop.open_text)}</span>
            ${done ? "" : statusPill(b.lead_status)} ${nfc}
            ${servicePill("NFC", "bi-credit-card-2-front", b.service_nfc)}
            ${servicePill("Content", "bi-camera-reels", b.service_content)}
          </div>
          ${result}
        </div>
        <div class="dropdown">
          <button class="btn btn-sm btn-ghost" data-bs-toggle="dropdown" aria-label="More"><i class="bi bi-three-dots-vertical"></i></button>
          <ul class="dropdown-menu dropdown-menu-end">
            <li><a class="dropdown-item" href="/businesses/${b.id}"><i class="bi bi-person-lines-fill"></i> Open lead</a></li>
            ${b.review_url ? `<li><a class="dropdown-item" href="${esc(b.review_url)}" target="_blank" rel="noopener noreferrer"><i class="bi bi-star"></i> Their review link</a></li>` : ""}
            <li><button class="dropdown-item text-danger" data-remove="${stop.id}"><i class="bi bi-x-circle"></i> Remove from trip</button></li>
          </ul>
        </div>
      </div>
      <div class="d-flex flex-wrap gap-2 mt-2">${actions}</div>
    </div>
  </div>`;
}

function legLine(stop) {
  if (!trip.optimized || stop.leg_duration_s == null) return "";
  return `<div class="leg-line"><i class="bi ${TRAVEL_MODES[trip.mode].icon}"></i>
    ${fmtDuration(stop.leg_duration_s)} ${TRAVEL_MODES[trip.mode].verb} · ${formatDistance(Math.round(stop.leg_distance_m))}</div>`;
}

function renderStops() {
  disposeTooltips(stopList);
  if (!trip.stops.length) {
    stopList.innerHTML = `<div class="card"><div class="empty-state"><i class="bi bi-geo"></i>
      <div class="fw-semibold text-body">No stops yet</div>
      <div class="small">Tap businesses on the map, or tick them on the <a href="/businesses">Leads</a> page and choose <em>Add to trip</em>.
        Then click <em>Find best route</em>.</div></div></div>`;
    return;
  }
  const nextId = trip.stops.find((s) => s.status === "pending")?.id;
  stopList.innerHTML = trip.stops.map((s, i) => `${i ? legLine(s) : ""}${stopCard(s, i, s.id === nextId)}`).join("");
  initTooltips(stopList);
}

function renderSummary() {
  const el = document.getElementById("trip-summary");
  const closed = trip.stops.filter((s) => s.status === "pending" && s.open_state === "closed").length;
  document.getElementById("remove-closed").classList.toggle("d-none", !closed);
  if (!trip.stops.length) {
    el.innerHTML = '<span class="text-body-secondary">Add at least two businesses to plan a route (up to 25).</span>';
    return;
  }
  const parts = [`<span><i class="bi bi-geo-alt"></i> ${trip.stop_count} stops · ${trip.done_count} done</span>`];
  if (trip.optimized) {
    const stay = trip.minutes_per_stop * trip.stop_count * 60;
    parts.push(`<span><i class="bi ${TRAVEL_MODES[trip.mode].icon}"></i> ${fmtDuration(trip.total_duration_s)} ${TRAVEL_MODES[trip.mode].google} · ${formatDistance(Math.round(trip.total_distance_m))}</span>`);
    parts.push(`<span><i class="bi bi-flag"></i> ${fmtClock(trip.planned_start)} → done about ${fmtClock(trip.finish_at)}
      <span class="text-body-secondary">(${fmtDuration(trip.total_duration_s + stay)} incl. stops)</span></span>`);
    if (trip.route_estimated) {
      parts.push('<span class="text-warning-emphasis"><i class="bi bi-exclamation-triangle"></i> Routing server unreachable: times are rough straight-line estimates</span>');
    }
  } else {
    parts.push('<span class="text-warning-emphasis"><i class="bi bi-info-circle"></i> Order not planned yet: click <em>Find best route</em></span>');
  }
  if (closed) parts.push(`<span class="text-danger"><i class="bi bi-door-closed"></i> ${closed} closed when you arrive</span>`);
  el.innerHTML = `<div class="d-flex flex-wrap gap-3">${parts.join("")}</div>`;
}

function render() {
  document.getElementById(`mode-${trip.mode}`).checked = true;
  document.getElementById("start-at").value = trip.start_at || "";
  document.getElementById("minutes-per-stop").value = trip.minutes_per_stop;
  document.getElementById("optimize").querySelector("span").textContent = trip.optimized ? "Re-plan route" : "Find best route";
  renderSummary();
  renderStops();
  renderGmapsLinks();
  drawMap();
}

// ---------- Actions ----------

async function run(promise, success) {
  try {
    const result = await promise;
    trip = result.trip || result;
    render();
    if (success) toast(typeof success === "function" ? success(result) : success);
    return result;
  } catch (err) {
    toast(err.message, "danger");
    return null;
  }
}

async function addStops(ids) {
  const result = await run(api(`/trips/${TRIP_ID}/stops`, { method: "POST", body: { business_ids: ids } }));
  if (!result) return;
  if (result.added) toast(`Added ${result.added} stop${result.added === 1 ? "" : "s"}`);
  result.skipped.forEach((s) => toast(`${s.name}: ${s.reason}`, "info"));
}

async function patchTrip(body) {
  await run(api(`/trips/${TRIP_ID}`, { method: "PATCH", body }));
}

document.querySelectorAll("#mode-toggle input").forEach((input) =>
  input.addEventListener("change", async () => {
    const wasOptimized = trip.optimized;
    await patchTrip({ mode: input.value });
    if (wasOptimized && trip.stops.length > 1) await optimize();
  }),
);
document.getElementById("start-at").addEventListener("change", (e) => patchTrip({ start_at: e.target.value || null }));
document.getElementById("minutes-per-stop").addEventListener("change", (e) => {
  const minutes = Number.parseInt(e.target.value, 10);
  patchTrip({ minutes_per_stop: Number.isNaN(minutes) ? 15 : minutes });
});
document.getElementById("trip-name").addEventListener("change", (e) => patchTrip({ name: e.target.value }));

async function optimize() {
  const btn = document.getElementById("optimize");
  btn.disabled = true;
  btn.querySelector("span").textContent = "Planning…";
  await run(api(`/trips/${TRIP_ID}/optimize`, { method: "POST" }), () => `Fastest ${TRAVEL_MODES[trip.mode].google} order found`);
  btn.disabled = false;
  btn.querySelector("span").textContent = trip.optimized ? "Re-plan route" : "Find best route";
}
document.getElementById("optimize").addEventListener("click", optimize);

document.getElementById("remove-closed").addEventListener("click", async () => {
  const ok = await confirmDialog({
    title: "Remove closed stops?",
    body: "Businesses that will be closed when you get there are taken off this trip. Then plan the route again.",
    confirmText: "Remove",
  });
  if (ok) await run(api(`/trips/${TRIP_ID}/remove-closed`, { method: "POST" }), (r) => `Removed ${r.removed} closed stop${r.removed === 1 ? "" : "s"}`);
});

document.getElementById("delete-trip").addEventListener("click", async () => {
  const ok = await confirmDialog({
    title: "Delete this trip?",
    body: "The route is removed. Visits you logged stay in each lead's history.",
  });
  if (!ok) return;
  try {
    await api(`/trips/${TRIP_ID}`, { method: "DELETE" });
    window.location.href = "/trips";
  } catch (err) {
    toast(err.message, "danger");
  }
});

stopList.addEventListener("click", async (e) => {
  const remove = e.target.closest("[data-remove]");
  const undo = e.target.closest("[data-undo]");
  const visit = e.target.closest("[data-visit]");
  if (remove) await run(api(`/trips/${TRIP_ID}/stops/${remove.dataset.remove}`, { method: "DELETE" }), "Stop removed");
  if (undo) await run(api(`/trips/${TRIP_ID}/stops/${undo.dataset.undo}/visit`, { method: "DELETE" }), "Visit undone");
  if (visit) openVisit(trip.stops.find((s) => s.id === Number(visit.dataset.visit)));
});

// ---------- Visit dialog ----------

function serviceOptions(selected) {
  return `<option value="">Not offered</option>${window.APP.serviceStatuses
    .map((s) => `<option value="${s.value}" ${s.value === selected ? "selected" : ""}>${esc(s.label)}</option>`)
    .join("")}`;
}

function openVisit(stop) {
  visitStop = stop;
  const b = stop.business;
  document.getElementById("visit-business").textContent = b.name;
  document.getElementById("visit-note").value = "";
  document.getElementById("visit-nfc").innerHTML = serviceOptions(b.service_nfc);
  document.getElementById("visit-content").innerHTML = serviceOptions(b.service_content);
  document.getElementById("visit-outcomes").innerHTML = VISIT_OUTCOMES
    .map((value, i) => {
      const s = STATUS_BY_VALUE[value];
      return `<input type="radio" class="btn-check" name="visit-outcome" id="vo-${value}" value="${value}" ${i === 0 ? "checked" : ""}>
        <label class="btn btn-outline-${s.color} text-start" for="vo-${value}"><i class="bi ${s.icon}"></i> ${esc(VISIT_OUTCOME_LABELS[value] || s.label)}</label>`;
    })
    .join("");
  visitModal.show();
}

async function saveVisit(body) {
  const result = await run(api(`/trips/${TRIP_ID}/stops/${visitStop.id}/visit`, { method: "POST", body }), body.outcome === "skipped" ? "Stop skipped" : "Visit saved");
  if (!result) return;
  visitModal.hide();
  const next = trip.stops.find((s) => s.status === "pending");
  if (next) document.getElementById(`stop-${next.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  else toast("All stops done. Nice work!", "info");
}

document.getElementById("visit-form").addEventListener("submit", (e) => {
  e.preventDefault();
  saveVisit({
    outcome: document.querySelector("[name=visit-outcome]:checked").value,
    note: document.getElementById("visit-note").value.trim() || null,
    service_nfc: document.getElementById("visit-nfc").value || null,
    service_content: document.getElementById("visit-content").value || null,
  });
});
document.getElementById("visit-skip").addEventListener("click", () => saveVisit({ outcome: "skipped" }));

// ---------- Load ----------

async function load() {
  try {
    [trip, leads] = await Promise.all([api(`/trips/${TRIP_ID}`), api("/businesses/map")]);
    render();
  } catch (err) {
    toast(err.message, "danger");
  }
}

load();
