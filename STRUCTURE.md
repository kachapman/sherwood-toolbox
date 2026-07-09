# Sherwood Toolbox structure

Read this first. One row per meaningful path: what it holds and "edit here to
change X." The app is one Flask app (a modular monolith): a hub plus one
blueprint per tool, run locally on `127.0.0.1`.

## Run it

- **Development / browser mode:** `run/standalone.py` serves on a fixed port and
  opens the system browser.
- **Production desktop mode (`.deb` or AppImage):** `run/desktop.py` serves the
  same Flask app inside a native pywebview window (GTK/WebKitGTK). The `.deb`
  wrapper and the AppImage both launch this.
- **Build the `.deb`:** `run/build-deb.sh` produces
  `sherwood-toolbox_<version>_amd64.deb`.
- **Build the AppImage (Fedora/Arch/portable):** `run/build-appimage.sh` produces
  `Sherwood_Toolbox-<version>-x86_64.AppImage` (fat GTK-bundled via linuxdeploy + gtk plugin).
  WebKitGTK + GTK + gi are bundled from the build host. Leaves `AppDir` and writes
  `BUILD_INFO.txt` + `.buildinfo`. Runtime on targets only needs FUSE (or `--appimage-extract-and-run`)
  plus basic graphics; the AMD workarounds remain in AppRun. GitHub CI remains thin (Ubuntu 22.04).
- **Launch:** GNOME app grid ("Sherwood Toolbox"), `sherwood-toolbox` command,
  or double-click the AppImage.
- **Dev loop:** edit a file, restart the launcher (no build step for
  templates/CSS). Python code changes need a process restart.

## Composition core

| Path | Holds | Edit here to |
|---|---|---|
| `toolbox/registry.py` | The list of tools (id, label, icon, url_prefix, description, ready). Single source of truth. | Add, remove, rename, or reorder a tool. Set `ready=True` when its blueprint exists. |
| `toolbox/app.py` | `create_app()`: builds Flask, registers the hub + each tool blueprint (or a placeholder when `ready=False`), injects `tools` and `caps` into templates. | Change app-wide wiring or context. |
| `toolbox/config.py` | Env-driven paths and flags (upload dir, fork path, `OFFLINE`, max upload). | Change where files are written or default limits. |
| `toolbox/core/hub.py` | The hub blueprint (`/`) and the shared `POST /crm/credentials` route (verify + save a CRM login). Also holds web auth routes and token admin endpoints in WEB_MODE. | Change the hub, credential logic, or token admin. |
| `toolbox/core/auth.py` | Token store (hashed), bootstrap, validate, cookie helpers, role helpers. | Change auth behavior or token persistence. |
| `toolbox/core/capabilities.py` | Detects network / CRM creds / fork + web_mode + web_limits + role into `caps`. | Change graceful-degradation or web capability exposure. |
| `toolbox/core/crm.py` | Graceful wrapper around `restoration_common.fetch_job_info_from_url`, plus `parse_address` (splits a CRM address into street + City/State/ZIP). | Change CRM error handling or address parsing shared by Photo Report and Documents. |
| `toolbox/core/templates/_crm_credentials.html` + `static/js/crm_credentials.js` | The CRM credential entry form, shown in both tools' CRM panels when `caps.crm_configured` is false. | Change how a machine enters its CRM login. |

## Shared look (defined once)

| Path | Holds | Edit here to |
|---|---|---|
| `toolbox/core/templates/base.html` | Sidebar + topbar chrome; favicon links; every page extends this. | Change the shell, nav, or offline notice. |
| `toolbox/core/templates/hub.html` | Tile grid markup. | Change the hub tiles. |
| `toolbox/core/templates/placeholder.html` | "Coming soon" page for not-yet-ready tools. | n/a |
| `toolbox/core/static/css/toolbox.css` | The shared design system: tokens, chrome, buttons, panels, fields, cards. | Change the global look. Tool-specific CSS extends these tokens. |
| `toolbox/core/static/js/company_theme.js` | Reads `#company_id` option `data-color` and tints `.company-theme-surface` panels and `.company-tinted` buttons with the selected company's brand color. | Change company color theming behavior. |
| `toolbox/core/static/js/folder_links.js` | Sidebar "Code Docs" and "Archive" buttons: open the attachments / uploads folders via pywebview, or show their paths in a browser. | Change sidebar folder shortcuts. |
| `toolbox/core/static/img/mark.svg` | Adaptive favicon mark (light/dark via `prefers-color-scheme`). | Change the favicon glyph. |
| `toolbox/core/static/img/logo.png` | Header logo in the sidebar (transparent). | Replace the brand logo. |
| `toolbox/core/static/img/app_icon.png` / `app_icon.svg` | OS dock / app-grid icon (toolbox glyph). | Replace the desktop application icon. |

## Tools (one package each, mounted at its url_prefix)

