const TBILISI = [41.7151, 44.8271];
const ACTIVE_STATUSES = ["pending", "running"];
const SECONDS_PER_BUSINESS = 15;
const SECONDS_BETWEEN_SEARCHES = 90;
const SECONDS_PER_SOCIAL_CHECK = 5;
const SECONDS_PER_REVIEW_CHECK = 8;
// interactive:false so left-drag still pans the map through the overlay.
const AREA_STYLE = { color: "#4f46e5", weight: 2, fillOpacity: 0.08, interactive: false };
const DEFAULT_RECT_HALF_M = 500;

const SAVED_SHAPE = localStorage.getItem("searchAreaShape");
const state = {
  shape: ["circle", "rectangle", "polygon"].includes(SAVED_SHAPE) ? SAVED_SHAPE : "circle",
  point: null,
  bounds: null,
  polygon: null, // [[lat, lng], ...] closed ring
  label: "",
  categories: [],
};

// ---------- "How it works" tip ----------

const howItWorks = document.getElementById("how-it-works");
const showHowItWorks = document.getElementById("show-how-it-works");

function setTipVisible(visible) {
  howItWorks.classList.toggle("d-none", !visible);
  showHowItWorks.classList.toggle("d-none", visible);
  localStorage.setItem("hideHowItWorks", visible ? "" : "1");
}

setTipVisible(!localStorage.getItem("hideHowItWorks"));
document.getElementById("hide-how-it-works").addEventListener("click", () => setTipVisible(false));
showHowItWorks.addEventListener("click", (e) => {
  e.preventDefault();
  setTipVisible(true);
  window.scrollTo({ top: 0, behavior: "smooth" });
});

// ---------- Step 1: map & location ----------

const map = L.map("search-map").setView(TBILISI, 13);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const marker = L.marker(TBILISI, { draggable: true });
const circle = L.circle(TBILISI, { radius: 1000, ...AREA_STYLE });
let rectangle = null;
let polygonLayer = null;
let draftRect = null;
let draftLine = null;
let drawStart = null;
let freehandPoints = null;
const radiusInput = document.getElementById("radius-input");
const locationLabel = document.getElementById("location-label");
const circleControls = document.getElementById("circle-controls");
const rectangleControls = document.getElementById("rectangle-controls");
const polygonControls = document.getElementById("polygon-controls");
const redrawRectangleBtn = document.getElementById("redraw-rectangle");
const redrawPolygonBtn = document.getElementById("redraw-polygon");
const mapEl = document.getElementById("search-map");

function radiusMeters() {
  return Number(radiusInput.value);
}

function shortName(displayName) {
  return displayName.split(",").slice(0, 3).join(",").trim();
}

function hasArea() {
  if (state.shape === "rectangle") return Boolean(state.bounds);
  if (state.shape === "polygon") return Boolean(state.polygon && state.polygon.length >= 4);
  return Boolean(state.point);
}

function metersToLat(m) {
  return m / 111_320;
}

function metersToLng(m, lat) {
  return m / (111_320 * Math.cos((lat * Math.PI) / 180));
}

function boundsFromCenter(lat, lng, halfM = DEFAULT_RECT_HALF_M) {
  const dLat = metersToLat(halfM);
  const dLng = metersToLng(halfM, lat);
  return {
    south: lat - dLat,
    west: lng - dLng,
    north: lat + dLat,
    east: lng + dLng,
  };
}

function leafletBounds(b) {
  return L.latLngBounds([b.south, b.west], [b.north, b.east]);
}

function clearCircleOverlay() {
  if (map.hasLayer(marker)) map.removeLayer(marker);
  if (map.hasLayer(circle)) map.removeLayer(circle);
}

function clearRectangleOverlay() {
  if (rectangle) {
    map.removeLayer(rectangle);
    rectangle = null;
  }
  if (draftRect) {
    map.removeLayer(draftRect);
    draftRect = null;
  }
  drawStart = null;
  mapEl.classList.remove("is-drawing");
}

function clearPolygonOverlay() {
  if (polygonLayer) {
    map.removeLayer(polygonLayer);
    polygonLayer = null;
  }
  if (draftLine) {
    map.removeLayer(draftLine);
    draftLine = null;
  }
  freehandPoints = null;
  mapEl.classList.remove("is-drawing");
}

function clearDrawnOverlays() {
  clearRectangleOverlay();
  clearPolygonOverlay();
}

function approxRectSize(bounds) {
  const height = Math.abs(bounds.north - bounds.south) * 111_320;
  const width = Math.abs(bounds.east - bounds.west) * 111_320 * Math.cos((((bounds.south + bounds.north) / 2) * Math.PI) / 180);
  return Math.round(Math.max(height, width));
}

