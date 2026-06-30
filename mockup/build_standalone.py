#!/usr/bin/env python3
"""Assemble the multi-page mockup sources in src/ into one self-contained
index.html. Inlines the CSS, embeds the logo as a data URI, and turns the
five pages into in-document sections switched by JavaScript.

Why single-file: the default browser here is Vivaldi as a Flatpak, opened
with --file-forwarding. That sandbox grants access only to the one file you
open, so external css/js/img and links to sibling .html files fail. One
self-contained file opens correctly by double-click with no server and no
sandbox change.

Run: python3 build_standalone.py  (writes ./index.html)
"""
import base64
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"

# (page id, sidebar label, title, subtitle, source file)
PAGES = [
    ("hub", "Hub", "Hub", "Pick a tool to open", "hub.html"),
    ("estimate-enhancer", "Estimate Enhancer", "Estimate Enhancer",
     "Clean up and link a construction estimate PDF", "estimate-enhancer.html"),
    ("iws", "Ice and Water Shield Calculator", "Ice and Water Shield Calculator",
     "Coverage from roof measurements", "iws.html"),
    ("photo-report", "Photo Report", "Photo Report",
     "Web port of the desktop generator, planned", "photo-report.html"),
    ("documents", "Documents", "Documents",
     "Invoice and certificate of completion, planned web port",
     "document-generator.html"),
]

# Map source href targets to page ids for in-document switching.
HREF_TO_ID = {
    "index.html": "hub",
    "estimate-enhancer.html": "estimate-enhancer",
    "iws.html": "iws",
    "photo-report.html": "photo-report",
    "document-generator.html": "documents",
}

# Sidebar icons (inline SVG), keyed by page id.
ICONS = {
    "hub": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    "estimate-enhancer": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M5 3h9l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M8 13h6M8 17h4"/></svg>',
    "iws": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12l9-7 9 7"/><path d="M5 10v9h14v-9"/><path d="M9 19v-5h6v5"/></svg>',
    "photo-report": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="6" width="18" height="14" rx="2"/><circle cx="12" cy="13" r="3.5"/><path d="M8 6l1.5-2h5L16 6"/></svg>',
    "documents": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M9 12h6M9 16h6"/></svg>',
}


def extract_content(html):
    """Return the inner HTML of the first <div class="content"> ... </div>,
    matching div nesting so we stop at the correct closing tag."""
    start = html.index('<div class="content">')
    open_len = len('<div class="content">')
    i = start + open_len
    depth = 1
    token = re.compile(r'<div\b|</div>')
    for m in token.finditer(html, i):
        depth += 1 if m.group() != '</div>' else -1
        if depth == 0:
            return html[i:m.start()]
    raise ValueError("unbalanced content div")


def rewrite_links(fragment):
    """Turn href="<tool>.html" into in-document page switches."""
    def repl(m):
        target = m.group(1)
        pid = HREF_TO_ID.get(target)
        if pid is None:
            return m.group(0)
        return 'href="javascript:void(0)" data-page="%s"' % pid
    return re.sub(r'href="([^"]+\.html)"', repl, fragment)


def build_sidebar():
    items = []
    for pid, label, _t, _s, _f in PAGES:
        items.append(
            '        <li><a href="javascript:void(0)" data-page="%s">%s %s</a></li>'
            % (pid, ICONS[pid], label)
        )
    return "\n".join(items)


def main():
    css = (SRC / "css" / "styles.css").read_text()
    logo_b64 = base64.b64encode((SRC / "assets" / "logo.png").read_bytes()).decode()
    logo_uri = "data:image/png;base64," + logo_b64

    sections = []
    for pid, _label, title, subtitle, fname in PAGES:
        content = rewrite_links(extract_content((SRC / fname).read_text()))
        sections.append(
            '      <div class="page" id="page-%s">\n'
            '        <div class="topbar">\n'
            '          <h1>%s\n            <span class="subtitle">%s</span>\n          </h1>\n'
            '          <span class="badge">Static mockup</span>\n'
            '        </div>\n'
            '        <div class="content">%s</div>\n'
            '      </div>' % (pid, title, subtitle, content)
        )

    extra_css = (
        "\n/* Single-file build: in-document page switching */\n"
        ".page { display: none; }\n"
        ".page.is-visible { display: block; }\n"
        ".nav a { cursor: pointer; }\n"
    )

    script = (
        "    (function () {\n"
        "      function show(id) {\n"
        "        var pages = document.querySelectorAll('.page');\n"
        "        for (var i = 0; i < pages.length; i++) {\n"
        "          pages[i].classList.toggle('is-visible', pages[i].id === 'page-' + id);\n"
        "        }\n"
        "        var links = document.querySelectorAll('.nav a');\n"
        "        for (var j = 0; j < links.length; j++) {\n"
        "          links[j].classList.toggle('is-active', links[j].getAttribute('data-page') === id);\n"
        "        }\n"
        "        window.scrollTo(0, 0);\n"
        "      }\n"
        "      document.addEventListener('click', function (e) {\n"
        "        var t = e.target.closest ? e.target.closest('[data-page]') : null;\n"
        "        if (t) { e.preventDefault(); show(t.getAttribute('data-page')); }\n"
        "      });\n"
        "      show('hub');\n"
        "    })();\n"
    )

    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "  <meta charset=\"UTF-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        "  <title>Sherwood Toolbox</title>\n"
        "  <link rel=\"icon\" type=\"image/png\" href=\"" + logo_uri + "\">\n"
        "  <style>\n" + css + extra_css + "\n  </style>\n"
        "</head>\n<body>\n"
        "  <div class=\"shell\">\n"
        "    <aside class=\"sidebar\">\n"
        "      <div class=\"sidebar-brand\">\n"
        "        <img src=\"" + logo_uri + "\" alt=\"Sherwood logo\">\n"
        "        <span class=\"brand-text\">Sherwood Toolbox\n"
        "          <span class=\"brand-sub\">Estimating tools</span>\n"
        "        </span>\n"
        "      </div>\n"
        "      <ul class=\"nav\">\n" + build_sidebar() + "\n      </ul>\n"
        "      <div class=\"sidebar-foot\">Layout mockup, no backend wired.</div>\n"
        "    </aside>\n"
        "    <div class=\"main\">\n" + "\n".join(sections) + "\n    </div>\n"
        "  </div>\n"
        "  <script>\n" + script + "  </script>\n"
        "</body>\n</html>\n"
    )

    out = HERE / "index.html"
    out.write_text(html)
    print("wrote %s (%d bytes)" % (out, len(html)))


if __name__ == "__main__":
    main()
