const businessId = document.getElementById("detail").dataset.businessId;
const LEAD_FIELDS = ["status", "followup", "phone", "email", "whatsapp", "website", "notes"];
let business = null;
let mapInitialized = false;
let dirty = false;

if (document.referrer.includes("/businesses?")) {
  document.getElementById("back-link").href = document.referrer;
}

// ---------- Rendering ----------

function infoRow(icon, label, valueHtml) {
  return `<div class="info-row"><i class="bi ${icon}"></i><div class="flex-grow-1">
    <div class="info-label">${label}</div><div>${valueHtml}</div></div></div>`;
}

function renderHeader(b) {
  document.getElementById("b-name").textContent = b.name;
  document.title = `${b.name} · Lead Finder`;
  document.getElementById("b-status").innerHTML = statusPill(b.lead_status);
  document.getElementById("b-claimed").innerHTML = b.claimed === false
    ? `<span class="pill pill-warning" data-bs-toggle="tooltip"
         title="The owner never claimed this Google Maps listing, which usually means nobody manages their online presence.">
         <i class="bi bi-patch-question"></i>Unclaimed listing</span>`
    : "";
  const parts = [b.category && esc(b.category), b.rating != null && ratingText(b.rating, b.review_count)].filter(Boolean);
  document.getElementById("b-subtitle").innerHTML = parts.join(' <span class="mx-1">·</span> ');

  const actions = [];
  if (b.phone) {
    actions.push(`<a class="btn btn-primary" href="${esc(telHref(b.phone))}"><i class="bi bi-telephone-fill"></i> Call ${esc(b.phone)}</a>`);
    actions.push(`<button type="button" class="btn btn-outline-secondary" id="copy-phone" title="Copy phone number"><i class="bi bi-clipboard"></i> Copy</button>`);
  }
  for (const channel of availableChannels(b)) {
    const c = CHANNELS[channel];
    actions.push(`<button type="button" class="btn ${c.cls}" data-message="${channel}">
      <i class="bi ${c.icon}"></i> ${c.label}</button>`);
  }
  const site = websiteInfo(b.website);
  if (site) {
    actions.push(`<a class="btn btn-outline-secondary" href="${esc(site.href)}" target="_blank" rel="noopener noreferrer">
      <i class="bi ${site.icon}"></i> ${site.icon === "bi-globe2" ? "Website" : esc(site.text)}</a>`);
  }
  const mapsUrl = safeUrl(b.maps_url);
  if (mapsUrl) {
    actions.push(`<a class="btn btn-outline-secondary" href="${esc(mapsUrl)}" target="_blank" rel="noopener noreferrer">
      <i class="bi bi-google"></i> Google Maps</a>`);
  }
  document.getElementById("b-actions").innerHTML = actions.join("");
  document.getElementById("copy-phone")?.addEventListener("click", async () => {
    await navigator.clipboard.writeText(b.phone);
    toast("Phone number copied");
  });
  document.querySelectorAll("#b-actions [data-message]").forEach((btn) =>
    btn.addEventListener("click", () => openMessage(btn.dataset.message)),
  );
}

function whatsappText(b) {
  if (b.whatsapp) return `${esc(b.whatsapp)} <span class="text-body-secondary small">· found on their website</span>`;
  if (isMobileNumber(b.phone)) {
    return `Probably ${esc(b.phone)} <span class="text-body-secondary small">· their phone is a mobile number</span>`;
  }
  return '<span class="text-body-tertiary">Not known. Their phone looks like a landline</span>';
}

function reviewsText(b) {
  if (b.recent_reviews_checked == null) {
    return '<span class="text-body-tertiary">Not read yet. Tick <em>Read latest reviews</em> when you start a search</span>';
  }
  if (!b.recent_reviews_checked) return '<span class="text-body-tertiary">No reviews on Google yet</span>';
  const parts = [];
  if (b.latest_review_date) {
    const days = Math.round((Date.now() - new Date(`${b.latest_review_date}T00:00:00`)) / 86400000);
    const stale = days > 180;
    parts.push(`Newest review <span class="${stale ? "text-danger-emphasis fw-semibold" : ""}">${esc(fmtAgo(days))}</span>`);
  }
  const replies = b.recent_owner_replies || 0;
  parts.push(`owner replied to <span class="${replies ? "" : "text-danger-emphasis fw-semibold"}">${replies} of the last ${b.recent_reviews_checked}</span>`);
  return parts.join(" · ");
}

