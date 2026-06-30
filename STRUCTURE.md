# Sherwood Toolbox structure

Read this first. One row per meaningful path: what it holds and "edit here to
change X." The app is one Flask app (a modular monolith): a hub plus one
blueprint per tool, run locally on `127.0.0.1`.

## Run it

- Install once: `run/install-standalone.sh` (venv + `.desktop` + zsh alias).
- Launch: the GNOME "Sherwood Toolbox" entry, or `sherwood-toolbox`, or
  `.venv/bin/python run/standalone.py`.
- Dev loop: edit a file, restart the launcher (no build step for templates/CSS).

## Composition core

| Path | Holds | Edit here to |
|---|---|---|
| `toolbox/registry.py` | The list of tools (id, label, icon, url_prefix, description, ready). Single source of truth. | Add, remove, rename, or reorder a tool. Set `ready=True` when its blueprint exists. |
| `toolbox/app.py` | `create_app()`: builds Flask, registers the hub + each tool blueprint (or a placeholder when `ready=False`), injects `tools` and `caps` into templates. | Change app-wide wiring or context. |
| `toolbox/config.py` | Env-driven paths and flags (upload dir, fork path, `OFFLINE`, max upload). | Change where files are written or default limits. |
| `toolbox/core/hub.py` | The hub blueprint; renders the tile grid from the registry. | Change the landing page behavior. |
| `toolbox/core/capabilities.py` | Detects network / CRM creds / fork presence into `caps`. | Change graceful-degradation logic. |
| `toolbox/core/crm.py` | Graceful wrapper around `restoration_common.fetch_job_info_from_url`, plus `parse_address` (splits a CRM address into street + City/State/ZIP). | Change CRM error handling or address parsing shared by Photo Report and Documents. |
| `toolbox/core/hub.py` | The hub blueprint (`/`) and the shared `POST /crm/credentials` route (verify + save a CRM login). | Change the hub or credential-save logic. |
| `toolbox/core/templates/_crm_credentials.html` + `static/js/crm_credentials.js` | The CRM credential entry form, shown in both tools' CRM panels when `caps.crm_configured` is false. | Change how a machine enters its CRM login. |

## Shared look (defined once)

| Path | Holds | Edit here to |
|---|---|---|
| `toolbox/core/templates/base.html` | Sidebar + topbar chrome; favicon links; every page extends this. | Change the shell, nav, or offline notice. |
| `toolbox/core/templates/hub.html` | Tile grid markup. | Change the hub tiles. |
| `toolbox/core/templates/placeholder.html` | "Coming soon" page for not-yet-ready tools. | n/a |
| `toolbox/core/static/css/toolbox.css` | The shared design system: tokens, chrome, buttons, panels, fields, cards. | Change the global look. Tool-specific CSS extends these tokens. |
| `toolbox/core/static/img/mark.svg` | Adaptive favicon mark (light/dark via `prefers-color-scheme`). | Change the favicon glyph. |
| `toolbox/core/static/img/logo.png` | Header logo (transparent). | Replace the brand logo. |

## Tools (one package each, mounted at its url_prefix)

| Path | Holds | Edit here to |
|---|---|---|
| `toolbox/tools/iws/static/js/calculator.js` | The IWS coverage math (client-side). | Change the calculation. |
| `toolbox/tools/iws/templates/iws.html` + `static/css/iws.css` | IWS form and result/diagram styling (shared classes + tokens). | Change the IWS UI. |
| `toolbox/tools/estimate_enhancer/pdf_ops.py` | Pure PDF analysis/enhancement logic (PyMuPDF, spellcheck). Section banners inside. | Change how estimates are analyzed or enhanced. |
| `toolbox/tools/estimate_enhancer/routes.py` | Routes, config wiring, the fork subprocess. | Change endpoints or file handling. |
| `toolbox/tools/estimate_enhancer/fork/add_image_links.py` | The bundled image-link helper run as a subprocess. | Change image-linking behavior. |
| `toolbox/tools/estimate_enhancer/attachments/` | Packaged IRC reference PDFs offered for attachment. | Add/remove reference documents. |
| `toolbox/tools/estimate_enhancer/templates/estimate_enhancer.html` + `static/css/ee.css` | The 4-step flow UI. | Change the EstimateEnhancer UI. |
| `toolbox/tools/photo_report/routes.py` + `templates/photo_report.html` | Photo report form -> `restoration_common.PhotoReportPDF`. | Change inputs or wiring. The PDF layout is in restoration_common. |
| `toolbox/tools/documents/routes.py` + `templates/documents.html` | Invoice + certificate forms -> `restoration_common` generators; line items, signature. | Change inputs or wiring. The PDF layouts are in restoration_common. |

## Bundled library (in this repo)

| Path | Holds | Edit here to |
|---|---|---|
| `vendor/restoration-common/restoration_common/` | Vendored headless PDF generators (`PhotoReportPDF`, `InvoicePDFGenerator`, `COCPDFGenerator`), CRM fetch/login, credential save, company/signature/logo helpers. No PyQt5. Installed into the venv with `--no-deps`. | Change PDF layouts or CRM logic. The canonical source is `~/.local/share/RestorationToolkit`; keep this copy in sync if that changes. |

## Run modes and artifacts

| Path | Holds | Edit here to |
|---|---|---|
| `run/standalone.py` | The local launcher: waitress on a fixed `127.0.0.1:8765`, opens the browser. Detects an already-running instance; never falls back to a random port (keeps per-origin browser state stable). | Change how the app starts locally. |
| `run/install-standalone.sh` | Portable installer: venv, bundled `restoration_common`, `.desktop`, zsh/bash alias, bundled signatures, prereq check. | Change install behavior. |
| `run/make-portable-bundle.sh` | Builds `sherwood-toolbox.tar.gz` (tracked files + signatures, no credentials). | Change what ships in the bundle. |
| `SHARING.md` | How to build, transfer, and install on another machine. | Update the sharing guide. |
| `run/sherwood-toolbox.desktop` | GNOME launcher template (`__REPO__`/`__VENV_PY__` placeholders). | Change the menu entry. |
| `spec/build_spec.py` + `spec/partials/` | Generator + sources for `toolbox-spec.html`. | Edit a partial, then rerun `python3 spec/build_spec.py`. |
| `toolbox-spec.html` | GENERATED full build spec (mockup + instructions + parked web appendix). | Do not edit by hand; rebuild from `spec/`. |
| `mockup/` | The signed-off layout mockup (design reference). | n/a |

## Conventions

- Predictable names: HTTP in `routes.py`, pure logic in `*_ops.py`, the design
  system in `toolbox.css`, tool-specific CSS in `tools/<id>/static/css/`.
- Keep files around 300 lines; split by concern; use `# === SECTION: name ===`
  banners in longer files (see `pdf_ops.py`).
- Generated files carry a header naming their source and rebuild command and are
  never hand-edited.
- The web-server deployment is parked; its instructions live in the Web Server
  appendix of `toolbox-spec.html`.