function latLngDistanceM(a, b) {
  const dLat = (a.lat - b.lat) * 111_320;
  const dLng = (a.lng - b.lng) * 111_320 * Math.cos((a.lat * Math.PI) / 180);
  return Math.hypot(dLat, dLng);
}

function simplifyLatLngs(latlngs, minMeters = 18) {
  if (!latlngs.length) return [];
  const out = [latlngs[0]];
  for (let i = 1; i < latlngs.length; i++) {
    if (latLngDistanceM(out[out.length - 1], latlngs[i]) >= minMeters) out.push(latlngs[i]);
  }
  const last = latlngs[latlngs.length - 1];
  if (out.length && latLngDistanceM(out[out.length - 1], last) > 1) out.push(last);
  return out;
}

function ringFromLatLngs(latlngs) {
  const simplified = simplifyLatLngs(latlngs);
  if (simplified.length < 3) return null;
  const ring = simplified.map((p) => [p.lat, p.lng]);
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) ring.push([first[0], first[1]]);
  return ring;
}

function boundsFromRing(ring) {
  const lats = ring.map((p) => p[0]);
  const lngs = ring.map((p) => p[1]);
  return { south: Math.min(...lats), west: Math.min(...lngs), north: Math.max(...lats), east: Math.max(...lngs) };
}

function setRectangleBounds(bounds, label = null, { fit = true } = {}) {
  state.bounds = bounds;
  state.polygon = null;
  state.point = {
    lat: (bounds.south + bounds.north) / 2,
    lng: (bounds.west + bounds.east) / 2,
  };
  clearCircleOverlay();
  clearPolygonOverlay();
  if (rectangle) map.removeLayer(rectangle);
  rectangle = L.rectangle(leafletBounds(bounds), AREA_STYLE).addTo(map);
  if (fit) map.fitBounds(leafletBounds(bounds), { padding: [24, 24] });
  redrawRectangleBtn.disabled = false;
  state.label = label || `Rectangle · ${formatDistance(approxRectSize(bounds))}`;
  locationLabel.textContent = state.label;
  updateSteps();
}

function setPolygonRing(ring, label = null, { fit = true } = {}) {
  state.polygon = ring;
  state.bounds = null;
  const box = boundsFromRing(ring);
  state.point = { lat: (box.south + box.north) / 2, lng: (box.west + box.east) / 2 };
  clearCircleOverlay();
  clearRectangleOverlay();
  if (polygonLayer) map.removeLayer(polygonLayer);
  polygonLayer = L.polygon(ring.map(([lat, lng]) => [lat, lng]), AREA_STYLE).addTo(map);
  if (fit) map.fitBounds(polygonLayer.getBounds(), { padding: [24, 24] });
  redrawPolygonBtn.disabled = false;
  state.label = label || `Drawn area · ${formatDistance(approxRectSize(box))}`;
  locationLabel.textContent = state.label;
  updateSteps();
}

