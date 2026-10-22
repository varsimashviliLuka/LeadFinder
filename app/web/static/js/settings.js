let mailSettings = null;

function renderMail(settings) {
  mailSettings = settings;
  const connected = settings.configured;
  document.getElementById("mail-status").innerHTML = connected
    ? '<span class="pill pill-success"><i class="bi bi-check-circle"></i>Connected</span>'
    : '<span class="pill pill-dark"><i class="bi bi-plug"></i>Not connected</span>';
  document.getElementById("mail-address").value = settings.address || "";
  document.getElementById("mail-name").value = settings.sender_name || "";
  document.getElementById("mail-password").value = "";
  document.getElementById("mail-password").placeholder = connected ? "Saved. Leave empty to keep it" : "abcd efgh ijkl mnop";
  document.querySelector("#mail-save span").textContent = connected ? "Save changes" : "Connect Gmail";
  document.getElementById("mail-test").classList.toggle("d-none", !connected);
  document.getElementById("mail-disconnect").classList.toggle("d-none", !connected);
}

async function withBusy(btn, label, action) {
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> ${label}`;
  try {
    await action();
  } catch (err) {
    toast(err.message, "danger");
  }
  btn.disabled = false;
  btn.innerHTML = original;
}

document.getElementById("mail-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const btn = document.getElementById("mail-save");
  withBusy(btn, "Signing in to Gmail…", async () => {
    const settings = await api("/mail/settings", {
      method: "PUT",
      body: {
        address: document.getElementById("mail-address").value,
        app_password: document.getElementById("mail-password").value,
        sender_name: document.getElementById("mail-name").value,
      },
    });
    renderMail(settings);
    toast(`Connected. Emails will be sent from ${settings.address}`);
  });
});

document.getElementById("mail-test").addEventListener("click", (e) => {
  withBusy(e.currentTarget, "Sending…", async () => {
    const result = await api("/mail/test", { method: "POST" });
    toast(`Test email sent to ${result.sent_to}. Check your inbox`);
  });
});

document.getElementById("mail-disconnect").addEventListener("click", async () => {
  const ok = await confirmDialog({
    title: "Disconnect Gmail?",
    body: `The saved App Password for ${mailSettings.address} will be deleted from this computer. `
      + "The Email button will open your email app instead.",
    confirmText: "Disconnect",
  });
  if (!ok) return;
  try {
    await api("/mail/settings", { method: "DELETE" });
    renderMail(await api("/mail/settings"));
    toast("Gmail disconnected");
  } catch (err) {
    toast(err.message, "danger");
  }
});

api("/mail/settings").then(renderMail).catch((err) => toast(err.message, "danger"));
