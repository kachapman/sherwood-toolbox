/* Sidebar folder shortcuts. In the pywebview desktop build they open the folder
   via the native file manager; in a regular browser they show an alert with the
   folder path so the user can open it manually. */
(function () {
  var FOLDER_PATHS = {
    code_docs: "/opt/sherwood-toolbox/toolbox/tools/estimate_enhancer/attachments/",
    archive: "~/.local/share/sherwood-toolbox/uploads/"
  };

  function openFolder(key) {
    var path = FOLDER_PATHS[key];
    if (window.pywebview && window.pywebview.api) {
      var method = key === "code_docs" ? "open_code_docs" : "open_archive";
      if (typeof window.pywebview.api[method] === "function") {
        window.pywebview.api[method]();
        return;
      }
    }
    alert("This button opens a folder and only works in the desktop app.\n\nFolder location:\n" + path);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".js-open-folder").forEach(function (el) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        openFolder(el.getAttribute("data-folder"));
      });
    });
  });
})();
