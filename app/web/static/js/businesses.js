const form = document.getElementById("filters");
const FILTER_NAMES = [
  "q", "status", "category", "sort", "order", "has_phone", "has_website",
  "claimed", "social", "website_quality", "has_email", "min_rating", "nfc_prospect", "service", "follow_up_due", "search_job_id",
];
const MORE_FILTERS = [
  "category", "has_phone", "has_website", "claimed", "social", "website_quality", "has_email", "min_rating", "nfc_prospect", "service",
];
const selected = new Set();
let pageIds = [];
let lastTotal = 0;
// Sensible direction per sort, so beginners don't need an order control.
const SORT_ORDER = {
  created_at: "desc", name: "asc", rating: "desc", review_count: "desc", follow_up_date: "asc", last_contacted_at: "desc",
};
let page = 1;
let perPage = 25;
let totalLeads = null;

function readFiltersFromUrl() {
  const params = new URLSearchParams(location.search);
  for (const name of FILTER_NAMES) {
    const field = form.elements[name];
    if (!field) continue;
    if (field.type === "checkbox") field.checked = params.get(name) === "true";
    else field.value = params.get(name) || (name === "sort" ? "created_at" : "");
  }
  page = Number(params.get("page")) || 1;
  perPage = Number(params.get("per_page")) || 25;
  document.getElementById("per-page").value = String(perPage);
  if (MORE_FILTERS.some((n) => form.elements[n].value)) {
    document.getElementById("more-filters").classList.add("show");
  }
}

function currentFilters() {
  form.elements.order.value = form.elements.order.value || SORT_ORDER[form.elements.sort.value] || "desc";
  const params = new URLSearchParams();
  for (const name of FILTER_NAMES) {
    const field = form.elements[name];
    if (!field) continue;
    if (field.type === "checkbox") {
      if (field.checked) params.set(name, "true");
    } else if (field.value.trim()) {
      params.set(name, field.value.trim());
    }
  }
  return params;
}

function hasActiveFilters() {
  return ["q", "status", "follow_up_due", "search_job_id", ...MORE_FILTERS].some((n) => {
    const f = form.elements[n];
    return f.type === "checkbox" ? f.checked : f.value.trim();
  });
}

function webPresence(b) {
  const site = websiteInfo(b.website);
  const profiles = b.social_profiles || [];
  // A social link listed as the "website" is already shown as an icon.
  const showSite = site && (site.icon === "bi-globe2" || !profiles.length);
  const parts = [];
  if (showSite) parts.push(`<div class="text-truncate">${websiteLink(b.website)}</div>`);
  if (profiles.length) parts.push(`<div class="d-flex gap-1 ${showSite ? "mt-1" : ""}">${socialIcons(profiles)}</div>`);
  const issues = b.website_issues || [];
  const extras = [];
  if (issues.length) {
    extras.push(`<span class="issue-badge" data-bs-toggle="tooltip" title="${esc(issues.join(" · "))}">
      <i class="bi bi-exclamation-triangle"></i>${issues.length} website problem${issues.length === 1 ? "" : "s"}</span>`);
  }
  if (b.email) extras.push(`<i class="bi bi-envelope text-body-secondary" data-bs-toggle="tooltip" title="${esc(b.email)}"></i>`);
  if (b.whatsapp) extras.push(`<i class="bi bi-whatsapp text-success" data-bs-toggle="tooltip" title="WhatsApp ${esc(b.whatsapp)}"></i>`);
  if (extras.length) parts.push(`<div class="d-flex align-items-center gap-2 mt-1">${extras.join("")}</div>`);
  if (parts.length) return parts.join("");
  return b.social_checked_at
    ? '<span class="text-body-tertiary" data-bs-toggle="tooltip" title="Checked: no website or social media found. A good prospect!">None found</span>'
    : '<span class="text-body-tertiary">No website</span>';
}