| Path | Holds | Edit here to |
|---|---|---|
| `toolbox/tools/iws/static/js/calculator.js` | The IWS coverage math (client-side). | Change the calculation. |
| `toolbox/tools/iws/templates/iws.html` + `static/css/iws.css` | IWS form and result/diagram styling (shared classes + tokens). | Change the IWS UI. |
| `toolbox/tools/estimate_enhancer/pdf_ops.py` | Pure PDF analysis/enhancement logic (PyMuPDF). Section banners inside. | Change how estimates are analyzed or enhanced. |
| `toolbox/tools/estimate_enhancer/routes.py` | Routes, config wiring, the fork subprocess. | Change endpoints or file handling. |
| `toolbox/tools/estimate_enhancer/fork/add_image_links.py` | The bundled image-link helper run as a subprocess. | Change image-linking behavior. |
| `toolbox/tools/estimate_enhancer/attachments/` | Packaged IRC reference PDFs (read-only). Offered in Estimate Enhancer "Attach Documents". | Add/remove packaged reference PDFs. |
| `TOOLBOX_ATTACHMENTS_DIR` (default `~/.local/share/sherwood-toolbox/attachments`) | Writable "Code Docs" for the sidebar file manager (employees). Packaged PDFs are auto-seeded here on first use. | Employee-managed reference PDFs. |
| `toolbox/tools/estimate_enhancer/templates/estimate_enhancer.html` + `static/css/ee.css` | The 4-step flow UI, highlight term controls, and download handler. | Change the EstimateEnhancer UI. |
| `toolbox/tools/photo_report/routes.py` + `templates/photo_report.html` | Photo report form -> `restoration_common.PhotoReportPDF`. | Change inputs or wiring. The PDF layout is in restoration_common. |
| `toolbox/tools/documents/routes.py` + `templates/documents.html` | Invoice + certificate forms -> `restoration_common` generators; line items, signature. | Change inputs or wiring. The PDF layouts are in restoration_common. |
| `toolbox/tools/reconciler/{extract,match,reconcile,report,playbook}.py` | The estimate-comparison engine. `extract.py` reads PDF text and OCR via PyMuPDF only and tags each line item with its section (from the `Totals:` delimiter). `reconcile.py` has `reconcile_matched` (two-file) and `reconcile_effectiveness` (three-file: original + current carrier + supplement, with the grand-total approval math). `report.py` renders the Markdown/CSV that feeds the log. | Change parsing/sectioning (`extract.py`), matching (`match.py`), the RCV bridge or effectiveness math (`reconcile.py`), or the log body (`report.py`). |
| `toolbox/tools/reconciler/markup.py` | Paints the reconciliation onto the carrier PDF (PyMuPDF): a prepended summary page (recoverable, or approval effectiveness when an original estimate is given), in-line highlight bands + numbered tabs on under-measured lines, blue checks on approved supplement wins, green "scope to add" blocks for outstanding scope grouped by section with supplement line numbers, and appended detail pages. Line items are located by re-clustering page words into rows and matching the printed line number. | Change what the carrier markup looks like or how rows are located/anchored. |
| `toolbox/tools/reconciler/logbook.py` | Writes the per-run log (`.md`/`.json`/`.csv`) under `DATA_DIR/reconciler-logs` and one line on the `reconciler` logger. This is where the found data goes instead of the screen. | Change what is logged or where. |
| `toolbox/tools/reconciler/routes.py` + `templates/reconciler.html` + `static/css/reconciler.css` | Two-file upload, `POST /run` -> reconcile -> mark up the carrier PDF + log the details -> JSON (headline + counts + PDF download link). The download route serves the marked-up `.pdf` once, then deletes it. | Change the Reconciler endpoints or UI. |
| `toolbox/tools/reconciler/playbook.json` | Pre-built checklist of commonly-added items mined from the contractor corpus (bundled package data). | Rebuild with `python -m` on the standalone corpus if the corpus changes. |

## Bundled library (in this repo)

| Path | Holds | Edit here to |
|---|---|---|
| `vendor/restoration-common/restoration_common/` | Vendored headless PDF generators (`PhotoReportPDF`, `InvoicePDFGenerator`, `COCPDFGenerator`), CRM fetch/login, credential save, company/signature/logo helpers. No PyQt5. Installed into the venv with `--no-deps`. | Change PDF layouts or CRM logic. The canonical source is `~/.local/share/RestorationToolkit`; keep this copy in sync if that changes. |
| `vendor/restoration-common/restoration_common/crm.py` | CRM login and `fetch_job_info_from_url`. Looks for the custom CRM field "CRM Job/ID" first, then falls back to the state-ZIP search for `job_id`. | Change CRM login behavior or field mapping. |

## Run modes and artifacts

| Path | Holds | Edit here to |
|---|---|---|
| `run/standalone.py` | Browser launcher: waitress on a fixed `127.0.0.1` port, opens the browser. Detects an already-running instance. | Change browser-mode startup. |
| `run/desktop.py` | Desktop launcher: waitress in a background thread + pywebview window. Downloads use a native Save As dialog via the JS bridge. | Change desktop window behavior. |
| `run/sherwood-toolbox-wrapper.sh` | System wrapper installed as `/usr/bin/sherwood-toolbox`; seeds signatures and launches `run/desktop.py`. | Change how the `.deb` invokes the app. |
| `run/build-deb.sh` | Builds `sherwood-toolbox_<version>_amd64.deb` from the project tree. | Change what ships in the package. |
| `run/install-standalone.sh` | Portable installer: venv, bundled `restoration_common`, `.desktop`, zsh/bash alias, bundled signatures, prereq check. | Change portable (non-deb) install behavior. |
| `run/make-portable-bundle.sh` | Builds `sherwood-toolbox.tar.gz` (tracked files + signatures, no credentials). | Change what ships in the bundle. |
| `debian/` | Debian packaging metadata (`control`, `postinst`, `prerm`) and the deb-ready `.desktop` file with absolute paths. | Change package dependencies or install scripts. |
| `SHARING.md` | How to build, transfer, and install on another machine. | Update the sharing guide. |
| `AGENTS.md` | Agent-focused context: build steps, conventions, known fixes. | Update agent guidance. |
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