async function setPoint(lat, lng, label = null, { fit = true } = {}) {
  if (state.shape === "rectangle") {
    setRectangleBounds(boundsFromCenter(lat, lng), label, { fit });
    if (!label) reverseLabel(lat, lng, () => state.point && state.point.lat === lat && state.point.lng === lng);
    return;
  }
  if (state.shape === "polygon") {
    // Keep map centred for drawing; don't invent a shape from a single point.
    state.point = { lat, lng };
    map.setView([lat, lng], Math.max(map.getZoom(), 14));
    if (label) {
      state.label = label;
      locationLabel.textContent = label;
    } else if (!state.polygon) {
      locationLabel.textContent = "Right-click and drag to draw a shape";
      state.label = "";
    }
    updateSteps();
    if (!label) reverseLabel(lat, lng, () => state.point && state.point.lat === lat && state.point.lng === lng);
    return;
  }

  state.point = { lat, lng };
  state.bounds = null;
  state.polygon = null;
  clearDrawnOverlays();
  marker.setLatLng([lat, lng]).addTo(map);
  circle.setLatLng([lat, lng]).setRadius(radiusMeters()).addTo(map);
  if (fit) map.fitBounds(circle.getBounds(), { padding: [24, 24] });

  state.label = label || `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  locationLabel.textContent = state.label;
  updateSteps();
  if (label) return;
  reverseLabel(lat, lng, () => state.point && state.point.lat === lat && state.point.lng === lng);
}

async function reverseLabel(lat, lng, stillCurrent) {
  try {
    const place = await api(`/geocode/reverse?lat=${lat}&lng=${lng}`);
    if (!stillCurrent()) return;
    state.label = shortName(place.display_name);
    locationLabel.textContent = state.label;
    updateSteps();
  } catch {
    // Keep coordinates / size as the label.
  }
}

function syncShapeUi() {
  document.querySelectorAll("[data-shape]").forEach((btn) => {
    const on = btn.dataset.shape === state.shape;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
  circleControls.classList.toggle("d-none", state.shape !== "circle");
  rectangleControls.classList.toggle("d-none", state.shape !== "rectangle");
  polygonControls.classList.toggle("d-none", state.shape !== "polygon");
  mapEl.classList.toggle("is-drawing", false);

  if (state.shape === "circle") {
    clearDrawnOverlays();
    if (state.point) {
      marker.setLatLng([state.point.lat, state.point.lng]).addTo(map);
      circle.setLatLng([state.point.lat, state.point.lng]).setRadius(radiusMeters()).addTo(map);
    }
  } else if (state.shape === "rectangle") {
    clearCircleOverlay();
    clearPolygonOverlay();
    if (state.bounds) {
      if (rectangle) map.removeLayer(rectangle);
      rectangle = L.rectangle(leafletBounds(state.bounds), AREA_STYLE).addTo(map);
      redrawRectangleBtn.disabled = false;
    } else {
      redrawRectangleBtn.disabled = true;
      locationLabel.textContent = "Right-click and drag to draw a rectangle";
      state.label = "";
    }
  } else {
    clearCircleOverlay();
    clearRectangleOverlay();
    if (state.polygon) {
      if (polygonLayer) map.removeLayer(polygonLayer);
      polygonLayer = L.polygon(state.polygon.map(([lat, lng]) => [lat, lng]), AREA_STYLE).addTo(map);
      redrawPolygonBtn.disabled = false;
    } else {
      redrawPolygonBtn.disabled = true;
      locationLabel.textContent = "Right-click and drag to draw a shape";
      state.label = "";
    }
  }
  updateSteps();
}

function setShape(shape) {
  if (!["circle", "rectangle", "polygon"].includes(shape)) return;
  const prev = state.shape;
  state.shape = shape;
  localStorage.setItem("searchAreaShape", shape);

  if (shape === "rectangle" && prev === "circle" && state.point && !state.bounds) {
    setRectangleBounds(
      boundsFromCenter(state.point.lat, state.point.lng, Math.max(DEFAULT_RECT_HALF_M, radiusMeters() / 2)),
      state.label,
    );
  } else if (shape === "circle" && (prev === "rectangle" || prev === "polygon")) {
    const center = state.point || (state.bounds && {
      lat: (state.bounds.south + state.bounds.north) / 2,
      lng: (state.bounds.west + state.bounds.east) / 2,
    }) || (state.polygon && (() => {
      const box = boundsFromRing(state.polygon);
      return { lat: (box.south + box.north) / 2, lng: (box.west + box.east) / 2 };
    })());
    state.bounds = null;
    state.polygon = null;
    if (center) setPoint(center.lat, center.lng, state.label || null);
  } else if (shape === "polygon" && prev !== "polygon") {
    state.bounds = null;
    clearRectangleOverlay();
  } else if (shape === "rectangle" && prev === "polygon") {
    state.polygon = null;
    clearPolygonOverlay();
  }
  syncShapeUi();
}

document.querySelectorAll("[data-shape]").forEach((btn) =>
  btn.addEventListener("click", () => setShape(btn.dataset.shape)),
);

redrawRectangleBtn.addEventListener("click", () => {
  state.bounds = null;
  clearRectangleOverlay();
  locationLabel.textContent = "Right-click and drag to draw a rectangle";
  state.label = "";
  redrawRectangleBtn.disabled = true;
  updateSteps();
});

redrawPolygonBtn.addEventListener("click", () => {
  state.polygon = null;
  clearPolygonOverlay();
  locationLabel.textContent = "Right-click and drag to draw a shape";
  state.label = "";
  redrawPolygonBtn.disabled = true;
  updateSteps();
});

map.on("click", (e) => {
  if (state.shape !== "circle" || drawStart || freehandPoints) return;
  setPoint(e.latlng.lat, e.latlng.lng, null, { fit: false });
});
marker.on("dragend", () => {
  const { lat, lng } = marker.getLatLng();
  setPoint(lat, lng, null, { fit: false });
});

// Left-drag pans. Right-drag draws rectangle or freehand polygon.
map.on("mousedown", (e) => {
  if (e.originalEvent.button !== 2) return;
  if (state.shape === "rectangle") {
    drawStart = e.latlng;
    mapEl.classList.add("is-drawing");
    if (draftRect) map.removeLayer(draftRect);
    draftRect = L.rectangle(L.latLngBounds(drawStart, drawStart), { ...AREA_STYLE, dashArray: "6 4" }).addTo(map);
    L.DomEvent.preventDefault(e.originalEvent);
  } else if (state.shape === "polygon") {
    freehandPoints = [e.latlng];
    mapEl.classList.add("is-drawing");
    if (draftLine) map.removeLayer(draftLine);
    draftLine = L.polyline(freehandPoints, { ...AREA_STYLE, dashArray: "6 4", fill: false }).addTo(map);
    L.DomEvent.preventDefault(e.originalEvent);
  }
});

map.on("mousemove", (e) => {
  if (drawStart && draftRect) {
    draftRect.setBounds(L.latLngBounds(drawStart, e.latlng));
    return;
  }
  if (freehandPoints && draftLine) {
    const last = freehandPoints[freehandPoints.length - 1];
    if (latLngDistanceM(last, e.latlng) >= 8) {
      freehandPoints.push(e.latlng);
      draftLine.setLatLngs(freehandPoints);
    }
  }
});

function finishRectDraw(endLatLng) {
  if (!drawStart) return;
  const start = drawStart;
  drawStart = null;
  mapEl.classList.remove("is-drawing");
  if (draftRect) {
    map.removeLayer(draftRect);
    draftRect = null;
  }
  if (!endLatLng) {
    updateSteps();
    return;
  }
  const bounds = {
    south: Math.min(start.lat, endLatLng.lat),
    west: Math.min(start.lng, endLatLng.lng),
    north: Math.max(start.lat, endLatLng.lat),
    east: Math.max(start.lng, endLatLng.lng),
  };
  if (approxRectSize(bounds) < 80) {
    toast("Right-click and drag a larger rectangle", "danger");
    updateSteps();
    return;
  }
  setRectangleBounds(bounds, null, { fit: false });
  reverseLabel(state.point.lat, state.point.lng, () => Boolean(state.bounds));
}

function finishPolygonDraw(endLatLng) {
  if (!freehandPoints) return;
  const points = freehandPoints;
  freehandPoints = null;
  mapEl.classList.remove("is-drawing");
  if (draftLine) {
    map.removeLayer(draftLine);
    draftLine = null;
  }
  if (endLatLng) points.push(endLatLng);
  const ring = ringFromLatLngs(points);
  if (!ring || approxRectSize(boundsFromRing(ring)) < 80) {
    toast("Right-click and drag a larger shape", "danger");
    updateSteps();
    return;
  }
  setPolygonRing(ring, null, { fit: false });
  reverseLabel(state.point.lat, state.point.lng, () => Boolean(state.polygon));
}

map.on("mouseup", (e) => {
  if (e.originalEvent.button !== 2) return;
  if (drawStart) finishRectDraw(e.latlng);
  else if (freehandPoints) finishPolygonDraw(e.latlng);
});
document.addEventListener("mouseup", (e) => {
  if (e.button !== 2) return;
  if (drawStart) finishRectDraw(null);
  else if (freehandPoints) finishPolygonDraw(null);
});
mapEl.addEventListener("contextmenu", (e) => {
  if (state.shape === "rectangle" || state.shape === "polygon") e.preventDefault();
});

radiusInput.addEventListener("input", () => {
  document.getElementById("radius-value").textContent = formatDistance(radiusMeters());
  circle.setRadius(radiusMeters());
  updateSteps();
});
radiusInput.addEventListener("change", () => {
  if (state.shape === "circle" && state.point) map.fitBounds(circle.getBounds(), { padding: [24, 24] });
});

const locateBtn = document.getElementById("locate-btn");
locateBtn.addEventListener("click", () => {
  if (!navigator.geolocation) {
    toast("Your browser doesn't support location access", "danger");
    return;
  }
  const original = locateBtn.innerHTML;
  locateBtn.disabled = true;
  locateBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Locating…';
  const done = () => {
    locateBtn.disabled = false;
    locateBtn.innerHTML = original;
  };
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      done();
      setPoint(pos.coords.latitude, pos.coords.longitude);
    },
    (err) => {
      done();
      toast(`Couldn't get your location: ${err.message}. Try searching an address instead.`, "danger");
    },
    { enableHighAccuracy: true, timeout: 15000 },
  );
});

