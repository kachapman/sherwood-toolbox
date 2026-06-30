/* Saves the CRM login from the credential form (shown when this machine has no
   saved credentials). Verifies + persists via POST, then hides the form and
   enables the Fetch button. No-op when the form is absent. Loaded from
   base.html on every page. */
(function () {
  var btn = document.getElementById("crmSaveBtn");
  if (!btn) return;
  btn.addEventListener("click", async function () {
    var msg = document.getElementById("crmCredMsg");
    var user = (document.getElementById("crmUser") || {}).value || "";
    var pass = (document.getElementById("crmPass") || {}).value || "";
    if (!user || !pass) { msg.textContent = "Enter both fields."; return; }
    msg.textContent = "Verifying...";
    btn.disabled = true;
    var fd = new FormData();
    fd.append("username", user);
    fd.append("password", pass);
    try {
      var r = await fetch(btn.getAttribute("data-url"), { method: "POST", body: fd });
      var data = await r.json();
      if (!data.ok) { msg.textContent = data.error || "Could not save."; btn.disabled = false; return; }
      var box = document.getElementById("crmCreds");
      if (box) box.style.display = "none";
      var fetchBtn = document.getElementById("crmFetchBtn");
      if (fetchBtn) fetchBtn.disabled = false;
    } catch (e) {
      msg.textContent = "Error: " + e.message;
      btn.disabled = false;
    }
  });
})();
