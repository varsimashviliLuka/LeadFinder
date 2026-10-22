const list = document.getElementById("template-list");
const PREVIEW_LEAD = { name: "Salon Nino", category: "სილამაზის სალონი" };

function templateCard(t) {
  const id = t.id ?? "new";
  return `<div class="col-lg-6">
    <form class="card h-100 template-card" data-template-id="${id}">
      <div class="card-body d-flex flex-column gap-2">
        <input class="form-control fw-semibold" name="name" value="${esc(t.name)}" placeholder="Template name, e.g. First message" maxlength="120">
        <textarea class="form-control flex-grow-1" name="body" rows="6"
          placeholder="Hi! I came across {name} on Google Maps…">${esc(t.body)}</textarea>
        <div class="small text-body-secondary"><span class="fw-semibold">Preview:</span>
          <span data-preview>${esc(fillTemplate(t.body, PREVIEW_LEAD))}</span></div>
      </div>
      <div class="card-footer bg-transparent d-flex justify-content-between">
        <button type="button" class="btn btn-sm btn-ghost text-danger" data-delete><i class="bi bi-trash"></i> Delete</button>
        <button type="submit" class="btn btn-sm btn-primary"><i class="bi bi-save"></i> Save</button>
      </div>
    </form>
  </div>`;
}

function bindCard(form) {
  const id = form.dataset.templateId;
  form.querySelector("[name=body]").addEventListener("input", (e) => {
    form.querySelector("[data-preview]").textContent = fillTemplate(e.target.value, PREVIEW_LEAD);
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { name: form.elements.name.value, body: form.elements.body.value };
    try {
      if (id === "new") await api("/templates", { method: "POST", body });
      else await api(`/templates/${id}`, { method: "PATCH", body });
      toast("Template saved");
      load();
    } catch (err) {
      toast(err.message, "danger");
    }
  });
  form.querySelector("[data-delete]").addEventListener("click", async () => {
    if (id === "new") {
      form.parentElement.remove();
      return;
    }
    const ok = await confirmDialog({
      title: "Delete this template?",
      body: `"${form.elements.name.value}" will be removed. Messages you already sent aren't affected.`,
    });
    if (!ok) return;
    try {
      await api(`/templates/${id}`, { method: "DELETE" });
      toast("Template deleted");
      load();
    } catch (err) {
      toast(err.message, "danger");
    }
  });
}

async function load() {
  try {
    const templates = await api("/templates");
    list.innerHTML = templates.length
      ? templates.map(templateCard).join("")
      : `<div class="col-12"><div class="card"><div class="empty-state"><i class="bi bi-chat-text"></i>
          <div class="fw-semibold text-body">No templates yet</div>
          <div class="small">Click <em>New template</em> to write your first message.</div></div></div></div>`;
    list.querySelectorAll("form").forEach(bindCard);
  } catch (err) {
    toast(err.message, "danger");
  }
}

document.getElementById("new-template").addEventListener("click", () => {
  if (list.querySelector('[data-template-id="new"]')) return;
  list.querySelector(".empty-state")?.closest(".col-12").remove();
  list.insertAdjacentHTML("afterbegin", templateCard({ name: "", body: "" }));
  const form = list.querySelector('[data-template-id="new"]');
  bindCard(form);
  form.elements.name.focus();
});

load();