const addressInput = document.getElementById("address-input");
const geocodeResults = document.getElementById("geocode-results");

async function searchAddress() {
  const q = addressInput.value.trim();
  if (!q) return;
  geocodeResults.innerHTML = '<div class="list-group-item small text-body-secondary"><span class="spinner-border spinner-border-sm"></span> Searching…</div>';
  geocodeResults.classList.remove("d-none");
  try {
    const matches = await api(`/geocode?q=${encodeURIComponent(q)}`);
    if (!matches.length) {
      geocodeResults.innerHTML = '<div class="list-group-item small text-body-secondary">No places found. Try a street or district name.</div>';
      return;
    }
    geocodeResults.innerHTML = matches
      .map((m, i) => `<button type="button" class="list-group-item list-group-item-action small" data-index="${i}">
        <i class="bi bi-geo-alt text-body-secondary me-1"></i>${esc(m.display_name)}</button>`)
      .join("");
    geocodeResults.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const m = matches[Number(btn.dataset.index)];
        geocodeResults.classList.add("d-none");
        addressInput.value = shortName(m.display_name);
        setPoint(m.latitude, m.longitude, shortName(m.display_name));
      });
    });
  } catch (err) {
    geocodeResults.innerHTML = `<div class="list-group-item small text-danger">${esc(err.message)}</div>`;
  }
}