function rowHtml(b) {
  const unclaimed = b.claimed === false
    ? ` <span class="pill pill-warning ms-1" data-bs-toggle="tooltip"
          title="Nobody manages this Google listing; a good sign they need help online">Unclaimed</span>`
    : "";
  const nfc = b.service_nfc === "sold"
    ? ' <span class="pill pill-success ms-1" data-bs-toggle="tooltip" title="You sold them a review NFC card"><i class="bi bi-credit-card-2-front"></i>NFC</span>'
    : b.nfc_reasons?.length && !b.service_nfc
      ? ` <span class="pill pill-info ms-1" data-bs-toggle="tooltip" title="${esc(`Good review NFC card prospect: ${b.nfc_reasons.join(" · ")}`)}"><i class="bi bi-credit-card-2-front"></i>NFC</span>`
      : "";
  return `<tr data-id="${b.id}" class="${selected.has(b.id) ? "row-selected" : ""}">
    <td class="select-col"><input type="checkbox" class="form-check-input" data-select="${b.id}" ${selected.has(b.id) ? "checked" : ""}
      aria-label="Select ${esc(b.name)}"></td>
    <td>
      <div class="fw-semibold">${esc(b.name)}${unclaimed}${nfc}</div>
      <div class="small text-body-secondary text-truncate-cell">${esc(b.category || "")}${b.address ? ` · ${esc(b.address)}` : ""}</div>
    </td>
    <td>${phoneChip(b.phone)}</td>
    <td class="small" style="max-width: 200px">${webPresence(b)}</td>
    <td class="small">${ratingText(b.rating, b.review_count)}</td>
    <td><select class="form-select form-select-sm status-select" data-status-for="${b.id}" aria-label="Lead status">${statusOptions(b.lead_status)}</select></td>
    <td class="small">${fmtFollowUp(b.follow_up_date)}</td>
    <td class="text-end text-body-tertiary"><i class="bi bi-chevron-right"></i></td>
  </tr>`;
}

function emptyHtml() {
  if (totalLeads === 0) {
    return `<tr><td colspan="8"><div class="empty-state">
      <i class="bi bi-person-lines-fill"></i>
      <div class="fw-semibold text-body">No leads yet</div>
      <div class="small mb-3">Run a search and the businesses it finds will appear here.</div>
      <a href="/" class="btn btn-primary btn-sm"><i class="bi bi-search-heart"></i> Find businesses</a>
    </div></td></tr>`;
  }
  return `<tr><td colspan="8"><div class="empty-state">
    <i class="bi bi-funnel"></i>
    <div class="fw-semibold text-body">No leads match these filters</div>
    <button type="button" class="btn btn-link btn-sm" data-reset>Clear all filters</button>
  </div></td></tr>`;
}

function updateFilterIndicators() {
  const status = form.elements.status.value;
  document.querySelectorAll(".status-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.status === status));
  const more = MORE_FILTERS.filter((n) => form.elements[n].value).length;
  const badge = document.getElementById("more-count");
  badge.textContent = more;
  badge.classList.toggle("d-none", !more);
}

async function load({ pushUrl = true } = {}) {
  updateFilterIndicators();
  const filters = currentFilters();
  const query = new URLSearchParams(filters);
  query.set("page", page);
  query.set("per_page", perPage);
  if (pushUrl) history.replaceState(null, "", `?${query}`);
  document.getElementById("export-btn").href = `/api/businesses/export?${filters}`;

  const body = document.getElementById("businesses-body");
  try {
    const data = await api(`/businesses?${query}`);
    document.getElementById("total-count").textContent = hasActiveFilters()
      ? `· ${data.total.toLocaleString()} shown`
      : `· ${data.total.toLocaleString()}`;
    disposeTooltips(body);
    body.innerHTML = data.items.length ? data.items.map(rowHtml).join("") : emptyHtml();
    initTooltips(body);
    pageIds = data.items.map((b) => b.id);
    lastTotal = data.total;
    updateSelection();
    body.querySelector("[data-reset]")?.addEventListener("click", resetFilters);

    const first = data.total ? (data.page - 1) * data.per_page + 1 : 0;
    const last = Math.min(data.page * data.per_page, data.total);
    document.getElementById("page-info").textContent = data.total ? `Showing ${first}–${last} of ${data.total.toLocaleString()}` : "";
    document.getElementById("prev-page").disabled = data.page <= 1;
    document.getElementById("next-page").disabled = data.page >= data.pages;
  } catch (err) {
    body.innerHTML = `<tr><td colspan="8" class="empty-state text-danger">${esc(err.message)}</td></tr>`;
  }
}

async function loadCounts() {
  try {
    const stats = await api("/businesses/stats");
    totalLeads = stats.total;
    document.querySelector('[data-count="total"]').textContent = stats.total.toLocaleString();
    for (const [status, count] of Object.entries(stats.by_status)) {
      const el = document.querySelector(`[data-count="${status}"]`);
      if (el) el.textContent = count.toLocaleString();
    }
    document.getElementById("followups-count").textContent = stats.follow_ups_due || "";
    if (!bulkRunning) {
      document.getElementById("bulk-socials-count").textContent = stats.needs_check;
      document.getElementById("bulk-socials-btn").classList.toggle("d-none", !stats.needs_check);
    }
  } catch {
    // Counts are a convenience; ignore.
  }
}

async function showJobFilter() {
  const jobId = form.elements.search_job_id.value;
  const box = document.getElementById("job-filter");
  if (!jobId) {
    box.classList.add("d-none");
    return;
  }
  let label = `search #${jobId}`;
  try {
    const job = await api(`/searches/${jobId}`);
    label = `"${job.query}" near ${job.location_text || "the map point"}`;
  } catch {
    // Show the id only.
  }
  box.innerHTML = `<span class="pill pill-primary py-2 px-3">
    <i class="bi bi-funnel"></i> Showing results of the search ${esc(label)}
    <button type="button" class="btn-close ms-2" style="font-size: .55rem" id="clear-job" aria-label="Show all leads"></button></span>`;
  box.classList.remove("d-none");
  document.getElementById("clear-job").addEventListener("click", () => {
    form.elements.search_job_id.value = "";
    showJobFilter();
    page = 1;
    load();
  });
}

function resetFilters() {
  form.reset();
  for (const name of ["status", "search_job_id", "order"]) form.elements[name].value = "";
  form.elements.sort.value = "created_at";
  showJobFilter();
  page = 1;
  load();
}

let typingTimer = null;
form.addEventListener("input", (e) => {
  if (e.target === form.elements.sort) form.elements.order.value = SORT_ORDER[e.target.value];
  clearTimeout(typingTimer);
  const delay = e.target.type === "search" || e.target.type === "text" ? 350 : 0;
  typingTimer = setTimeout(() => {
    page = 1;
    load();
  }, delay);
});
form.addEventListener("submit", (e) => e.preventDefault());

document.querySelectorAll(".status-tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    bootstrap.Tooltip.getInstance(tab)?.hide();
    form.elements.status.value = tab.dataset.status;
    page = 1;
    load();
  }),
);

