# Sharing the Sherwood Toolbox to another machine

Two ways to distribute: a `.deb` package (recommended for Debian/Ubuntu/Zorin
with a desktop), or a self-contained tarball. Both contain the toolbox app, the
vendored `restoration_common`, and the shipped default companies and logos.

Not included in either package: your CRM credentials (`crm.ini`). The other user
enters their own in the app (see CRM setup below).

## Option A: `.deb` package (recommended)

### 1. Build the `.deb` (on this machine)

```bash
cd /path/to/sherwood-toolbox
./run/build-deb.sh
```

This writes `sherwood-toolbox_<version>_amd64.deb` in the project root.

### 2. Install on the target machine

```bash
sudo dpkg -i sherwood-toolbox_0.3.0_amd64.deb
```

If `dpkg` complains about missing dependencies, run:

```bash
sudo apt-get install -f
```

The post-install script creates a local venv at `/opt/sherwood-toolbox/.venv`,
installs the app and bundled `restoration_common`, adds the GNOME/freedesktop
launcher, and copies bundled signatures into
`~/.config/restoration_toolkit/` (without overwriting an existing file).

### 3. Launch

- GNOME app grid: **Sherwood Toolbox**
- Terminal: `sherwood-toolbox`

The desktop launcher runs inside a native pywebview window on port `8766`
(default). Generated PDFs/ZIPs open a native Save As dialog. The sidebar has
**Code Docs** and **Archive** buttons that open the attachments and uploads
folders.

## Option B: AppImage (recommended for Fedora, Arch, Zorin, and other non-.deb distros)

### 0. Get the source on the target machine

```bash
# SSH (if you have a key)
git clone git@github.com:kachapman/sherwood-toolbox.git
cd sherwood-toolbox

# or HTTPS (use a Personal Access Token for password)
git clone https://github.com/kachapman/sherwood-toolbox.git
cd sherwood-toolbox
```

**Important:** Build and run the AppImage on the machine where you will use it
(Zorin, Fedora 43, etc.) so the bundled Python can use the system's WebKitGTK +
PyGObject bindings.

You can either:

- Download a prebuilt `Sherwood_Toolbox-*.AppImage` from the
  [Releases page](https://github.com/kachapman/sherwood-toolbox/releases), or
- Build it yourself (see below).

### 1. Build the AppImage

```bash
cd /path/to/sherwood-toolbox
chmod +x run/build-appimage.sh
./run/build-appimage.sh
```

This produces `Sherwood_Toolbox-<version>-x86_64.AppImage` in the project root.

**Build-time requirements** (especially on Fedora 43 + AMD or Zorin):
```bash
# Fedora 43 / recent Fedora
sudo dnf install python3-gobject webkit2gtk4.1 fuse

# Zorin / Debian / Ubuntu builders
sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.1 fuse
```

### 2. Runtime requirements on the target machine

The AppImage bundles its own Python and most libraries, but still needs the
system WebKitGTK + PyGObject bindings because it uses the native GTK backend:

```bash
# Fedora 43 (AMD Ryzen iGPUs are common here)
sudo dnf install webkit2gtk4.1 python3-gobject

# Zorin / Ubuntu-based
sudo apt install gir1.2-webkit2-4.1 python3-gi python3-gi-cairo
```

### 3. Run it

```bash
chmod +x Sherwood_Toolbox-*.AppImage
./Sherwood_Toolbox-*.AppImage
```

The AppImage launches the native pywebview desktop shell. On AMD hardware
(Ryzen 6000/7000/8000 series iGPUs) it automatically sets these workarounds
to avoid black/blank windows and dmabuf crashes:

- `WEBKIT_DISABLE_COMPOSITING_MODE=1`
- `WEBKIT_DISABLE_DMABUF_RENDERER=1`
- `GDK_BACKEND=x11`

If you still get a black window, try:
```bash
LIBGL_ALWAYS_SOFTWARE=1 ./Sherwood_Toolbox-*.AppImage
```

### 4. Updates

Rebuild the AppImage on the source machine (or download a newer prebuilt) and
copy the new `.AppImage` over. No install step is required on the target.

## Option C: Portable tarball

### 1. Build the bundle

```bash
cd /path/to/sherwood-toolbox
./run/make-portable-bundle.sh
```

This writes `sherwood-toolbox.tar.gz` in the project root. It contains committed
files plus your `signatures.json`; treat it as a file with personal data.

### 2. Prerequisites on the target machine

- Python 3 with the `venv` module. On Debian/Ubuntu/Zorin:
  `sudo apt install python3-venv`
- Internet for the one-time install (pip downloads PyMuPDF, reportlab, etc.).
  After that the app runs offline.

### 3. Install on the target machine

```bash
tar -xzf sherwood-toolbox.tar.gz
cd sherwood-toolbox
./run/install-standalone.sh
```

The installer creates a local venv, installs the app and the bundled
`restoration_common`, adds the GNOME launcher, adds a `sherwood-toolbox` alias to
`~/.zshrc` and/or `~/.bashrc`, and copies the bundled signatures into
`~/.config/restoration_toolkit/` (without overwriting an existing file). It is
idempotent; re-run it any time.

### 4. Launch

- GNOME app grid: "Sherwood Toolbox"
- Terminal: `sherwood-toolbox` (open a new shell first, or `source ~/.zshrc`)

The tarball installer launches the app in a browser window. For the pywebview
desktop shell, use the `.deb` or AppImage instead.

## CRM setup on the new machine

CRM lookup needs that user's own credentials. On the new machine, open Photo
Report or Documents: while no credentials are saved, the CRM panel shows a short
form. Enter the CRM username and password and click "Save CRM login". The app
verifies the login, stores it at `~/.config/photo_report_generator/crm.ini`
(permissions 600), and enables Fetch. Until then, all fields can be entered
manually.

The CRM scraper first looks for a custom field named **CRM Job/ID**. If that
field is empty or missing, it falls back to searching the page text for a
state-ZIP pattern.

## Updating the toolbox later

For `.deb` installs, rebuild and re-run `sudo dpkg -i` on each target machine.
For tarball installs, rebuild the bundle, copy it over, extract it over the old
folder (or into a fresh one), and run `./run/install-standalone.sh` again. The
venv and config are reused; nothing is lost.

## Removing it

For `.deb` installs:

```bash
sudo apt remove sherwood-toolbox
```

For tarball installs:

- Delete the extracted `sherwood-toolbox` folder (includes its `.venv`).
- Remove `~/.local/share/applications/sherwood-toolbox.desktop`.
- Remove the `sherwood-toolbox` alias line from `~/.zshrc` / `~/.bashrc`.
- Optional: delete `~/.config/restoration_toolkit/` and
  `~/.config/photo_report_generator/` to clear companies, signatures, and CRM
  credentials.