document.getElementById("address-btn").addEventListener("click", searchAddress);
addressInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    searchAddress();
  }
});
document.addEventListener("click", (e) => {
  if (!geocodeResults.contains(e.target) && e.target !== addressInput) geocodeResults.classList.add("d-none");
});

// ---------- Step 2: business types ----------

const categoryInput = document.getElementById("category-input");
const suggested = new Set([...document.querySelectorAll("#category-chips .category-chip")].map((c) => c.dataset.category));

function toggleCategory(category) {
  const i = state.categories.indexOf(category);
  if (i >= 0) state.categories.splice(i, 1);
  else state.categories.push(category);
  renderCategories();
}

function addCustomCategory() {
  const value = categoryInput.value.trim();
  categoryInput.value = "";
  if (value && !state.categories.includes(value)) {
    state.categories.push(value);
    renderCategories();
  }
}

function renderCategories() {
  document.querySelectorAll("#category-chips .category-chip").forEach((chip) => {
    const selected = state.categories.includes(chip.dataset.category);
    chip.classList.toggle("selected", selected);
    chip.innerHTML = `${selected ? '<i class="bi bi-check-lg"></i>' : ""}${esc(chip.dataset.category)}`;
  });
  const custom = state.categories.filter((c) => !suggested.has(c));
  const box = document.getElementById("custom-categories");
  box.innerHTML = custom
    .map((c) => `<span class="category-chip selected" data-remove="${esc(c)}" title="Click to remove">
      <i class="bi bi-check-lg"></i>${esc(c)}<i class="bi bi-x ms-1"></i></span>`)
    .join("");
  box.querySelectorAll("[data-remove]").forEach((chip) =>
    chip.addEventListener("click", () => toggleCategory(chip.dataset.remove)),
  );
  updateSteps();
}

document.querySelectorAll("#category-chips .category-chip").forEach((chip) =>
  chip.addEventListener("click", () => toggleCategory(chip.dataset.category)),
);
document.getElementById("category-add").addEventListener("click", addCustomCategory);
categoryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    addCustomCategory();
  }
});

// ---------- Step 3: summary & start ----------

const maxResultsInput = document.getElementById("max-results-input");
maxResultsInput.addEventListener("change", updateSteps);

const findSocialsInput = document.getElementById("find-socials-input");
findSocialsInput.checked = localStorage.getItem("findSocials") === "true";
findSocialsInput.addEventListener("change", () => {
  localStorage.setItem("findSocials", String(findSocialsInput.checked));
  updateSteps();
});

const collectReviewsInput = document.getElementById("collect-reviews-input");
collectReviewsInput.checked = localStorage.getItem("collectReviews") === "true";
collectReviewsInput.addEventListener("change", () => {
  localStorage.setItem("collectReviews", String(collectReviewsInput.checked));
  updateSteps();
});

const nfcFilterInput = document.getElementById("nfc-filter-input");
const nfcFilterOptions = document.getElementById("nfc-filter-options");
const maxRatingInput = document.getElementById("max-rating-input");
const maxReviewsInput = document.getElementById("max-reviews-input");
const NFC_DEFAULT_MAX_RATING = 4.3;
const NFC_DEFAULT_MAX_REVIEWS = 50;

function nfcFilterOn() {
  return nfcFilterInput.checked;
}

function nfcMaxRating() {
  const value = Number(maxRatingInput.value);
  if (!Number.isFinite(value) || value < 1 || value > 5) return null;
  return Math.round(value * 10) / 10;
}

function nfcMaxReviews() {
  const value = Number(maxReviewsInput.value);
  if (!Number.isFinite(value) || value < 0 || value !== Math.floor(value)) return null;
  return value;
}

function syncNfcFilterUi() {
  nfcFilterOptions.classList.toggle("d-none", !nfcFilterOn());
  if (nfcFilterOn()) {
    if (maxRatingInput.value === "") maxRatingInput.value = String(NFC_DEFAULT_MAX_RATING);
    if (maxReviewsInput.value === "") maxReviewsInput.value = String(NFC_DEFAULT_MAX_REVIEWS);
  }
  updateSteps();
}