function fmtAgo(days) {
  if (days < 1) return "today";
  if (days < 14) return `about ${days} day${days === 1 ? "" : "s"} ago`;
  if (days < 60) return `about ${Math.round(days / 7)} weeks ago`;
  if (days < 365) return `about ${Math.round(days / 30)} months ago`;
  const years = Math.round(days / 365);
  return `about ${years} year${years === 1 ? "" : "s"} ago`;
}

function renderContact(b) {
  const lastContacted = b.last_contacted_at
    ? `${esc(fmtDateTime(b.last_contacted_at))} <span class="text-body-secondary">(${esc(fmtRelative(b.last_contacted_at))})</span>`
    : '<span class="text-body-tertiary">Never. You haven\'t logged a call yet</span>';
  document.getElementById("b-contact").innerHTML = [
    infoRow("bi-telephone", "Phone", phoneChip(b.phone)),
    infoRow("bi-envelope", "Email", b.email
      ? `<a href="mailto:${esc(b.email)}">${esc(b.email)}</a>`
      : '<span class="text-body-tertiary">Not known. Add it in Your notes if you get one</span>'),
    infoRow("bi-whatsapp", "WhatsApp", whatsappText(b)),
    infoRow("bi-globe2", "Website", websiteLink(b.website)),
    infoRow("bi-chat-square-quote", "Google reviews", reviewsText(b)),
    ...(b.price_level ? [infoRow("bi-cash-coin", "Price level", esc(b.price_level))] : []),
    infoRow("bi-geo-alt", "Address", b.address ? esc(b.address) : '<span class="text-body-tertiary">Not listed</span>'),
    infoRow("bi-telephone-outbound", "Last contacted", lastContacted),
    infoRow("bi-calendar-plus", "Found on", esc(fmtDateTime(b.created_at))),
  ].join("");
}

function renderSocials(b) {
  const box = document.getElementById("b-socials");
  const profiles = b.social_profiles;
  document.querySelector("#find-socials-btn span").textContent = b.social_checked_at ? "Check again" : "Find accounts";

  if (profiles.length) {
    box.innerHTML = profiles
      .map((p) => {
        const href = safeUrl(p.url);
        const meta = SOCIAL_META[p.platform];
        return `<div class="social-row">
          <span class="social-icon social-${p.platform}"><i class="bi ${meta.icon}"></i></span>
          <div class="flex-grow-1 min-w-0">
            <a href="${esc(href)}" target="_blank" rel="noopener noreferrer" class="fw-semibold text-decoration-none">
              ${esc(socialName(p))} <i class="bi bi-box-arrow-up-right small"></i></a>
            <div class="small text-body-secondary">${esc(meta.label)} · ${esc(SOCIAL_SOURCE_LABELS[p.source] || p.source)}</div>
          </div>
          <button type="button" class="btn btn-sm btn-ghost text-danger" data-social-id="${p.id}" title="Remove this account">
            <i class="bi bi-x-lg"></i></button>
        </div>`;
      })
      .join("");
    box.querySelectorAll("[data-social-id]").forEach((btn) =>
      btn.addEventListener("click", () => removeSocial(btn.dataset.socialId)),
    );
    return;
  }

  let message;
  if (!b.social_checked_at) {
    message = `<div class="fw-semibold text-body">Not checked yet</div>
      <div class="small">Click <em>Find accounts</em> to look for the profiles linked from their Google listing and website.</div>`;
  } else if (!b.website) {
    message = `<div class="fw-semibold text-body">No website to look at</div>
      <div class="small">Their Google listing has no website, so there was nowhere to look. If you find their accounts, add them below.</div>`;
  } else {
    message = `<div class="fw-semibold text-body">No accounts found</div>
      <div class="small">Their website doesn't link to any. They may have none, which makes them a strong prospect.</div>`;
  }
  box.innerHTML = `<div class="empty-state py-4"><i class="bi bi-person-badge"></i>${message}</div>`;
}

