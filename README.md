# Sherwood Toolbox

A local, offline-first desktop application that bundles several construction-estimating tools under one simple hub.

**Original author:** Meat Claud & his Clanker  
**Current maintenance:** This repository is being taken over and actively improved by the current owner.

## What is Sherwood Toolbox?

Sherwood Toolbox is a modular Flask application that provides a collection of practical tools for property restoration and insurance estimating work. It runs as a native desktop application on Linux (using pywebview) or can be launched in a browser during development.

All processing happens locally on your machine. Uploaded files stay on your system.

### Included Tools

- **Estimate Enhancer**  
  Upload Xactimate PDFs, automatically detect zero-quantity line items and duplicate photo names, add clickable image links, highlight custom terms, and attach IRC reference documents.

- **Ice & Water Shield Calculator**  
  Fast client-side calculator for determining ice-and-water-shield coverage.

- **Photo Report**  
  Generate professional, company-branded photo report PDFs from a job’s images.

- **Documents**  
  Create invoices and certificates of completion, with CRM auto-fill, line items, signatures, and company branding.

- **Estimate Reconciler**  
  Upload a carrier insurance estimate and a contractor Xactimate estimate for the same claim. The tool marks up the carrier PDF: a summary page with the Replacement Cost Value (RCV) gap and estimated recoverable, the line items the contractor measured higher highlighted in place and colored by how large the dollar gap is, and the missing scope and Overhead & Profit listed by category on appended pages. The full line-by-line breakdown, the RCV bridge, and the carrier's quoted coverage statements are written to a per-run log on the machine rather than shown on screen.

## Features

- Native desktop window (pywebview) with proper Save As dialogs
- Optional CRM integration (auto-fills customer, claim, address, and Job/ID)
- Company color theming — panels and buttons get a faint brand tint based on the selected contractor
- Sidebar shortcuts: **Code Docs** and **Archive** folder buttons
- Fully offline after the initial one-time install

## Installation

### .deb package (Debian, Ubuntu, Zorin, Pop!_OS, Linux Mint, etc.)

```bash
sudo dpkg -i sherwood-toolbox_0.2.0_amd64.deb
sudo apt-get install -f   # if dependencies are missing
```

Launch **Sherwood Toolbox** from your application menu.

### AppImage (Fedora, Arch, and other distros)

Download `Sherwood_Toolbox-*.AppImage`, make it executable and run:

```bash
chmod +x Sherwood_Toolbox-*.AppImage
./Sherwood_Toolbox-*.AppImage
```

On Fedora 43 (especially with AMD Ryzen graphics) you also need:
```bash
sudo dnf install webkit2gtk4.1 python3-gobject
```

The AppImage includes the native pywebview desktop shell and Fedora/AMD workarounds.

### Portable tarball (works on most Linux distributions)

```bash
tar -xzf sherwood-toolbox.tar.gz
cd sherwood-toolbox
./run/install-standalone.sh
sherwood-toolbox
```

See [SHARING.md](SHARING.md) for detailed distribution instructions.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install --no-deps -e vendor/restoration-common
python3 run/standalone.py
```

Then open the URL printed in the terminal.

### Optional dependency: Tesseract OCR

The Estimate Reconciler reads text-based PDFs with no extra software. For image-only (scanned) estimates it uses Tesseract OCR when it is installed, and otherwise shows a clear message and continues without crashing. To enable OCR:

```bash
sudo apt-get install tesseract-ocr        # Debian/Ubuntu/Zorin
sudo dnf install tesseract                 # Fedora
```

No other tool requires Tesseract.

## Project Structure

- `toolbox/` — Core Flask application and shared assets
- `toolbox/tools/` — Individual tools (estimate_enhancer, iws, photo_report, documents, reconciler)
- `vendor/restoration-common/` — Vendored PDF generators and CRM helpers
- `run/` — Launchers and packaging scripts
- `debian/` — Debian package metadata
- `STRUCTURE.md` — Detailed project layout
- `AGENTS.md` — Guidance for coding agents
- `CHANGELOG.md` — Release history

## CRM Integration

Photo Report and Documents can optionally fetch data from a CRM.

- Default CRM base URL: `https://office.publicadjustermidwest.com`
- Override with the `TOOLBOX_CRM_BASE_URL` environment variable
- The scraper first looks for a custom field labeled **"CRM Job/ID"**. If that field is empty or missing, it falls back to searching the page text for a state-ZIP pattern.

## Author & Credits

- **Original creator**: Meat Claud & his Clanker
- This fork is being maintained and extended by the current owner.

## License

To be determined.