nfcFilterInput.checked = localStorage.getItem("nfcFilter") === "true";
const savedMaxRating = localStorage.getItem("nfcMaxRating");
const savedMaxReviews = localStorage.getItem("nfcMaxReviews");
if (savedMaxRating) maxRatingInput.value = savedMaxRating;
if (savedMaxReviews) maxReviewsInput.value = savedMaxReviews;
nfcFilterInput.addEventListener("change", () => {
  localStorage.setItem("nfcFilter", String(nfcFilterInput.checked));
  syncNfcFilterUi();
});
maxRatingInput.addEventListener("change", () => {
  const value = nfcMaxRating();
  if (value == null) {
    maxRatingInput.value = String(NFC_DEFAULT_MAX_RATING);
  } else {
    maxRatingInput.value = String(value);
    localStorage.setItem("nfcMaxRating", String(value));
  }
  updateSteps();
});
maxReviewsInput.addEventListener("change", () => {
  const value = nfcMaxReviews();
  if (value == null) {
    maxReviewsInput.value = String(NFC_DEFAULT_MAX_REVIEWS);
  } else {
    maxReviewsInput.value = String(value);
    localStorage.setItem("nfcMaxReviews", String(value));
  }
  updateSteps();
});
syncNfcFilterUi();

function estimateMinutes() {
  const n = state.categories.length;
  const perBusiness = SECONDS_PER_BUSINESS
    + (findSocialsInput.checked ? SECONDS_PER_SOCIAL_CHECK : 0)
    + (collectReviewsInput.checked ? SECONDS_PER_REVIEW_CHECK : 0);
  const seconds = n * Number(maxResultsInput.value) * perBusiness + Math.max(0, n - 1) * SECONDS_BETWEEN_SEARCHES;
  return Math.max(1, Math.round(seconds / 60));
}

function areaSummaryLine() {
  if (state.shape === "polygon" && state.polygon) {
    return `<div class="mb-1"><i class="bi bi-pencil text-body-secondary"></i> Inside a drawn shape around <strong>${esc(state.label)}</strong> (~${formatDistance(approxRectSize(boundsFromRing(state.polygon)))} across)</div>`;
  }
  if (state.shape === "rectangle" && state.bounds) {
    return `<div class="mb-1"><i class="bi bi-square text-body-secondary"></i> Inside a rectangle around <strong>${esc(state.label)}</strong> (~${formatDistance(approxRectSize(state.bounds))} across)</div>`;
  }
  return `<div class="mb-1"><i class="bi bi-circle text-body-secondary"></i> Within ${formatDistance(radiusMeters())} of <strong>${esc(state.label)}</strong></div>`;
}

function updateSteps() {
  const ready = hasArea();
  const hasTypes = state.categories.length > 0;
  document.getElementById("step-area").classList.toggle("is-done", ready);
  document.getElementById("step-types").classList.toggle("is-done", hasTypes);
  document.getElementById("search-submit").disabled = !(ready && hasTypes);

  const summary = document.getElementById("search-summary");
  if (!ready || !hasTypes) {
    const needArea = state.shape === "rectangle"
      ? "draw a rectangle on the map (step 1)"
      : state.shape === "polygon"
        ? "draw a shape on the map (step 1)"
        : "pick an area on the map (step 1)";
    const missing = [!ready && needArea, !hasTypes && "choose at least one business type (step 2)"]
      .filter(Boolean)
      .join(" and ");
    summary.innerHTML = `<span class="text-body-secondary"><i class="bi bi-info-circle"></i> To start, ${missing}.</span>`;
    return;
  }
  const types = state.categories.map((c) => `<strong>${esc(c)}</strong>`).join(", ");
  const nfcLine = nfcFilterOn()
    ? `<div class="mb-1"><i class="bi bi-credit-card-2-front text-body-secondary"></i> Only NFC prospects: rating ≤ ${nfcMaxRating() ?? NFC_DEFAULT_MAX_RATING}, reviews ≤ ${nfcMaxReviews() ?? NFC_DEFAULT_MAX_REVIEWS}</div>`
    : "";
  summary.innerHTML = `
    <div class="mb-1"><i class="bi bi-search text-body-secondary"></i> Look for ${types}</div>
    ${areaSummaryLine()}
    ${nfcLine}
    ${collectReviewsInput.checked ? '<div class="mb-1"><i class="bi bi-chat-square-quote text-body-secondary"></i> Read each one\'s latest reviews</div>' : ""}
    ${findSocialsInput.checked ? '<div class="mb-1"><i class="bi bi-instagram text-body-secondary"></i> Then check their websites and find social media, email and WhatsApp</div>' : ""}
    <div><i class="bi bi-clock text-body-secondary"></i> Up to ${maxResultsInput.value} of each · roughly ${estimateMinutes()} min at most</div>`;
}

