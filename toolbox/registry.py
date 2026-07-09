"""The tool registry: the single source of truth for what the toolbox contains.

The hub tiles, the sidebar nav, and blueprint registration all read this list.
To add a tool: create toolbox/tools/<id>/ exposing `bp` (a Blueprint named
<id> with an `index` route), then add one ToolSpec entry here with ready=True.
Until ready, a placeholder page is served so the nav and links stay valid.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    id: str            # blueprint name; endpoint is "<id>.index"
    label: str         # sidebar + tile title
    icon: str          # inline SVG markup
    url_prefix: str    # mount point, e.g. "/iws"
    description: str   # one line for the hub tile
    offline_capable: bool = True
    ready: bool = False  # True when a real blueprint module exists


# Inline SVG icons (no emoji, per project rules).
_IC_EE = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
          '<path d="M14 3v4a1 1 0 0 0 1 1h4"/>'
          '<path d="M5 3h9l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
          '<path d="M8 13h6M8 17h4"/></svg>')
_IC_IWS = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
           '<path d="M3 12l9-7 9 7"/><path d="M5 10v9h14v-9"/><path d="M9 19v-5h6v5"/></svg>')
_IC_PHOTO = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
             '<rect x="3" y="6" width="18" height="14" rx="2"/><circle cx="12" cy="13" r="3.5"/>'
             '<path d="M8 6l1.5-2h5L16 6"/></svg>')
_IC_DOCS = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
            '<path d="M14 3v4a1 1 0 0 0 1 1h4"/>'
            '<path d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
            '<path d="M9 12h6M9 16h6"/></svg>')
_IC_REC = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
           '<rect x="2" y="4" width="8.5" height="16" rx="1.5"/>'
           '<rect x="13.5" y="4" width="8.5" height="16" rx="1.5"/>'
           '<path d="M4.5 9h3.5M4.5 12.5h3.5M16 9h3.5M16 12.5h3.5"/></svg>')

TOOLS = [
    ToolSpec("estimate_enhancer", "Estimate Enhancer", _IC_EE, "/estimate-enhancer",
             "Enhance and clean up construction estimate PDFs.", True, True),
    ToolSpec("iws", "Ice and Water Shield Calculator", _IC_IWS, "/iws",
             "Calculate ice and water shield coverage.", True, True),
    ToolSpec("photo_report", "Photo Report", _IC_PHOTO, "/photo-report",
             "Build a branded photo report PDF from a job's images.", True, True),
    ToolSpec("documents", "Documents", _IC_DOCS, "/documents",
             "Generate invoices and certificates of completion.", True, True),
    ToolSpec("reconciler", "Estimate Reconciler", _IC_REC, "/reconciler",
             "Mark up a carrier estimate against a contractor estimate: missing "
             "scope and quantity gaps highlighted on the PDF, with a logged "
             "breakdown.", True, True),
]
