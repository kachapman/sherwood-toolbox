/* Tints elements marked `.company-tinted` with a muted version of the selected
   company's brand color, so the active company is visible at a glance. Acts only
   when a `#company_id` <select> with data-color options is present; otherwise it
   is a no-op. Loaded on every page from base.html. */
(function () {
  function hexToRgb(h) {
    h = (h || "").replace("#", "");
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    if (h.length !== 6) return null;
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  function rgbToHsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    var max = Math.max(r, g, b), min = Math.min(r, g, b), h, s, l = (max + min) / 2;
    if (max === min) { h = s = 0; }
    else {
      var d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {
        case r: h = (g - b) / d + (g < b ? 6 : 0); break;
        case g: h = (b - r) / d + 2; break;
        default: h = (r - g) / d + 4;
      }
      h /= 6;
    }
    return [h, s, l];
  }
  function hslToRgb(h, s, l) {
    var r, g, b;
    if (s === 0) { r = g = b = l; }
    else {
      function hue(p, q, t) {
        if (t < 0) t += 1;
        if (t > 1) t -= 1;
        if (t < 1 / 6) return p + (q - p) * 6 * t;
        if (t < 1 / 2) return q;
        if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
        return p;
      }
      var q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
      r = hue(p, q, h + 1 / 3); g = hue(p, q, h); b = hue(p, q, h - 1 / 3);
    }
    return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
  }
  // Pull the brand hue toward the muted, low-saturation, mid-dark range the rest
  // of the site uses, so the tint reads as on-brand without clashing.
  function muted(hex) {
    var rgb = hexToRgb(hex);
    if (!rgb) return null;
    var hsl = rgbToHsl(rgb[0], rgb[1], rgb[2]);
    var s = Math.min(hsl[1], 0.40);
    var l = Math.min(Math.max(hsl[2], 0.30), 0.40);
    var out = hslToRgb(hsl[0], s, l);
    return "rgb(" + out[0] + "," + out[1] + "," + out[2] + ")";
  }
  function apply() {
    var sel = document.getElementById("company_id");
    if (!sel) return;
    var opt = sel.options[sel.selectedIndex];
    var tint = opt ? muted(opt.getAttribute("data-color")) : null;
    document.querySelectorAll(".company-tinted").forEach(function (el) {
      if (tint) {
        el.style.backgroundColor = tint;
        el.style.borderColor = tint;
        el.style.color = "#fff";
      } else {
        el.style.backgroundColor = "";
        el.style.borderColor = "";
        el.style.color = "";
      }
    });
  }
  document.addEventListener("DOMContentLoaded", function () {
    var sel = document.getElementById("company_id");
    if (!sel) return;
    sel.addEventListener("change", apply);
    apply();
  });
})();
