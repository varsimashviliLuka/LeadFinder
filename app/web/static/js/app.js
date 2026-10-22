// Shared helpers for all pages.

const STATUS_BY_VALUE = Object.fromEntries(window.APP.statuses.map((s) => [s.value, s]));
const SEARCH_STATUS_BY_VALUE = Object.fromEntries(window.APP.searchStatuses.map((s) => [s.value, s]));

// ---------- Theme ----------

function currentTheme() {
  return document.documentElement.getAttribute("data-bs-theme") || "light";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-bs-theme", theme);
  localStorage.setItem("theme", theme);
  document.querySelectorAll(".theme-label").forEach((el) => {
    el.textContent = theme === "dark" ? "Light mode" : "Dark mode";
  });
}

document.querySelectorAll(".theme-toggle").forEach((btn) =>
  btn.addEventListener("click", () => applyTheme(currentTheme() === "dark" ? "light" : "dark")),
);
applyTheme(currentTheme());

// ---------- API ----------

async function api(path, { method = "GET", body } = {}) {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || `Request failed (${response.status})`);
  return data;
}

// ---------- Formatting ----------

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

// Scraped URLs are untrusted; only allow real web links.
function safeUrl(url) {
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}

function websiteInfo(url) {
  const href = safeUrl(url);
  if (!href) return null;
  const host = new URL(href).hostname.replace(/^www\./, "");
  if (host.endsWith("instagram.com")) return { href, icon: "bi-instagram", text: "Instagram" };
  if (host.endsWith("facebook.com")) return { href, icon: "bi-facebook", text: "Facebook" };
  if (host.endsWith("tiktok.com")) return { href, icon: "bi-tiktok", text: "TikTok" };
  return { href, icon: "bi-globe2", text: host };
}

function websiteLink(url) {
  const info = websiteInfo(url);
  if (!info) return '<span class="text-body-tertiary">No website</span>';
  return `<a href="${esc(info.href)}" target="_blank" rel="noopener noreferrer" class="text-decoration-none">
    <i class="bi ${info.icon} me-1"></i>${esc(info.text)}</a>`;
}

const SOCIAL_META = {
  facebook: { label: "Facebook", icon: "bi-facebook" },
  instagram: { label: "Instagram", icon: "bi-instagram" },
  tiktok: { label: "TikTok", icon: "bi-tiktok" },
};
const SOCIAL_SOURCE_LABELS = {
  google_maps: "Listed on their Google Maps page",
  website: "Linked from their own website",
  manual: "Added by you",
};

function socialName(profile) {
  if (profile.handle) return profile.platform === "tiktok" ? `@${profile.handle}` : profile.handle;
  return `${SOCIAL_META[profile.platform].label} page`;
}

