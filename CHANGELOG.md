# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Estimate Reconciler** tool: upload a carrier estimate and a contractor Xactimate estimate for the same claim. The tool lists the line items the carrier omits (grouped by category, largest RCV first), breaks down the shared items by quantity and price, flags whether Overhead & Profit is applied on each estimate, and reports the RCV gap, with downloadable `.md`/`.csv` reports. The engine (parse, match, reconcile, report) is ported from the standalone reconciler.
- Tesseract OCR support as an **optional** dependency for image-only (scanned) estimates. When Tesseract is absent, the Reconciler shows a clear message and continues without crashing.

### Changed
- The Reconciler reads PDF text and OCR through PyMuPDF (`fitz`) only, removing any poppler/`pdftotext` dependency. Its layout-preserving extraction reproduces the standalone CLI's figures to the cent.

### Fixed
- Carrier grand RCV is now read from the estimate's recap total instead of summing every "Replacement Cost Value" occurrence, which double-counted coverage subtotals and picked up legend-page example numbers (e.g. Gritzman read $33,056.74 instead of the correct $32,813.71). Extraction now tries, in order: an Allstate-style "Loss Recap Summary" grand `TOTAL` row, the sum of distinct per-coverage "Replacement Cost Value" lines, then the "Line Item Totals" row (RCV column identified by RCV − depreciation = ACV). Verified against 14 carrier estimates.

## [0.2.0] - 2026-06-30

### Added
- Native desktop application using pywebview (runs in its own window instead of a browser).
- Native "Save As" dialog for generated PDFs and ZIPs in the desktop build.
- Sidebar "Code Docs" and "Archive" folder shortcut buttons.
- Company color theming (faint tint + button colors) for Documents and Photo Report tools.
- Support for the "CRM Job/ID" custom CRM field when fetching job data.
- Configurable CRM base URL via `TOOLBOX_CRM_BASE_URL` environment variable.
- Separate application icon (`app_icon.png`) for the OS dock and menu.
- Proper `.deb` packaging (`run/build-deb.sh` + `debian/` directory).
- `AGENTS.md` for coding agent guidance.
- This `CHANGELOG.md`.

### Changed
- Default CRM login URL changed from `office.vanguardadj.com` to `office.publicadjustermidwest.com`.
- Highlight color dropdowns in Estimate Enhancer are now readable (white background + colored borders + swatches).
- `.desktop` file now uses absolute paths so the app appears correctly in GNOME/KDE/etc.
- Updated `STRUCTURE.md` and `SHARING.md` for the new desktop-first packaging.

### Removed
- Spell checker functionality from Estimate Enhancer (including `pyspellchecker`, `spell_utils.py`, and `spell_vocab.py`).

### Fixed
- GNOME application menu not showing the app due to placeholder paths in the `.desktop` file.
- PDF downloads in the desktop build would open the PDF inline instead of offering a Save dialog.
- Text in some highlight color dropdowns was unreadable (green, blue, purple, coral).

## [0.1.0] - 2026-06-17

### Added
- Initial release of the browser-based Sherwood Toolbox.
- Tools included: Estimate Enhancer, Ice & Water Shield Calculator, Photo Report, and Documents.
- Portable tarball installer (`run/install-standalone.sh`).
- Bundled `restoration_common` for PDF generation and CRM features.
- Local-only operation (uploads go to `~/.local/share/sherwood-toolbox/`).

[Unreleased]: https://github.com/kachapman/sherwood-toolbox/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/kachapman/sherwood-toolbox/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kachapman/sherwood-toolbox/releases/tag/v0.1.0