async function removeSocial(profileId) {
  const profile = business.social_profiles.find((p) => String(p.id) === String(profileId));
  const ok = await confirmDialog({
    title: "Remove this account?",
    body: `${SOCIAL_META[profile.platform].label} "${socialName(profile)}" will be removed from this lead.`,
    confirmText: "Remove",
  });
  if (!ok) return;
  try {
    render(await api(`/businesses/${businessId}/socials/${profileId}`, { method: "DELETE" }), { keepForm: dirty });
    toast("Account removed");
  } catch (err) {
    toast(err.message, "danger");
  }
}

function checkRow(state, title, detail = "") {
  const icon = { ok: "bi-check-circle-fill", bad: "bi-x-circle-fill", info: "bi-info-circle" }[state];
  return `<div class="check-row check-${state}"><i class="bi ${icon}"></i><div>
    <div class="fw-semibold">${title}</div>${detail ? `<div class="small text-body-secondary">${detail}</div>` : ""}</div></div>`;
}

function renderWebsiteCheck(b) {
  const box = document.getElementById("b-website-check");
  const btn = document.getElementById("check-website-btn");
  const check = b.website_check;
  btn.classList.toggle("d-none", !b.website);
  btn.querySelector("span").textContent = check ? "Check again" : "Check website";

  if (!b.website) {
    box.innerHTML = `<div class="empty-state py-4"><i class="bi bi-globe2"></i>
      <div class="fw-semibold text-body">No website</div>
      <div class="small">They rely on Google Maps and social media only, so content you create is even more important to them.</div></div>`;
    return;
  }
  if (!check) {
    box.innerHTML = `<div class="empty-state py-4"><i class="bi bi-window-sidebar"></i>
      <div class="fw-semibold text-body">Not checked yet</div>
      <div class="small">Click <em>Check website</em>. It opens their homepage once and also looks for social accounts, email and WhatsApp.</div></div>`;
    return;
  }
  if ("social_only" in check) {
    const platform = SOCIAL_META[check.social_only]?.label || "a social media page";
    box.innerHTML = checkRow("bad", "No real website", `The website link on Google goes to ${esc(platform)}.`)
      + checkRow("info", "Good to mention", "A simple website with their photos and prices helps them show up in Google searches.");
    return;
  }
  if (check.error) {
    box.innerHTML = checkRow("bad", "Their website doesn't open", esc(check.error))
      + checkRow("info", "Good to mention", "Customers who click the website link on Google hit a dead end.");
    return;
  }
  const outdatedYear = new Date().getFullYear() - 2;
  const rows = [
    check.https
      ? checkRow("ok", "Secure (HTTPS)")
      : checkRow("bad", "Not secure", "No HTTPS. Browsers show a 'Not secure' warning to visitors."),
    check.mobile_friendly
      ? checkRow("ok", "Works on phones")
      : checkRow("bad", "Not made for phones", "Most visitors come from a phone and will see a tiny desktop page."),
    check.load_seconds > 4
      ? checkRow("bad", `Slow: ${check.load_seconds} s to load`, "People usually leave after about 3 seconds.")
      : checkRow("ok", `Loads in ${check.load_seconds} s`),
  ];
  if (check.copyright_year) {
    rows.push(check.copyright_year <= outdatedYear
      ? checkRow("bad", `Looks outdated: © ${check.copyright_year}`, "The footer year hasn't been updated, so the site is probably not maintained.")
      : checkRow("ok", `Recently updated: © ${check.copyright_year}`));
  }
  if (check.builder) rows.push(checkRow("info", `Built with ${esc(check.builder)}`));
  box.innerHTML = rows.join("");
}

