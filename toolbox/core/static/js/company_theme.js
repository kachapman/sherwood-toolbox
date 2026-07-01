/* Tints the active workspace with the selected company's brand color so users
   can see at a glance which company is selected. Applies a faint tint to
   .company-theme-surface panels and the brand color to .company-tinted buttons.
   Loaded on every page from base.html; no-op if #company_id is absent. */
(function () {
  function hexToRgb(h) {
    h = (h || "").replace("#", "");
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    if (h.length !== 6) return null;
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }

  function rgb(hex) {
    var c = hexToRgb(hex);
    return c ? "rgb(" + c[0] + "," + c[1] + "," + c[2] + ")" : null;
  }

  function rgba(hex, alpha) {
    var c = hexToRgb(hex);
    return c ? "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + alpha + ")" : null;
  }

  // Returns 'dark' or 'light' depending on which text color is readable on the
  // given solid background.
  function textVariant(hex) {
    var c = hexToRgb(hex);
    if (!c) return "dark";
    // Relative luminance (sRGB).
    var lum = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    return lum > 140 ? "dark" : "light";
  }

  function apply() {
    var sel = document.getElementById("company_id");
    if (!sel) return;
    var opt = sel.options[sel.selectedIndex];
    var color = opt ? opt.getAttribute("data-color") : null;
    if (!color) return;

    var solid = rgb(color);
    var faintBg = rgba(color, 0.12);
    var faintBorder = rgba(color, 0.35);
    var text = textVariant(color);

    document.querySelectorAll(".company-theme-surface").forEach(function (el) {
      el.style.backgroundColor = faintBg;
      el.style.borderColor = faintBorder;
      el.style.borderLeft = "4px solid " + solid;
    });

    document.querySelectorAll(".company-tinted").forEach(function (el) {
      el.style.backgroundColor = solid;
      el.style.borderColor = solid;
      el.style.color = text === "dark" ? "#1a1a1a" : "#fff";
    });
  }

  function clear() {
    document.querySelectorAll(".company-theme-surface, .company-tinted").forEach(function (el) {
      el.style.backgroundColor = "";
      el.style.borderColor = "";
      el.style.color = "";
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var sel = document.getElementById("company_id");
    if (!sel) return;
    sel.addEventListener("change", apply);
    apply();
  });
})();
