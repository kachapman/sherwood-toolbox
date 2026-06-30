#!/usr/bin/env python3
"""Assemble toolbox-spec.html: the signed-off visual mockup bundled with the
full build instructions and a parked web-server appendix, in one self-contained
file that opens via file:// with no server and no external requests.

Sources:
  mockup/src/*.html        the visual mockup (hub + four tool pages)
  mockup/src/css/styles.css   base styles
  mockup/src/assets/logo.png  embedded as a data URI
  spec/partials/*.html     editable instruction text (per tool + docs)

Tool pages show the mockup UI followed by that tool's implementation panel.
Documentation pages show a partial on its own.

Run: python3 spec/build_spec.py   (writes ../toolbox-spec.html)
"""
import base64
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MSRC = ROOT / "mockup" / "src"
PARTIALS = HERE / "partials"

# id, nav label, group, title, subtitle, mockup source file, instruction partial
PAGES = [
    ("overview", "Overview", "Documentation", "Overview and architecture",
     "What this file is and how the toolbox fits together", None, "overview.html"),
    ("hub", "Hub", "Tools", "Hub", "The landing grid", "hub.html", None),
    ("estimate-enhancer", "Estimate Enhancer", "Tools", "Estimate Enhancer",
     "Mockup and build instructions", "estimate-enhancer.html", "estimate-enhancer.html"),
    ("iws", "Ice and Water Shield Calculator", "Tools", "Ice and Water Shield Calculator",
     "Mockup and build instructions", "iws.html", "iws.html"),
    ("photo-report", "Photo Report", "Tools", "Photo Report",
     "Mockup and build instructions", "photo-report.html", "photo-report.html"),
    ("documents", "Documents", "Tools", "Documents",
     "Mockup and build instructions", "document-generator.html", "documents.html"),
    ("run-local", "Run Locally", "Documentation", "Run locally",
     "Install, launch, offline behavior", None, "run-local.html"),
    ("maintainability", "Maintainability", "Documentation", "Maintainability",
     "How the structure stays editable", None, "maintainability.html"),
    ("web-parked", "Web Server (parked)", "Documentation", "Web server deployment",
     "Benched, preserved for later", None, "web-parked.html"),
]

HREF_TO_ID = {
    "index.html": "hub",
    "estimate-enhancer.html": "estimate-enhancer",
    "iws.html": "iws",
    "photo-report.html": "photo-report",
    "document-generator.html": "documents",
}

TOOL_ICON = {
    "hub": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    "estimate-enhancer": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M5 3h9l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M8 13h6M8 17h4"/></svg>',
    "iws": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12l9-7 9 7"/><path d="M5 10v9h14v-9"/><path d="M9 19v-5h6v5"/></svg>',
    "photo-report": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="6" width="18" height="14" rx="2"/><circle cx="12" cy="13" r="3.5"/><path d="M8 6l1.5-2h5L16 6"/></svg>',
    "documents": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M9 12h6M9 16h6"/></svg>',
}
DOC_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 3h9l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M9 8h6M9 12h6M9 16h4"/></svg>'

EXTRA_CSS = """
/* Spec build: page switching + instruction styling */
.page { display: none; }
.page.is-visible { display: block; }
.nav a { cursor: pointer; }
.nav-group { padding: 14px 16px 4px; font-size: 0.68rem; letter-spacing: 0.6px;
  text-transform: uppercase; color: #9fb095; }
.panel.spec h3 { margin: 18px 0 6px; font-size: 0.96rem; color: var(--green-800); }
.panel.spec ul, .panel.spec ol { margin: 6px 0; padding-left: 20px; }
.panel.spec li { margin: 3px 0; font-size: 0.9rem; }
.panel.spec p { font-size: 0.9rem; }
.panel.spec code { background: var(--sage-50); border: 1px solid var(--line);
  border-radius: 4px; padding: 1px 5px; font-size: 0.82rem; }
.panel.spec pre { background: var(--green-900); color: #e7eede; border-radius: 8px;
  padding: 14px 16px; overflow-x: auto; font-size: 0.8rem; line-height: 1.45; }
.panel.spec pre code { background: none; border: none; color: inherit; padding: 0; }
.panel.spec.parked { border-left: 4px solid var(--accent); }
.spec-flag { background: var(--accent); color: #fff; }
"""

