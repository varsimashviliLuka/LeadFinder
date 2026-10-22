const TBILISI = [41.7151, 44.8271];
const ACTIVE_STATUSES = ["pending", "running"];
const SECONDS_PER_BUSINESS = 15;
const SECONDS_BETWEEN_SEARCHES = 90;
const SECONDS_PER_SOCIAL_CHECK = 5;
const SECONDS_PER_REVIEW_CHECK = 8;

const state = {
  point: null,
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
const circle = L.circle(TBILISI, { radius: 1000, color: "#4f46e5", weight: 2, fillOpacity: 0.08 });
const radiusInput = document.getElementById("radius-input");
const locationLabel = document.getElementById("location-label");

function radiusMeters() {
  return Number(radiusInput.value);
}

function shortName(displayName) {
  return displayName.split(",").slice(0, 3).join(",").trim();
}

async function setPoint(lat, lng, label = null, { fit = true } = {}) {
  state.point = { lat, lng };
  marker.setLatLng([lat, lng]).addTo(map);
  circle.setLatLng([lat, lng]).setRadius(radiusMeters()).addTo(map);
  if (fit) map.fitBounds(circle.getBounds(), { padding: [24, 24] });

  state.label = label || `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  locationLabel.textContent = state.label;
  updateSteps();
  if (label) return;

  try {
    const place = await api(`/geocode/reverse?lat=${lat}&lng=${lng}`);
    if (state.point && state.point.lat === lat && state.point.lng === lng) {
      state.label = shortName(place.display_name);
      locationLabel.textContent = state.label;
      updateSteps();
    }
  } catch {
    // Keep coordinates as the label.
  }
}

map.on("click", (e) => setPoint(e.latlng.lat, e.latlng.lng, null, { fit: false }));
marker.on("dragend", () => {
  const { lat, lng } = marker.getLatLng();
  setPoint(lat, lng, null, { fit: false });
});

radiusInput.addEventListener("input", () => {
  document.getElementById("radius-value").textContent = formatDistance(radiusMeters());
  circle.setRadius(radiusMeters());
  updateSteps();
});
radiusInput.addEventListener("change", () => {
  if (state.point) map.fitBounds(circle.getBounds(), { padding: [24, 24] });
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

function estimateMinutes() {
  const n = state.categories.length;
  const perBusiness = SECONDS_PER_BUSINESS
    + (findSocialsInput.checked ? SECONDS_PER_SOCIAL_CHECK : 0)
    + (collectReviewsInput.checked ? SECONDS_PER_REVIEW_CHECK : 0);
  const seconds = n * Number(maxResultsInput.value) * perBusiness + Math.max(0, n - 1) * SECONDS_BETWEEN_SEARCHES;
  return Math.max(1, Math.round(seconds / 60));
}

function updateSteps() {
  const hasArea = Boolean(state.point);
  const hasTypes = state.categories.length > 0;
  document.getElementById("step-area").classList.toggle("is-done", hasArea);
  document.getElementById("step-types").classList.toggle("is-done", hasTypes);
  document.getElementById("search-submit").disabled = !(hasArea && hasTypes);

  const summary = document.getElementById("search-summary");
  if (!hasArea || !hasTypes) {
    const missing = [!hasArea && "pick an area on the map (step 1)", !hasTypes && "choose at least one business type (step 2)"]
      .filter(Boolean)
      .join(" and ");
    summary.innerHTML = `<span class="text-body-secondary"><i class="bi bi-info-circle"></i> To start, ${missing}.</span>`;
    return;
  }
  const types = state.categories.map((c) => `<strong>${esc(c)}</strong>`).join(", ");
  summary.innerHTML = `
    <div class="mb-1"><i class="bi bi-search text-body-secondary"></i> Look for ${types}</div>
    <div class="mb-1"><i class="bi bi-geo-alt text-body-secondary"></i> Within ${formatDistance(radiusMeters())} of <strong>${esc(state.label)}</strong></div>
    ${collectReviewsInput.checked ? '<div class="mb-1"><i class="bi bi-chat-square-quote text-body-secondary"></i> Read each one\'s latest reviews</div>' : ""}
    ${findSocialsInput.checked ? '<div class="mb-1"><i class="bi bi-instagram text-body-secondary"></i> Then check their websites and find social media, email and WhatsApp</div>' : ""}
    <div><i class="bi bi-clock text-body-secondary"></i> Up to ${maxResultsInput.value} of each · roughly ${estimateMinutes()} min at most</div>`;
}

document.getElementById("search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.point || !state.categories.length) return;

  const submit = document.getElementById("search-submit");
  submit.disabled = true;
  submit.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Starting…';
  let started = 0;
  for (const query of state.categories) {
    try {
      await api("/searches", {
        method: "POST",
        body: {
          query,
          latitude: state.point.lat,
          longitude: state.point.lng,
          location_text: state.label,
          radius_m: radiusMeters(),
          max_results: Number(maxResultsInput.value),
          find_socials: findSocialsInput.checked,
          collect_reviews: collectReviewsInput.checked,
        },
      });
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

  return `<div class="job-item">
    <div class="d-flex flex-wrap justify-content-between align-items-start gap-2">
      <div class="me-auto">
        <div class="fw-semibold text-capitalize">${esc(job.query)}</div>
        <div class="small text-body-secondary">
          <i class="bi bi-geo-alt"></i> ${esc(area)} · ${formatDistance(job.radius_m)} · ${esc(fmtRelative(job.started_at || job.created_at))}
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
  if (perm.state === "granted" && !state.point) locateBtn.click();
});

renderCategories();
refreshJobs();
