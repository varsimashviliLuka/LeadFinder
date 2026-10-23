const list = document.getElementById("trip-list");

function tripCard(t) {
  const progress = t.stop_count ? Math.round((t.done_count / t.stop_count) * 100) : 0;
  const route = t.optimized
    ? `${fmtDuration(t.total_duration_s)} ${t.mode === "car" ? "driving" : "walking"} · ${formatDistance(Math.round(t.total_distance_m))}`
    : '<span class="text-warning-emphasis">Route not planned yet</span>';
  const when = t.start_at
    ? new Date(t.start_at).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : "Start time: when you go";
  return `<div class="col-md-6 col-xl-4">
    <a class="card h-100 trip-card text-decoration-none" href="/trips/${t.id}">
      <div class="card-body d-flex flex-column gap-2">
        <div class="d-flex justify-content-between align-items-start gap-2">
          <div class="fw-semibold text-body">${esc(t.name)}</div>
          <span class="pill pill-secondary"><i class="bi ${TRAVEL_MODES[t.mode].icon}"></i>${TRAVEL_MODES[t.mode].label}</span>
        </div>
        <div class="small text-body-secondary"><i class="bi bi-calendar-event"></i> ${esc(when)}</div>
        <div class="small text-body-secondary"><i class="bi bi-signpost-split"></i> ${t.stop_count} stop${t.stop_count === 1 ? "" : "s"} · ${route}</div>
        <div class="mt-auto pt-2">
          <div class="progress" style="height:6px"><div class="progress-bar bg-success" style="width:${progress}%"></div></div>
          <div class="small text-body-secondary mt-1">${t.done_count} of ${t.stop_count} done</div>
        </div>
      </div>
    </a>
  </div>`;
}

async function load() {
  try {
    const trips = await api("/trips");
    list.innerHTML = trips.length
      ? trips.map(tripCard).join("")
      : `<div class="col-12"><div class="card"><div class="empty-state"><i class="bi bi-signpost-split"></i>
          <div class="fw-semibold text-body">No trips yet</div>
          <div class="small">Click <em>New trip</em> and pick businesses on the map, or select them on the Leads page.</div></div></div></div>`;
  } catch (err) {
    toast(err.message, "danger");
  }
}

document.getElementById("new-trip").addEventListener("click", async () => {
  try {
    const { trip } = await api("/trips", { method: "POST", body: {} });
    window.location.href = `/trips/${trip.id}`;
  } catch (err) {
    toast(err.message, "danger");
  }
});

load();