SWITCH_JS = """    (function () {
      function show(id) {
        var pages = document.querySelectorAll('.page');
        for (var i = 0; i < pages.length; i++) {
          pages[i].classList.toggle('is-visible', pages[i].id === 'page-' + id);
        }
        var links = document.querySelectorAll('.nav a');
        for (var j = 0; j < links.length; j++) {
          links[j].classList.toggle('is-active', links[j].getAttribute('data-page') === id);
        }
        window.scrollTo(0, 0);
      }
      document.addEventListener('click', function (e) {
        var t = e.target.closest ? e.target.closest('[data-page]') : null;
        if (t) { e.preventDefault(); show(t.getAttribute('data-page')); }
      });
      show('overview');
    })();
"""


def extract_content(html):
    start = html.index('<div class="content">')
    i = start + len('<div class="content">')
    depth = 1
    for m in re.compile(r'<div\b|</div>').finditer(html, i):
        depth += 1 if m.group() != '</div>' else -1
        if depth == 0:
            return html[i:m.start()]
    raise ValueError("unbalanced content div")


def rewrite_links(fragment):
    def repl(m):
        pid = HREF_TO_ID.get(m.group(1))
        return 'href="javascript:void(0)" data-page="%s"' % pid if pid else m.group(0)
    return re.sub(r'href="([^"]+\.html)"', repl, fragment)


def build_sidebar():
    rows, current = [], None
    for pid, label, group, *_ in PAGES:
        if group != current:
            rows.append('        <li class="nav-group">%s</li>' % group)
            current = group
        icon = TOOL_ICON.get(pid, DOC_ICON)
        rows.append('        <li><a href="javascript:void(0)" data-page="%s">%s %s</a></li>'
                    % (pid, icon, label))
    return "\n".join(rows)


def main():
    css = (MSRC / "css" / "styles.css").read_text()
    logo_uri = "data:image/png;base64," + base64.b64encode(
        (MSRC / "assets" / "logo.png").read_bytes()).decode()
    mark_uri = "data:image/svg+xml;base64," + base64.b64encode(
        (ROOT / "toolbox" / "core" / "static" / "img" / "mark.svg").read_bytes()).decode()

    sections = []
    for pid, _label, _group, title, subtitle, mockup_file, partial in PAGES:
        body = ""
        if mockup_file:
            body += '<div class="content">%s</div>' % rewrite_links(
                extract_content((MSRC / mockup_file).read_text()))
        if partial:
            body += '\n        <div class="content">%s</div>' % (PARTIALS / partial).read_text()
        sections.append(
            '      <div class="page" id="page-%s">\n'
            '        <div class="topbar">\n'
            '          <h1>%s\n            <span class="subtitle">%s</span>\n          </h1>\n'
            '          <span class="badge spec-flag">Build spec</span>\n'
            '        </div>\n%s\n      </div>' % (pid, title, subtitle, body))

    html = (
        "<!DOCTYPE html>\n"
        "<!-- GENERATED FILE - do not edit by hand.\n"
        "     Source: spec/partials/*.html and mockup/src/*.\n"
        "     Rebuild: python3 spec/build_spec.py -->\n"
        "<html lang=\"en\">\n<head>\n"
        "  <meta charset=\"UTF-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        "  <title>Sherwood Toolbox build spec</title>\n"
        "  <link rel=\"icon\" type=\"image/svg+xml\" href=\"" + mark_uri + "\">\n"
        "  <style>\n" + css + EXTRA_CSS + "\n  </style>\n"
        "</head>\n<body>\n"
        "  <div class=\"shell\">\n"
        "    <aside class=\"sidebar\">\n"
        "      <div class=\"sidebar-brand\">\n"
        "        <img src=\"" + logo_uri + "\" alt=\"Sherwood logo\">\n"
        "        <span class=\"brand-text\">Sherwood Toolbox\n"
        "          <span class=\"brand-sub\">Build spec</span>\n"
        "        </span>\n"
        "      </div>\n"
        "      <ul class=\"nav\">\n" + build_sidebar() + "\n      </ul>\n"
        "      <div class=\"sidebar-foot\">Self-contained spec. Mockup plus instructions.</div>\n"
        "    </aside>\n"
        "    <div class=\"main\">\n" + "\n".join(sections) + "\n    </div>\n"
        "  </div>\n"
        "  <script>\n" + SWITCH_JS + "  </script>\n"
        "</body>\n</html>\n"
    )

    out = ROOT / "toolbox-spec.html"
    out.write_text(html)
    print("wrote %s (%d bytes)" % (out, len(html)))


if __name__ == "__main__":
    main()