document.getElementById("search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!hasArea() || !state.categories.length) return;

  if (nfcFilterOn() && (nfcMaxRating() == null || nfcMaxReviews() == null)) {
    toast("Set a max Google rating (1–5) and max reviews for the NFC filter", "danger");
    return;
  }

  const submit = document.getElementById("search-submit");
  submit.disabled = true;
  submit.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Starting…';
  let started = 0;
  for (const query of state.categories) {
    try {
      const body = {
        query,
        location_text: state.label,
        area_shape: state.shape,
        max_results: Number(maxResultsInput.value),
        find_socials: findSocialsInput.checked,
        collect_reviews: collectReviewsInput.checked,
      };
      if (state.shape === "rectangle") {
        Object.assign(body, state.bounds);
      } else if (state.shape === "polygon") {
        body.polygon = state.polygon;
      } else {
        body.latitude = state.point.lat;
        body.longitude = state.point.lng;
        body.radius_m = radiusMeters();
      }
      if (nfcFilterOn()) {
        body.max_rating = nfcMaxRating();
        body.max_reviews = nfcMaxReviews();
      }
      await api("/searches", { method: "POST", body });
      started += 1;
    } catch (err) {
      toast(`"${query}": ${err.message}`, "danger");
    }
  }
  submit.innerHTML = '<i class="bi bi-play-fill"></i> Start search';
  if (started) {
    toast(started > 1 ? `${started} searches added. They'll run one after another.` : "Search started. Watch progress below.");
    state.categories = [];
    renderCategories();
    document.getElementById("jobs-list").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  updateSteps();
  refreshJobs();
});

// ---------- Your searches ----------

function socialsLine(job, active) {
  if (!job.find_socials) return "";
  const icon = '<i class="bi bi-instagram"></i>';
  if (job.stage !== "socials") {
    return active ? `<div class="small text-body-secondary mt-2">${icon} Website & social media check runs after Google Maps</div>` : "";
  }
  if (!job.socials_total) {
    return `<div class="small text-body-secondary mt-2">${icon} Social media: every business here was already checked earlier</div>`;
  }
  const checking = active && job.socials_checked < job.socials_total;
  const pct = Math.round((job.socials_checked / job.socials_total) * 100);
  const bar = checking
    ? `<div class="progress flex-grow-1" role="progressbar"><div class="progress-bar progress-bar-striped progress-bar-animated" style="width:${pct}%"></div></div>`
    : "";
  const text = checking
    ? `Checking websites & social media: ${job.socials_checked} of ${job.socials_total} done · ${job.socials_found} have accounts`
    : `Social media: ${job.socials_found} of ${job.socials_checked} businesses have accounts`;
  return `<div class="d-flex align-items-center gap-3 mt-2 small text-body-secondary">
    ${bar}<span class="text-nowrap">${icon} ${text}</span></div>`;
}

