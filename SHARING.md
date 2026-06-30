# Sharing the Sherwood Toolbox to another machine

A self-contained tarball you build on this machine, copy over, and install. The
target is Linux with a desktop (GNOME and other freedesktop desktops work).

## What travels in the bundle

- The toolbox app and the vendored `restoration_common` (no external install
  needed) plus the shipped default companies and logos.
- Your saved signatures (`signatures.json`), so signed documents work.

Not included: your CRM credentials (`crm.ini`). The other user enters their own
in the app (see CRM setup below).

## 1. Build the bundle (on this machine)

```
cd ~/Documents/projects/SherwoodToolbox
./run/make-portable-bundle.sh
```

This writes `sherwood-toolbox.tar.gz` in the project root. It contains committed
files plus your `signatures.json`; treat it as a file with personal data.

## 2. Prerequisites on the target machine

- Python 3 with the `venv` module. On Debian/Ubuntu/Zorin:
  `sudo apt install python3-venv`
- Internet for the one-time install (pip downloads PyMuPDF, reportlab, etc.).
  After that the app runs offline.

## 3. Install on the target machine

```
tar -xzf sherwood-toolbox.tar.gz
cd sherwood-toolbox
./run/install-standalone.sh
```

The installer creates a local venv, installs the app and the bundled
`restoration_common`, adds the GNOME launcher, adds a `sherwood-toolbox` alias to
`~/.zshrc` and/or `~/.bashrc`, and copies the bundled signatures into
`~/.config/restoration_toolkit/` (without overwriting an existing file). It is
idempotent; re-run it any time.

## 4. Launch

- GNOME app grid: "Sherwood Toolbox"
- Terminal: `sherwood-toolbox` (open a new shell first, or `source ~/.zshrc`)

The launcher serves on `http://127.0.0.1:8765` and opens the browser. It always
uses that fixed port so each tool's saved browser state (such as the Ice and
Water Shield history) stays consistent.

## 5. CRM setup on the new machine

CRM lookup needs that user's own credentials. On the new machine, open Photo
Report or Documents: while no credentials are saved, the CRM panel shows a short
form. Enter the CRM username and password and click "Save CRM login". The app
verifies the login, stores it at `~/.config/photo_report_generator/crm.ini`
(permissions 600), and enables Fetch. Until then, all fields can be entered
manually.

## Updating the toolbox later

Rebuild the bundle here, copy it over, extract it over the old folder (or into a
fresh one), and run `./run/install-standalone.sh` again. The venv and config are
reused; nothing is lost.

## Removing it

- Delete the extracted `sherwood-toolbox` folder (includes its `.venv`).
- Remove `~/.local/share/applications/sherwood-toolbox.desktop`.
- Remove the `sherwood-toolbox` alias line from `~/.zshrc` / `~/.bashrc`.
- Optional: delete `~/.config/restoration_toolkit/` and
  `~/.config/photo_report_generator/` to clear companies, signatures, and CRM
  credentials.