// One request checks the website quality and looks for social accounts, email and WhatsApp.
async function runOnlineCheck(btn) {
  const buttons = [document.getElementById("find-socials-btn"), document.getElementById("check-website-btn")];
  buttons.forEach((b) => (b.disabled = true));
  btn.querySelector("i").className = "spinner-border spinner-border-sm";
  btn.querySelector("span").textContent = "Checking…";
  try {
    const before = business;
    const result = await api(`/businesses/${businessId}/socials/find`, { method: "POST" });
    const b = result.business;
    render(b, { keepForm: dirty });
    if (result.error) {
      toast(`Couldn't read their website: ${result.error}`, "danger");
    } else {
      const found = [];
      if (result.added) found.push(`${result.added} social account${result.added === 1 ? "" : "s"}`);
      if (b.email && !before.email) found.push("an email");
      if (b.whatsapp && !before.whatsapp) found.push("a WhatsApp number");
      const issues = b.website_issues.length;
      const summary = issues ? `${issues} website problem${issues === 1 ? "" : "s"}` : "no website problems";
      toast(found.length ? `Found ${found.join(", ")}; ${summary}` : `Nothing new found; ${summary}`, found.length ? "success" : "info");
    }
  } catch (err) {
    toast(err.message, "danger");
    renderSocials(business);
    renderWebsiteCheck(business);
  }
  buttons.forEach((b) => {
    b.disabled = false;
    b.querySelector("i").className = "bi bi-search";
  });
}

document.getElementById("find-socials-btn").addEventListener("click", (e) => runOnlineCheck(e.currentTarget));
document.getElementById("check-website-btn").addEventListener("click", (e) => runOnlineCheck(e.currentTarget));

document.getElementById("social-add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("social-url");
  if (!input.value.trim()) return;
  try {
    render(await api(`/businesses/${businessId}/socials`, { method: "POST", body: { url: input.value } }), { keepForm: dirty });
    input.value = "";
    toast("Account added");
  } catch (err) {
    toast(err.message, "danger");
  }
});

function renderHours(b) {
  const hours = b.opening_hours ? Object.entries(b.opening_hours) : [];
  document.getElementById("b-hours").innerHTML = hours.length
    ? `<table class="table table-sm mb-0 small">${hours
        .map(([day, value]) => `<tr><td class="ps-3 bg-transparent">${esc(day)}</td>
          <td class="text-end pe-3 bg-transparent ${/closed|დაკეტ/i.test(value) ? "text-body-tertiary" : ""}">${esc(value)}</td></tr>`)
        .join("")}</table>`
    : '<div class="p-3 small text-body-secondary">Google doesn\'t list opening hours for this business.</div>';
}

function renderMap(b) {
  if (mapInitialized) return;
  if (b.latitude == null) {
    document.getElementById("detail-map").innerHTML = '<div class="p-3 small text-body-secondary">No location available</div>';
    return;
  }
  mapInitialized = true;
  const map = L.map("detail-map", { scrollWheelZoom: false }).setView([b.latitude, b.longitude], 16);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  L.marker([b.latitude, b.longitude]).addTo(map);
}