function jobItem(job) {
  const active = ACTIVE_STATUSES.includes(job.status);
  const pct = Math.min(100, Math.round((job.results_found / job.max_results) * 100));
  const mapsActive = active && job.stage !== "socials";
  const area = job.location_text || `${job.latitude.toFixed(4)}, ${job.longitude.toFixed(4)}`;
  const error = job.error
    ? `<div class="small ${job.status === "failed" ? "text-danger" : "text-body-secondary"} mt-2">
        <i class="bi bi-info-circle"></i> ${esc(job.error)}</div>`
    : "";
  const counts = job.results_found
    ? `${job.results_found} found
       <span data-bs-toggle="tooltip" title="Businesses that weren't already in your leads">· ${job.results_new} new</span>`
    : active ? (job.status === "pending" ? "Waiting for its turn…" : "Opening Google Maps…") : "Nothing found";
  const nfcCaps = job.max_rating != null || job.max_reviews != null
    ? ` · <span data-bs-toggle="tooltip" title="Only businesses within these Google rating / review caps were kept"><i class="bi bi-credit-card-2-front"></i> NFC ≤${job.max_rating ?? "any"}★ / ≤${job.max_reviews ?? "any"} reviews</span>`
    : "";
  const areaSize = job.area_shape === "polygon"
    ? `<span data-bs-toggle="tooltip" title="Only businesses inside the freehand drawn shape were kept"><i class="bi bi-pencil"></i> drawn area</span>`
    : job.area_shape === "rectangle"
      ? `<span data-bs-toggle="tooltip" title="Only businesses inside the drawn rectangle were kept"><i class="bi bi-square"></i> rectangle</span>`
      : formatDistance(job.radius_m);

  return `<div class="job-item">
    <div class="d-flex flex-wrap justify-content-between align-items-start gap-2">
      <div class="me-auto">
        <div class="fw-semibold text-capitalize">${esc(job.query)}</div>
        <div class="small text-body-secondary">
          <i class="bi bi-geo-alt"></i> ${esc(area)} · ${areaSize}${nfcCaps} · ${esc(fmtRelative(job.started_at || job.created_at))}
        </div>
      </div>
      <div class="d-flex align-items-center gap-2">
        ${searchStatusPill(job.status)}
        ${job.results_found ? `<a class="btn btn-sm btn-outline-primary" href="/businesses?search_job_id=${job.id}">
          <i class="bi bi-person-lines-fill"></i> View leads</a>` : ""}
        ${active ? `<button class="btn btn-sm btn-outline-danger" data-cancel="${job.id}"><i class="bi bi-stop-fill"></i> Stop</button>` : ""}
        ${!active && !job.results_found ? `<button class="btn btn-sm btn-ghost text-danger" data-delete-job="${job.id}"
          title="Delete this search (it found nothing)"><i class="bi bi-trash"></i></button>` : ""}
      </div>
    </div>
    <div class="d-flex align-items-center gap-3 mt-2">
      <div class="progress flex-grow-1" role="progressbar"><div class="progress-bar ${mapsActive ? "progress-bar-striped progress-bar-animated" : ""}" style="width:${pct}%"></div></div>
      <div class="small text-body-secondary text-nowrap">${counts} <span class="text-body-tertiary">/ ${job.max_results} max</span></div>
    </div>
    ${socialsLine(job, active)}
    ${error}
  </div>`;
}

let jobsTimer = null;

async function refreshJobs() {
  clearTimeout(jobsTimer);
  let anyActive = false;
  const list = document.getElementById("jobs-list");
  try {
    const page = await api("/searches?per_page=10");
    anyActive = page.items.some((j) => ACTIVE_STATUSES.includes(j.status));
    disposeTooltips(list);
    list.innerHTML = page.items.length
      ? page.items.map(jobItem).join("")
      : `<div class="empty-state"><i class="bi bi-search"></i>
          <div class="fw-semibold text-body">No searches yet</div>
          <div class="small">Follow steps 1–3 above to find your first businesses.</div></div>`;
    initTooltips(list);
    const hasEmpty = page.items.some((j) => !ACTIVE_STATUSES.includes(j.status) && !j.results_found);
    document.getElementById("clear-empty-jobs").classList.toggle("d-none", !hasEmpty);
    list.querySelectorAll("[data-delete-job]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await api(`/searches/${btn.dataset.deleteJob}`, { method: "DELETE" });
          toast("Search deleted");
        } catch (err) {
          toast(err.message, "danger");
        }
        refreshJobs();
      }),
    );
    list.querySelectorAll("[data-cancel]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        const ok = await confirmDialog({
          title: "Stop this search?",
          body: "Businesses found so far stay in your leads. You can start the search again later.",
          confirmText: "Stop search",
        });
        if (!ok) return;
        btn.disabled = true;
        try {
          await api(`/searches/${btn.dataset.cancel}/cancel`, { method: "POST" });
          toast("Stopping… businesses found so far are kept");
        } catch (err) {
          toast(err.message, "danger");
        }
        refreshJobs();
      }),
    );
  } catch (err) {
    list.innerHTML = `<div class="empty-state text-danger">Couldn't load searches: ${esc(err.message)}</div>`;
  }
  jobsTimer = setTimeout(refreshJobs, anyActive ? 3000 : 15000);
}

document.getElementById("clear-empty-jobs").addEventListener("click", async () => {
  const ok = await confirmDialog({
    title: "Clear empty searches?",
    body: "Removes every finished search that found no businesses (failed, stopped or empty ones). "
      + "Searches with results and all your leads stay untouched.",
    confirmText: "Clear them",
  });
  if (!ok) return;
  try {
    const { deleted } = await api("/searches/empty", { method: "DELETE" });
    toast(`Removed ${deleted} empty search${deleted === 1 ? "" : "es"}`);
  } catch (err) {
    toast(err.message, "danger");
  }
  refreshJobs();
});

// Only auto-locate when permission was already given, so the page never pops a prompt on load.
navigator.permissions?.query({ name: "geolocation" }).then((perm) => {
  if (perm.state === "granted" && !hasArea()) locateBtn.click();
});

syncShapeUi();
renderCategories();
refreshJobs();