document.getElementById("per-page").addEventListener("change", (e) => {
  perPage = Number(e.target.value);
  page = 1;
  load();
});
document.getElementById("prev-page").addEventListener("click", () => {
  page = Math.max(1, page - 1);
  load();
});
document.getElementById("next-page").addEventListener("click", () => {
  page += 1;
  load();
});

const tableBody = document.getElementById("businesses-body");
tableBody.addEventListener("click", (e) => {
  if (e.target.closest("a, select, button, input, .select-col")) {
    const cell = e.target.closest(".select-col");
    if (cell && e.target === cell) cell.querySelector("input").click();
    return;
  }
  const row = e.target.closest("tr[data-id]");
  if (row) location.href = `/businesses/${row.dataset.id}`;
});
tableBody.addEventListener("change", async (e) => {
  const box = e.target.closest("[data-select]");
  if (box) {
    const id = Number(box.dataset.select);
    if (box.checked) selected.add(id);
    else selected.delete(id);
    updateSelection();
    return;
  }
  const select = e.target.closest("[data-status-for]");
  if (!select) return;
  select.disabled = true;
  try {
    await api(`/businesses/${select.dataset.statusFor}`, { method: "PATCH", body: { lead_status: select.value } });
    toast(`Status changed to "${STATUS_BY_VALUE[select.value].label}"`);
    loadCounts();
  } catch (err) {
    toast(err.message, "danger");
  }
  select.disabled = false;
});

// ---------- Select leads to visit ----------

const selectPage = document.getElementById("select-page");
const tripTarget = document.getElementById("trip-target");

function updateSelection() {
  tableBody.querySelectorAll("[data-select]").forEach((box) => {
    box.checked = selected.has(Number(box.dataset.select));
    box.closest("tr").classList.toggle("row-selected", box.checked);
  });
  const onPage = pageIds.filter((id) => selected.has(id)).length;
  selectPage.checked = pageIds.length > 0 && onPage === pageIds.length;
  selectPage.indeterminate = onPage > 0 && onPage < pageIds.length;
  document.getElementById("selected-count").textContent = selected.size;
  document.getElementById("selection-bar").classList.toggle("d-none", !selected.size);
  const matching = document.getElementById("select-all-matching");
  matching.classList.toggle("d-none", !(selectPage.checked && lastTotal > pageIds.length && selected.size < lastTotal));
  matching.querySelector("[data-page-count]").textContent = pageIds.length;
  matching.querySelector("[data-total]").textContent = lastTotal.toLocaleString();
}

selectPage.addEventListener("change", () => {
  pageIds.forEach((id) => (selectPage.checked ? selected.add(id) : selected.delete(id)));
  updateSelection();
});