function renderCalls(b) {
  const box = document.getElementById("call-history");
  const emails = b.emails || [];
  const items = [...b.calls.map((c) => ({ ...c, kind: "call" })), ...emails.map((m) => ({ ...m, kind: "email" }))]
    .sort((x, y) => parseUtc(y.created_at) - parseUtc(x.created_at));
  document.getElementById("call-count").textContent = items.length || "";
  box.innerHTML = items.length
    ? items
        .map((c) => c.kind === "email" ? `<div class="timeline-item">
          <span class="timeline-dot"></span>
          <span class="pill pill-primary"><i class="bi bi-envelope-check"></i>Email sent</span>
          <div class="small text-body-secondary mt-1">${esc(fmtDateTime(c.created_at))} · to ${esc(c.to_address)}</div>
          <details class="mt-2 small"><summary class="fw-semibold">${esc(c.subject)}</summary>
            <div class="mt-1" style="white-space: pre-wrap">${esc(c.body)}</div></details>
        </div>` : `<div class="timeline-item">
          <span class="timeline-dot"></span>
          <div class="d-flex justify-content-between align-items-start gap-2">
            <div>
              ${statusPill(c.outcome)}
              <div class="small text-body-secondary mt-1">${esc(fmtDateTime(c.created_at))}</div>
            </div>
            <button type="button" class="btn btn-sm btn-ghost text-danger delete-call" data-call-id="${c.id}" title="Delete this call">
              <i class="bi bi-trash"></i>
            </button>
          </div>
          ${c.note ? `<div class="mt-2 small">${esc(c.note)}</div>` : ""}
        </div>`)
        .join("")
    : `<div class="empty-state py-4"><i class="bi bi-telephone"></i>
        <div class="small">Nothing yet. After you call, record it above. Emails you send appear here too.</div></div>`;
  box.querySelectorAll("[data-call-id]").forEach((btn) => btn.addEventListener("click", () => deleteCall(btn.dataset.callId)));
}

function renderLeadForm(b) {
  document.getElementById("lead-status").innerHTML = statusOptions(b.lead_status);
  document.getElementById("lead-followup").value = b.follow_up_date || "";
  document.getElementById("lead-phone").value = b.phone || "";
  document.getElementById("lead-email").value = b.email || "";
  document.getElementById("lead-whatsapp").value = b.whatsapp || "";
  document.getElementById("lead-website").value = b.website || "";
  document.getElementById("lead-notes").value = b.notes || "";
  updateStatusHelp();
  setDirty(false);
}

function render(b, { keepForm = false } = {}) {
  business = b;
  disposeTooltips(document.getElementById("detail"));
  renderHeader(b);
  renderContact(b);
  renderSocials(b);
  renderWebsiteCheck(b);
  renderHours(b);
  renderMap(b);
  renderCalls(b);
  if (!keepForm) renderLeadForm(b);
  else document.getElementById("lead-status").value = b.lead_status;
  initTooltips(document.getElementById("detail"));
}

async function load() {
  try {
    render(await api(`/businesses/${businessId}`));
  } catch (err) {
    toast(err.message, "danger");
  }
}

// ---------- Log a call ----------

const OUTCOME_LABELS = { client: "Became a client" };

document.getElementById("call-outcomes").innerHTML = window.APP.callOutcomes
  .map((value) => {
    const s = STATUS_BY_VALUE[value];
    return `<input type="radio" class="btn-check" name="outcome" id="outcome-${value}" value="${value}" autocomplete="off">
      <label class="outcome-option" for="outcome-${value}">
        <span class="pill pill-${s.color} px-2"><i class="bi ${s.icon}"></i></span>
        <span><span class="fw-semibold">${esc(OUTCOME_LABELS[value] || s.label)}</span><small>${esc(s.help)}</small></span>
      </label>`;
  })
  .join("");

document.getElementById("call-outcomes").addEventListener("change", () => {
  document.getElementById("call-submit").disabled = false;
});

document.getElementById("call-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const outcome = document.querySelector('input[name="outcome"]:checked')?.value;
  if (!outcome) return;
  const submit = document.getElementById("call-submit");
  submit.disabled = true;
  try {
    await api(`/businesses/${businessId}/calls`, {
      method: "POST",
      body: { outcome, note: document.getElementById("call-note").value },
    });
    document.getElementById("call-note").value = "";
    document.querySelector('input[name="outcome"]:checked').checked = false;
    toast(`Call saved. Status is now "${STATUS_BY_VALUE[outcome].label}"`);
    render(await api(`/businesses/${businessId}`), { keepForm: dirty });
    if (outcome === "call_back" && !document.getElementById("lead-followup").value) {
      toast("Tip: set a follow-up date in Your notes so you don't forget to call back", "info");
    }
  } catch (err) {
    toast(err.message, "danger");
    submit.disabled = false;
  }
});