function socialIcons(profiles) {
  return (profiles || [])
    .map((p) => {
      const href = safeUrl(p.url);
      if (!href) return "";
      const meta = SOCIAL_META[p.platform];
      return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer" class="social-icon social-${p.platform}"
        data-bs-toggle="tooltip" title="${esc(`${meta.label}: ${socialName(p)}`)}"><i class="bi ${meta.icon}"></i></a>`;
    })
    .join("");
}

function telHref(phone) {
  return `tel:${phone.replace(/[^\d+]/g, "")}`;
}

function phoneChip(phone) {
  if (!phone) return '<span class="text-body-tertiary">No phone</span>';
  return `<a href="${esc(telHref(phone))}" class="phone-chip" title="Click to call">
    <i class="bi bi-telephone"></i>${esc(phone)}</a>`;
}

// ---------- Messaging ----------

// Georgian mobile numbers are +995 5XX XXX XXX; landlines can't use WhatsApp or Viber.
function isMobileNumber(phone) {
  return /^9955\d{8}$/.test((phone || "").replace(/\D/g, ""));
}

// Digits (with country code) to message on WhatsApp/Viber, or null.
function messagingNumber(b) {
  if (b.whatsapp) return b.whatsapp.replace(/\D/g, "");
  return isMobileNumber(b.phone) ? b.phone.replace(/\D/g, "") : null;
}

function fillTemplate(body, b) {
  return body
    .replaceAll("{name}", b.name || "")
    .replaceAll("{category}", (b.category || "").toLowerCase());
}

const CHANNELS = {
  whatsapp: { label: "WhatsApp", icon: "bi-whatsapp", cls: "btn-whatsapp" },
  viber: { label: "Viber", icon: "bi-chat-dots-fill", cls: "btn-viber" },
  email: { label: "Email", icon: "bi-envelope-fill", cls: "btn-outline-secondary" },
};

function channelHref(channel, b, text, subject = "") {
  const digits = messagingNumber(b);
  if (channel === "whatsapp") return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
  if (channel === "viber") return `viber://chat?number=${encodeURIComponent(`+${digits}`)}`;
  return `mailto:${encodeURIComponent(b.email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(text)}`;
}

function availableChannels(b) {
  const digits = messagingNumber(b);
  return Object.keys(CHANNELS).filter((c) => (c === "email" ? !!b.email : !!digits));
}

function statusPill(status) {
  const s = STATUS_BY_VALUE[status] || { label: status, color: "secondary", icon: "bi-circle", help: "" };
  return `<span class="pill pill-${s.color}" title="${esc(s.help)}"><i class="bi ${s.icon}"></i>${esc(s.label)}</span>`;
}

function searchStatusPill(status) {
  const s = SEARCH_STATUS_BY_VALUE[status] || { label: status, color: "secondary", icon: "bi-circle", help: "" };
  const icon = status === "running"
    ? '<span class="spinner-border spinner-border-sm" style="width:.75rem;height:.75rem"></span>'
    : `<i class="bi ${s.icon}"></i>`;
  return `<span class="pill pill-${s.color}" title="${esc(s.help)}">${icon}${esc(s.label)}</span>`;
}

function statusOptions(selected, values = window.APP.statuses.map((s) => s.value)) {
  return values
    .map((v) => `<option value="${v}" ${v === selected ? "selected" : ""}>${esc(STATUS_BY_VALUE[v].label)}</option>`)
    .join("");
}

function ratingText(rating, reviews) {
  if (rating == null) return '<span class="text-body-tertiary">No rating</span>';
  const count = reviews != null
    ? ` <span class="text-body-secondary">· ${reviews.toLocaleString()} review${reviews === 1 ? "" : "s"}</span>`
    : "";
  return `<span class="text-nowrap"><i class="bi bi-star-fill text-warning"></i> ${rating.toFixed(1)}${count}</span>`;
}

function formatDistance(meters) {
  return meters < 1000 ? `${meters} m` : `${(meters / 1000).toFixed(1).replace(/\.0$/, "")} km`;
}

// The API returns UTC timestamps without a zone suffix.
function parseUtc(iso) {
  if (!iso) return null;
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
}

function fmtDateTime(iso) {
  const d = parseUtc(iso);
  return d ? d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—";
}

function fmtRelative(iso) {
  const d = parseUtc(iso);
  if (!d) return "—";
  const seconds = Math.round((Date.now() - d.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 172800) return "yesterday";
  return d.toLocaleDateString();
}

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fmtFollowUp(isoDate) {
  if (!isoDate) return '<span class="text-body-tertiary">—</span>';
  const today = todayIso();
  const label = new Date(`${isoDate}T00:00:00`).toLocaleDateString([], { month: "short", day: "numeric" });
  if (isoDate < today) return `<span class="text-danger fw-semibold" title="Overdue"><i class="bi bi-alarm"></i> ${label}</span>`;
  if (isoDate === today) return `<span class="text-warning-emphasis fw-semibold"><i class="bi bi-alarm"></i> Today</span>`;
  return `<span>${label}</span>`;
}

// ---------- UI helpers ----------

function toast(message, type = "success") {
  const icons = { success: "bi-check-circle-fill", danger: "bi-exclamation-octagon-fill", info: "bi-info-circle-fill" };
  const el = document.createElement("div");
  el.className = "toast align-items-center border-0 shadow";
  el.innerHTML = `<div class="d-flex"><div class="toast-body d-flex gap-2 align-items-center">
      <i class="bi ${icons[type] || icons.info} text-${type === "danger" ? "danger" : type === "info" ? "primary" : "success"}"></i>
      <span>${esc(message)}</span></div>
    <button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
  document.getElementById("toasts").appendChild(el);
  const t = new bootstrap.Toast(el, { delay: type === "danger" ? 7000 : 3500 });
  el.addEventListener("hidden.bs.toast", () => el.remove());
  t.show();
}

function initTooltips(root = document) {
  root.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => bootstrap.Tooltip.getOrCreateInstance(el));
}

// Call before replacing a container's HTML so open tooltips don't linger.
function disposeTooltips(root) {
  root.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => bootstrap.Tooltip.getInstance(el)?.dispose());
}

function confirmDialog({ title, body, confirmText = "Delete", danger = true }) {
  return new Promise((resolve) => {
    const wrapper = document.createElement("div");
    wrapper.innerHTML = `<div class="modal fade" tabindex="-1"><div class="modal-dialog modal-dialog-centered"><div class="modal-content">
      <div class="modal-header border-0 pb-0"><h5 class="modal-title">${esc(title)}</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body text-body-secondary">${esc(body)}</div>
      <div class="modal-footer border-0 pt-0">
        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
        <button type="button" class="btn ${danger ? "btn-danger" : "btn-primary"}" data-confirm>${esc(confirmText)}</button>
      </div></div></div></div>`;
    const modalEl = wrapper.firstElementChild;
    document.body.appendChild(modalEl);
    const modal = new bootstrap.Modal(modalEl);
    let confirmed = false;
    modalEl.querySelector("[data-confirm]").addEventListener("click", () => {
      confirmed = true;
      modal.hide();
    });
    modalEl.addEventListener("hidden.bs.modal", () => {
      modalEl.remove();
      resolve(confirmed);
    });
    modal.show();
  });
}

// ---------- Scraper status (sidebar) ----------

async function refreshScraperStatus() {
  const el = document.getElementById("scraper-status");
  if (!el) return;
  try {
    const s = await api("/searches/scraper-status");
    disposeTooltips(el);
    if (s.provider !== "google_maps") {
      el.innerHTML = `<div class="small fw-semibold"><i class="bi bi-cone-striped text-warning"></i> Test mode</div>
        <div class="small text-body-secondary mt-1">Searches create sample data (<code>${esc(s.provider)}</code> scraper).</div>`;
      return;
    }
    if (s.blocked_until) {
      el.innerHTML = `<div class="small fw-semibold text-danger"><i class="bi bi-pause-circle-fill"></i> Searching paused</div>
        <div class="small text-body-secondary mt-1">Google showed a CAPTCHA. To stay safe, new searches wait until
        <strong>${esc(fmtDateTime(s.blocked_until))}</strong>.</div>`;
      return;
    }
    const pct = Math.min(100, Math.round((s.places_today / s.daily_limit) * 100));
    const cooldown = s.next_search_in > 0
      ? `<div class="small text-body-secondary mt-2"><i class="bi bi-hourglass-split"></i> Next search can start in ${s.next_search_in}s</div>`
      : "";
    el.innerHTML = `<div class="d-flex justify-content-between align-items-center small">
        <span class="fw-semibold">Today's searching</span>
        <i class="bi bi-question-circle help-icon" data-bs-toggle="tooltip" data-bs-placement="top"
           title="To avoid being blocked by Google, the app opens at most ${s.daily_limit} businesses per day and waits between searches."></i>
      </div>
      <div class="progress mt-2" role="progressbar"><div class="progress-bar" style="width:${pct}%; background: var(--accent)"></div></div>
      <div class="small text-body-secondary mt-1">${s.places_today} of ${s.daily_limit} businesses opened</div>${cooldown}`;
    initTooltips(el);
  } catch {
    el.innerHTML = "";
  }
}

refreshScraperStatus();
setInterval(refreshScraperStatus, 15000);
initTooltips();