document.querySelector("[data-select-matching]").addEventListener("click", async () => {
  try {
    // Only leads with a location can be visited, which is what the map endpoint returns.
    const points = await api(`/businesses/map?${currentFilters()}`);
    points.forEach((p) => selected.add(p.id));
    updateSelection();
  } catch (err) {
    toast(err.message, "danger");
  }
});

document.getElementById("clear-selection").addEventListener("click", () => {
  selected.clear();
  updateSelection();
});

async function loadTripOptions() {
  try {
    const trips = await api("/trips");
    tripTarget.innerHTML = '<option value="new">A new trip</option>'
      + trips.map((t) => `<option value="${t.id}">${esc(t.name)} (${t.stop_count} stops)</option>`).join("");
  } catch {
    // "A new trip" still works.
  }
}

document.getElementById("add-to-trip").addEventListener("click", async () => {
  const ids = [...selected];
  try {
    const result = tripTarget.value === "new"
      ? await api("/trips", { method: "POST", body: { business_ids: ids } })
      : await api(`/trips/${tripTarget.value}/stops`, { method: "POST", body: { business_ids: ids } });
    if (result.skipped.length) {
      const reasons = {};
      result.skipped.forEach((s) => { reasons[s.reason] = (reasons[s.reason] || 0) + 1; });
      toast(`Skipped ${result.skipped.length}: ${Object.entries(reasons).map(([r, n]) => `${n} ${r}`).join(", ")}`, "info");
    }
    if (!result.added && !result.trip.stop_count) {
      if (tripTarget.value === "new") await api(`/trips/${result.trip.id}`, { method: "DELETE" });
      return;
    }
    window.location.href = `/trips/${result.trip.id}`;
  } catch (err) {
    toast(err.message, "danger");
  }
});

// ---------- Find social media for leads never checked ----------

let bulkRunning = false;
let bulkStop = false;

async function uncheckedLeadIds() {
  const ids = [];
  for (let p = 1; ; p += 1) {
    const data = await api(`/businesses?social=needs_check&per_page=100&page=${p}`);
    ids.push(...data.items.map((b) => b.id));
    if (p >= data.pages) return ids;
  }
}

document.getElementById("bulk-socials-btn").addEventListener("click", async () => {
  const btn = document.getElementById("bulk-socials-btn");
  const count = btn.querySelector("#bulk-socials-count").textContent;
  const ok = await confirmDialog({
    title: `Check websites & social media for ${count} leads?`,
    body: "For each lead that hasn't been checked, the app opens the website from their Google listing, checks whether "
      + "it's secure, works on phones and looks up to date, and saves the Facebook, Instagram and TikTok accounts, "
      + "email and WhatsApp number it links to. It doesn't use Google, so it can't get you blocked. "
      + "Keep this page open; you can stop any time.",
    confirmText: "Start",
    danger: false,
  });
  if (!ok) return;

  bulkRunning = true;
  bulkStop = false;
  bootstrap.Tooltip.getInstance(btn)?.hide();
  btn.classList.add("d-none");
  const panel = document.getElementById("bulk-socials-panel");
  const text = document.getElementById("bulk-socials-text");
  const bar = document.getElementById("bulk-socials-bar");
  panel.classList.remove("d-none");
  document.getElementById("bulk-socials-spinner").classList.remove("d-none");

  let done = 0;
  let found = 0;
  try {
    const ids = await uncheckedLeadIds();
    for (const id of ids) {
      if (bulkStop) break;
      text.textContent = `Checking websites & social media: ${done} of ${ids.length} done · ${found} have accounts`;
      bar.style.width = `${Math.round((done / ids.length) * 100)}%`;
      try {
        const result = await api(`/businesses/${id}/socials/find`, { method: "POST" });
        if (result.business.social_profiles.length) found += 1;
      } catch {
        // One failing lead shouldn't stop the rest.
      }
      done += 1;
    }
    toast(`${bulkStop ? "Stopped. " : ""}Checked ${done} leads: ${found} have social media`, bulkStop ? "info" : "success");
  } catch (err) {
    toast(err.message, "danger");
  }
  bulkRunning = false;
  panel.classList.add("d-none");
  loadCounts();
  load({ pushUrl: false });
});

document.getElementById("bulk-socials-stop").addEventListener("click", () => {
  bulkStop = true;
  document.getElementById("bulk-socials-text").textContent = "Stopping after this website…";
});

window.addEventListener("beforeunload", (e) => {
  if (bulkRunning) {
    e.preventDefault();
    e.returnValue = "";
  }
});

readFiltersFromUrl();
showJobFilter();
loadTripOptions();
loadCounts().then(() => load({ pushUrl: false }));