async function deleteCall(callId) {
  const call = business.calls.find((c) => String(c.id) === String(callId));
  const ok = await confirmDialog({
    title: "Delete this call?",
    body: `The "${STATUS_BY_VALUE[call.outcome].label}" call from ${fmtDateTime(call.created_at)} will be removed. `
      + "If it set the current status, the status goes back to what it was before.",
    confirmText: "Delete call",
  });
  if (!ok) return;
  try {
    const updated = await api(`/businesses/${businessId}/calls/${callId}`, { method: "DELETE" });
    render(updated, { keepForm: dirty });
    toast("Call deleted");
  } catch (err) {
    toast(err.message, "danger");
  }
}

// ---------- Your notes ----------

function setDirty(value) {
  dirty = value;
  document.getElementById("lead-dirty").classList.toggle("d-none", !value);
}

function updateStatusHelp() {
  const s = STATUS_BY_VALUE[document.getElementById("lead-status").value];
  document.getElementById("lead-status-help").textContent = s ? s.help : "";
}

for (const field of LEAD_FIELDS) {
  document.getElementById(`lead-${field}`).addEventListener("input", () => setDirty(true));
}
document.getElementById("lead-status").addEventListener("change", updateStatusHelp);

document.querySelectorAll("[data-followup-days]").forEach((btn) =>
  btn.addEventListener("click", () => {
    const d = new Date();
    d.setDate(d.getDate() + Number(btn.dataset.followupDays));
    document.getElementById("lead-followup").value =
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    setDirty(true);
  }),
);
document.getElementById("clear-followup").addEventListener("click", () => {
  document.getElementById("lead-followup").value = "";
  setDirty(true);
});

document.getElementById("lead-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const website = document.getElementById("lead-website").value.trim();
  if (website && !safeUrl(website)) {
    toast("Website should start with http:// or https://", "danger");
    return;
  }
  const save = document.getElementById("lead-save");
  save.disabled = true;
  try {
    const updated = await api(`/businesses/${businessId}`, {
      method: "PATCH",
      body: {
        lead_status: document.getElementById("lead-status").value,
        follow_up_date: document.getElementById("lead-followup").value || null,
        phone: document.getElementById("lead-phone").value,
        email: document.getElementById("lead-email").value,
        whatsapp: document.getElementById("lead-whatsapp").value,
        website,
        notes: document.getElementById("lead-notes").value,
      },
    });
    render(updated);
    toast("Notes saved");
  } catch (err) {
    toast(err.message, "danger");
  }
  save.disabled = false;
});

window.addEventListener("beforeunload", (e) => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});

document.getElementById("delete-btn").addEventListener("click", async () => {
  const ok = await confirmDialog({
    title: `Delete ${business?.name || "this lead"}?`,
    body: "This removes the business, your notes and its whole call history. This can't be undone.",
    confirmText: "Delete lead",
  });
  if (!ok) return;
  try {
    await api(`/businesses/${businessId}`, { method: "DELETE" });
    dirty = false;
    location.href = "/businesses";
  } catch (err) {
    toast(err.message, "danger");
  }
});

// ---------- Message (WhatsApp / Viber / email) ----------

const messageModal = new bootstrap.Modal(document.getElementById("message-modal"));
let templates = null;
let mailSettings = { configured: false };
let messageChannel = "whatsapp";

const CHANNEL_HINTS = {
  whatsapp: "Opens WhatsApp with this text ready. You still press Send yourself.",
  viber: "Viber can't fill in text automatically, so the message is copied for you. Just paste it into the chat.",
};

function emailHint() {
  return mailSettings.configured
    ? `Sends right away from ${esc(mailSettings.address)}. You'll also find it in your Gmail Sent folder.`
    : 'Opens your email app with this text ready. <a href="/settings">Connect Gmail in Settings</a> to send straight from here.';
}

function sendsDirectly() {
  return messageChannel === "email" && mailSettings.configured;
}

