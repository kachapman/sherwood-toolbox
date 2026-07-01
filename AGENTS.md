# Agent guidance for Sherwood Toolbox

This file is for coding agents working on the Sherwood Toolbox. Human contributors
should start with `README.md` (if present) and `STRUCTURE.md`.

## Project overview

A local-only Flask application that bundles several estimating tools under one
hub. It is distributed as:
- a `.deb` package (native pywebview desktop shell on Debian/Ubuntu-based distros)
- an AppImage (portable, recommended for Fedora 43+, Arch, and other distros)
- a portable tarball (browser mode)

The desktop builds use pywebview 5+ with GTK/WebKitGTK.

- **Language / framework:** Python 3.9+, Flask 3+, Waitress, pywebview 5+
- **UI:** Server-rendered Jinja2 templates, minimal vanilla JS, shared CSS in
  `toolbox/core/static/css/toolbox.css`
- **Architecture:** Modular monolith — one Blueprint per tool in
  `toolbox/tools/<tool>/`
- **State:** User data lives under `~/.local/share/sherwood-toolbox/` and
  `~/.config/restoration_toolkit/`. The source tree is read-only after install.

## How to build and run

### Development (browser mode)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install --no-deps -e vendor/restoration-common
python3 run/standalone.py
```

Open the URL it prints.

### Build the `.deb`

```bash
./run/build-deb.sh
```

Produces `sherwood-toolbox_<version>_amd64.deb`.

### Build the AppImage (portable, for Fedora/Arch/etc.)

```bash
./run/build-appimage.sh
```

Produces `Sherwood_Toolbox-<version>-x86_64.AppImage`.

**On Fedora 43 + AMD (common case):**
```bash
sudo dnf install python3-gobject webkit2gtk4.1 fuse
```

The resulting AppImage embeds Fedora/AMD workarounds (disables dmabuf/compositing, forces X11) and the native pywebview desktop shell.

### Install / upgrade the `.deb`

```bash
sudo dpkg -i sherwood-toolbox_<version>_amd64.deb
```

If dependency errors appear: `sudo apt-get install -f`.

## Key files and where to make changes

- Add/remove/reorder tools: `toolbox/registry.py`
- App wiring / context: `toolbox/app.py`
- Paths, limits, run mode: `toolbox/config.py`
- Shared page chrome: `toolbox/core/templates/base.html`
- Shared CSS: `toolbox/core/static/css/toolbox.css`
- Company color theming: `toolbox/core/static/js/company_theme.js`
- Sidebar folder shortcuts: `toolbox/core/static/js/folder_links.js`
- CRM fetch/login logic: `vendor/restoration-common/restoration_common/crm.py`
- CRM address parsing wrapper: `toolbox/core/crm.py`
- `.deb` metadata: `debian/`
- Build script: `run/build-deb.sh`

See `STRUCTURE.md` for a full path-by-path reference.

## Conventions

- HTTP routes live in `routes.py`. Pure logic lives in `*_ops.py`.
- Tool-specific CSS goes in `toolbox/tools/<id>/static/css/<id>.css`.
- Use inline SVG icons, not emoji or image icons, for UI elements.
- Keep files around 300 lines; split by concern.
- Generated files (`toolbox-spec.html`) are never edited by hand — edit partials
  in `spec/partials/` and run `python3 spec/build_spec.py`.
- The vendored `restoration_common` package has its canonical source at
  `~/.local/share/RestorationToolkit`. If you change it here, keep the copies in
  sync.

## Known fixes and behaviors

### CRM base URL
The CRM login URL is configurable via the `TOOLBOX_CRM_BASE_URL` environment
variable and defaults to `https://office.publicadjustermidwest.com`. The login
endpoint is `<base>/Auth.aspx`.

### CRM Job/ID field
`fetch_job_info_from_url()` first looks for a custom CRM field labeled
"CRM Job/ID" (case-insensitive, with or without the slash). If that field is
empty or missing, it falls back to searching the page text for a state-ZIP
pattern.

### Downloads in the desktop shell
WebKitGTK does not reliably honor `Content-Disposition: attachment`. The desktop
build uses a pywebview JS bridge (`window.pywebview.api.save_file`) to show a
native Save As dialog. Browser mode falls back to a normal `<a download>`.

### Company color theming
`company_theme.js` reads the selected company's `data-color` and applies:
- a faint tinted background + left border to `.company-theme-surface` panels,
- the brand color to `.company-tinted` buttons.
Documents and Photo Report panels carry the `company-theme-surface` class; their
generate buttons carry `company-tinted`.

### Sidebar folder buttons
**Code Docs** opens `/opt/sherwood-toolbox/toolbox/tools/estimate_enhancer/attachments/`.
**Archive** opens `~/.local/share/sherwood-toolbox/uploads/`. In a browser, the
buttons show an alert with those paths instead.

### Icons
- `toolbox/core/static/img/logo.png` — Sherwood brand logo in the sidebar.
- `toolbox/core/static/img/app_icon.png` — Toolbox icon for the OS dock/app grid.
- `toolbox/core/static/img/mark.svg` — Favicon.

## Versioning and release

Versions are stored in:
- `pyproject.toml` (`project.version`)
- `debian/control` (`Version:`)

To release:
1. Update both version strings.
2. Commit and tag: `git tag vX.Y.Z`.
3. Run `./run/build-deb.sh` (for .deb) and/or `./run/build-appimage.sh` (for portable AppImage).
4. Push commits and tags.

Pushing a `vX.Y.Z` tag triggers `.github/workflows/build-appimage.yml`, which builds
the AppImage on GitHub (Ubuntu 22.04 runner) and attaches it to the GitHub Release.

## Testing checklist for agents

After changes that affect the desktop shell, packaging, or CRM:
- [ ] `./run/build-deb.sh` completes without errors.
- [ ] `sudo dpkg -i sherwood-toolbox_*.deb` installs cleanly.
- [ ] `./run/build-appimage.sh` completes without errors (and passes its Fedora/AMD pre-flight).
- [ ] `Sherwood_Toolbox-*.AppImage` is produced and is executable.
- [ ] Launching `sherwood-toolbox` (or the AppImage) opens the desktop window.
- [ ] Estimate Enhancer downloads show a Save As dialog.
- [ ] Documents / Photo Report panels tint when the company dropdown changes.
- [ ] CRM Fetch populates customer, claim, address, and Job/ID fields.

For AppImage + Fedora 43 + AMD specifically:
- [ ] On a Fedora 43 machine (or the Ubuntu CI runner): build succeeds with `python3-gobject` + `webkit2gtk4.1` (or equivalent `gir1.2-webkit2-4.1`) present.
- [ ] On AMD Ryzen iGPU hardware the AppImage starts without a black window (workarounds in AppRun are active).

