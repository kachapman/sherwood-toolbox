/* Sidebar folder shortcuts.
   Opens a simple in-app modal for listing/deleting/uploading (Code Docs) or clearing older (Archive).
   Works the same on desktop (pywebview) and web/browser.
   The pywebview bridge still supports the native open as a secondary action if needed.
*/
(function () {
  var FOLDER_LABELS = {
    code_docs: "Code Docs",
    archive: "Archive"
  };

  function openFileModal(key) {
    var modal = document.getElementById("fileModal");
    var body = document.getElementById("fileModalBody");
    var titleEl = document.getElementById("fileModalTitle");
    var uploadWrap = document.getElementById("fileModalUpload");
    var clearWrap = document.getElementById("fileModalClearOlder");

    if (!modal || !body || !titleEl) return;

    titleEl.textContent = FOLDER_LABELS[key] || key;
    body.innerHTML = "Loading...";
    uploadWrap.style.display = (key === "code_docs") ? "" : "none";
    clearWrap.style.display = (key === "archive") ? "" : "none";

    modal.style.display = "flex";
    modal.classList.remove("hidden");

    window.closeFileModal = function () {
      modal.style.display = "none";
      modal.classList.add("hidden");
    };

    // Fetch list
    fetch("/files?dir=" + encodeURIComponent(key))
      .then(r => r.json())
      .then(data => {
        var items = data.items || [];
        if (!items.length) {
          body.innerHTML = '<p class="muted-note">No files.</p>';
        } else {
          var html = '<table style="width:100%;font-size:0.9rem;border-collapse:collapse;">';
          html += '<thead><tr><th style="text-align:left;padding:6px 4px;color:var(--green-800);">Name</th><th style="text-align:right;padding:6px 4px;color:var(--green-800);">Size</th><th></th></tr></thead><tbody>';
          items.forEach(function (it) {
            var size = (it.size / 1024).toFixed(1) + " KB";
            html += '<tr>' +
              '<td style="padding:6px 4px;border-bottom:1px solid var(--line);">' + it.name + '</td>' +
              '<td style="padding:6px 4px;border-bottom:1px solid var(--line);text-align:right;">' + size + '</td>' +
              '<td style="padding:6px 4px;border-bottom:1px solid var(--line);text-align:right;">' +
              '<button class="btn btn-secondary" style="padding:4px 10px;font-size:0.8rem;" data-name="' + it.name + '">Delete</button>' +
              '</td></tr>';
          });
          html += '</tbody></table>';
          body.innerHTML = html;

          body.querySelectorAll("button[data-name]").forEach(function (btn) {
            btn.addEventListener("click", function () {
              if (!confirm("Delete this file?")) return;
              var fd = new FormData();
              fd.append("dir", key);
              fd.append("name", btn.getAttribute("data-name"));
              fetch("/files/delete", { method: "POST", body: fd })
                .then(r => r.json())
                .then(res => {
                  if (res && res.ok) {
                    openFileModal(key);
                  } else {
                    alert((res && res.error) || "Delete failed.");
                  }
                })
                .catch(() => alert("Delete failed."));
            });
          });
        }
      })
      .catch(() => {
        body.innerHTML = '<p class="muted-note">Could not load files.</p>';
      });

    // Upload (Code Docs only)
    var uploadBtn = document.getElementById("fileUploadBtn");
    var fileInput = document.getElementById("fileUploadInput");
    if (uploadBtn && fileInput && key === "code_docs") {
      uploadBtn.onclick = function () {
        if (!fileInput.files[0]) { alert("Choose a file."); return; }
        var fd = new FormData();
        fd.append("file", fileInput.files[0]);
        uploadBtn.disabled = true;
        fetch("/files/upload?dir=code_docs", { method: "POST", body: fd })
          .then(r => r.json())
          .then(res => {
            uploadBtn.disabled = false;
            if (res.ok) {
              fileInput.value = "";
              openFileModal(key);
            } else {
              alert(res.error || "Upload failed.");
            }
          })
          .catch(() => {
            uploadBtn.disabled = false;
            alert("Upload failed.");
          });
      };
    }

    // Clear older (Archive)
    var clearBtn = document.getElementById("clearOlderBtn");
    var hoursInput = document.getElementById("clearOlderHours");
    if (clearBtn && hoursInput && key === "archive") {
      clearBtn.onclick = function () {
        var hours = parseInt(hoursInput.value || "24", 10);
        if (!confirm("Delete all files older than " + hours + " hours?")) return;
        var fd = new FormData();
        fd.append("dir", key);
        fd.append("older_than_hours", hours);
        clearBtn.disabled = true;
        fetch("/files/clear-older", { method: "POST", body: fd })
          .then(r => r.json())
          .then(() => {
            clearBtn.disabled = false;
            openFileModal(key);
          })
          .catch(() => {
            clearBtn.disabled = false;
            alert("Clear failed.");
          });
      };
    }
  }

  // Expose for desktop bridge if needed
  window.__openFileManager = openFileModal;

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".js-open-folder").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        var key = el.getAttribute("data-folder");
        // Try to open the in-app modal first (works on web and desktop)
        if (window.__openFileManager) {
          window.__openFileManager(key);
          return;
        }
        // Fallback to old behavior (paths are best-effort strings for the alert)
        var path = (key === "code_docs")
          ? "~/.local/share/sherwood-toolbox/attachments/"
          : "~/.local/share/sherwood-toolbox/uploads/";
        if (window.pywebview && window.pywebview.api) {
          var method = key === "code_docs" ? "open_code_docs" : "open_archive";
          if (typeof window.pywebview.api[method] === "function") {
            window.pywebview.api[method]();
            return;
          }
        }
        alert("This button opens a folder.\n\nFolder location:\n" + path);
      });
    });
  });
})();