function selectedTemplateText() {
  const t = templates.find((x) => String(x.id) === document.getElementById("message-template").value);
  return t ? fillTemplate(t.body, business) : "";
}

function updateMessageChannel(channel) {
  messageChannel = channel;
  const c = CHANNELS[channel];
  const send = document.getElementById("message-send");
  send.className = `btn ${channel === "email" ? "btn-primary" : c.cls}`;
  send.innerHTML = sendsDirectly()
    ? '<i class="bi bi-send-fill"></i> Send email'
    : `<i class="bi ${c.icon}"></i> Open ${c.label}`;
  document.getElementById("message-subject-wrap").classList.toggle("d-none", channel !== "email");
  document.getElementById("message-hint").innerHTML = channel === "email" ? emailHint() : esc(CHANNEL_HINTS[channel]);
}

async function openMessage(channel) {
  try {
    [templates, mailSettings] = await Promise.all([templates || api("/templates"), api("/mail/settings")]);
  } catch (err) {
    toast(err.message, "danger");
    return;
  }
  document.getElementById("message-to").value = business.email || "";
  const available = availableChannels(business);
  document.getElementById("message-title").textContent = `Send a message to ${business.name}`;
  document.getElementById("message-channels").innerHTML = Object.entries(CHANNELS)
    .map(([key, c]) => `<div class="col-4">
      <input type="radio" class="btn-check" name="channel" id="channel-${key}" value="${key}"
        ${key === channel ? "checked" : ""} ${available.includes(key) ? "" : "disabled"}>
      <label class="channel-option" for="channel-${key}"><i class="bi ${c.icon}"></i> ${c.label}</label></div>`)
    .join("");
  document.getElementById("message-template").innerHTML = templates.length
    ? templates.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("")
    : '<option value="">No templates yet. Write your message below</option>';
  document.getElementById("message-text").value = templates.length ? selectedTemplateText() : "";
  document.getElementById("message-subject").value = "Photos and videos for your social media";
  updateMessageChannel(channel);
  messageModal.show();
}

document.getElementById("message-channels").addEventListener("change", (e) => updateMessageChannel(e.target.value));

document.getElementById("message-template").addEventListener("change", () => {
  document.getElementById("message-text").value = selectedTemplateText();
});

document.getElementById("message-copy").addEventListener("click", async () => {
  await navigator.clipboard.writeText(document.getElementById("message-text").value);
  toast("Message copied");
});

async function sendEmailDirectly(btn, text) {
  const original = btn.innerHTML;
  btn.classList.add("disabled");
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Sending…';
  try {
    const to = document.getElementById("message-to").value.trim();
    const updated = await api(`/businesses/${businessId}/emails`, {
      method: "POST",
      body: { to, subject: document.getElementById("message-subject").value, body: text },
    });
    messageModal.hide();
    render(updated, { keepForm: dirty });
    toast(`Email sent to ${to}`);
  } catch (err) {
    toast(err.message, "danger");
  }
  btn.classList.remove("disabled");
  btn.innerHTML = original;
}

document.getElementById("message-send").addEventListener("click", async (e) => {
  const text = document.getElementById("message-text").value.trim();
  if (!text) {
    e.preventDefault();
    toast("Write a message first", "danger");
    return;
  }
  if (sendsDirectly()) {
    e.preventDefault();
    if (!document.getElementById("message-subject").value.trim()) {
      toast("Add a subject first", "danger");
      return;
    }
    sendEmailDirectly(e.currentTarget, text);
    return;
  }
  const target = { ...business, email: document.getElementById("message-to").value.trim() || business.email };
  e.currentTarget.href = channelHref(messageChannel, target, text, document.getElementById("message-subject").value);
  e.currentTarget.target = messageChannel === "whatsapp" ? "_blank" : "_self";
  if (messageChannel === "viber") {
    await navigator.clipboard.writeText(text).catch(() => {});
    toast("Message copied. Paste it into the Viber chat", "info");
  }
  messageModal.hide();
});

load();
