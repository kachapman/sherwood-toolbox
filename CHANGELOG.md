# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Estimate Reconciler** tool: upload a carrier estimate and a contractor Xactimate estimate for the same claim. The tool lists the line items the carrier omits (grouped by category, largest RCV first), breaks down the shared items by quantity and price, flags whether Overhead & Profit is applied on each estimate, and reports the RCV gap, with downloadable `.md`/`.csv` reports. The engine (parse, match, reconcile, report) is ported from the standalone reconciler.
- Reconciler surfaces the carrier's stated coverage limitations, quoted verbatim from the estimate (matching exclusion, ACV/depreciation schedule, policy exclusions), plus labeled "denial hypotheses" that tie clusters of missing items to a quoted exclusion (badged "Quoted exclusion") or, absent a quote, mark them as an inference to verify (badged "Inference"). A themed hypothesis is emitted only when items of that theme are actually missing, so the tool never asserts a reason for scope the carrier included.
- Tesseract OCR support as an **optional** dependency for image-only (scanned) estimates. When Tesseract is absent, the Reconciler shows a clear message and continues without crashing.

### Changed
- The Reconciler reads PDF text and OCR through PyMuPDF (`fitz`) only, removing any poppler/`pdftotext` dependency. Its layout-preserving extraction reproduces the standalone CLI's figures to the cent.
- **Reconciler tuned for the shared web-server hardware:** OCR of image-only scans is the one heavy path (about 2.5 s and tens of MB per page at 300 DPI). It is now bounded by env vars read per request so the container can cap it without a rebuild: `TOOLBOX_RECONCILER_OCR=0` (disable; scans then degrade to the "re-export as text PDF" message), `TOOLBOX_RECONCILER_OCR_DPI` (default 300; 150 quarters the pixels and memory), and `TOOLBOX_RECONCILER_OCR_MAX_PAGES`. Line-item location stops once every wanted item is found, so trailing photo/addendum pages on a long carrier are never word-clustered. Log writes are non-fatal, so a read-only log directory on the container cannot fail a reconciliation. Recommended production settings are in `AGENTS.md`.
- **Reconciler plain-language summary:** every reconciliation now leads its summary (both the marked-up PDF's first page and the browser result) with two or three plain sentences a reader can take in at a glance, with the coverage-sublimit warning set off as a "Heads up" callout. The narrative is deterministic (no model call, works offline); qualitative words are chosen from the numbers. The statistical tiles stay below it for anyone verifying the math. Built by `reconcile.build_narrative`.
- **Reconciler visual-estimating flow:** instead of rendering the missing items, shared deltas, and hypotheses as on-screen tables, the Reconciler now marks up the carrier PDF and logs the details. The marked-up PDF carries a prepended summary page (RCV gap, estimated recoverable, color legend), in-line highlight bands with numbered margin tabs on the line items the contractor measured higher (colored by dollar size), the missing scope painted in green onto the carrier pages below the section it belongs to, and appended detail pages for the quantity differences, the full missing-scope list by category, the RCV build-up, the denial hypotheses, and the quoted carrier statements. Line items are located on the page by re-clustering the words into rows and matching the printed line number, so an item is highlighted or anchored in place even when its description wraps or repeats; an image-only scan degrades to the appended pages. The full line-by-line breakdown is written to a per-run log (`.md`/`.json`/`.csv`) under `~/.local/share/sherwood-toolbox/reconciler-logs`. The browser shows only the headline figures, the counts, and the marked-up-PDF download. New modules: `markup.py`, `logbook.py`.
- **Reconciler paints missing scope in place:** line items in the contractor scope but absent from the carrier are drawn as green "scope to add" insertion rows onto the carrier pages, grouped by their supplement section and keyed by supplement line number, anchored below the matching carrier section. Blocks stack rather than overlap; when a block runs out of room it caps and adds a "+N more" line pointing to the full list at the back. The under-measured color thresholds were recalibrated to be less aggressive: major (red) is now a $2,000-or-more dollar shortfall, moderate (amber) $1,000 to $2,000, minor (yellow) under $1,000.
- **Reconciler coverage-sublimit hypothesis:** predicts when a dwelling-extension / other-structures sublimit may cap the payout, so pushing for more approvals on the secondary structure (a barn, shed, detached garage) does not help and can lower the homeowner's net by shifting the settlement to ACV. It classifies line items into the dwelling vs the secondary structure, detects the sublimit coverage in the estimate text, and in three-way mode measures the divergent approval rate (on VanWinkle: 65% of the dwelling ask approved but 0% of the barn ask, with the barn RCV and depreciation frozen identical to the original). Always a labelled inference to verify, never asserted, since the limit lives on the declarations. It leads the denial hypotheses and shows an amber caution on the effectiveness summary. New: `reconcile.coverage_limit_hypothesis`, `extract.is_extension_item`, `extract.detect_sublimit_coverages`.
- **Reconciler three-way approval effectiveness:** an optional third upload, the original carrier estimate, turns the tool into an approval tracker. It measures the supplement ask (contractor minus original), what the carrier has approved to date (current minus original), the outstanding scope (contractor minus current), and the approval rate, all from grand totals so they are reliable to the cent. The marked-up PDF leads with the approval rate, checks off approved supplement items in blue on the carrier pages, and paints the outstanding scope in green by section. Line items now carry their estimate section (parsed from the `Totals:` delimiter). Without the original estimate the tool falls back to the two-file "what's missing" flow. New reconcile entry point: `reconcile_effectiveness`.

### Fixed
- **Reconciler effectiveness summary reformatted.** The prepended summary page now
  titles "Reconciliation report - <claimant>" and leads with one sage panel that
  carries the APPROVAL EFFECTIVENESS label, the large percentage, and the money
  summary together; the coverage-sublimit "Heads up" callout follows immediately. The
  under-measured shortfall scale was rebanded to red at $500+, salmon at $150-$500,
  and amber under $150 (was $2,000 / $1,000), with the legend updated to match. The
  sublimit caution wording softened to "anything on the scope that is pushed past the
  limit would not necessarily raise the payout." `markup._effectiveness_headline`,
  `markup.SEVERITIES`, `reconcile._secondary_caution`.
- **Reconciler under-measured flags now print the RCV gap in place.** The left-margin
  tab on each shared line the carrier measured short of the contractor shows the
  dollar shortfall (e.g. $839.89) instead of a cross-reference number; cents are kept
  when they fit the narrow margin and dropped for a wide 4-digit gap ($1,036). The
  "Quantity differences" detail table drops its now-redundant number column and is
  keyed by the on-page RCV gap and page number. `markup.flag_row` / `_flag_money`.
- **Reconciler section reconciliation no longer misroutes a whole elevation.** When the
  carrier and contractor label the same scope under different elevations (Kevin Black:
  carrier's 627 SF siding is "Left Elevation", the contractor splits siding across
  "Back" and "Left"), the carrier→contractor section vote could tie and break on
  insertion order, routing the carrier's entire Left subtotal onto contractor "Back
  Elevation" so Back read **$0 net** (missed) and Left was over-stated. The vote now
  breaks ties by section-name overlap, so Back shows its real **$4,673.14** and Left
  $1,492.24. `reconcile.map_and_diff_sections`.
- **Reconciler paints every outstanding section block in place.** Blocks were painted
  in dollar order, so a block anchored low on a carrier page (Left Elevation at the
  page foot) advanced the per-page cursor past the page bottom and blocks anchored
  higher on the same page (Back, Right Elevation) found no room and silently dropped.
  Blocks now paint top-to-bottom per page; on Black this restored the Back and Right
  Elevation blocks (painted rows 13 → 20), and Esposito/Campbell now paint every
  missing line. `markup.paint_outstanding_by_section`.
- **Reconciler approval effectiveness now lists approved items consistently.** Approved items are "added or revised": the tool credited only brand-new carrier lines and missed lines the carrier *raised* toward the contractor. It now also reports each matched line whose RCV rose from the original as a raised ("revised") approval, keyed to the contractor line it moved toward, checked in green in place and listed under "Raised lines" on the Approved-items page (Kevin Black: the R&R Gutter line raised 91.58 → 99 LF, +$82.51, matching the contractor's 99 LF, previously invisible). New: `reconcile.ApprovedRevision`, `Recon.approved_added` / `approved_revised`.
- **Reconciler skips the carrier's "guide to reading your adjuster summary" sample page.** Allstate National Catastrophe Team (and similar) estimates append a two-page guide against a fictitious insured with sample line items (a refrigerator, a coffee table, a Samsung TV). The parser was scraping those as real scope and misreading the sample's `$1,734.85` as the estimate's sales tax; the Black original read 35 items / tax $1,734.85 instead of 31 items / tax $958.32 (its line-item total $28,961.94 + tax $958.32 now ties to the printed grand $29,920.26 to the cent). Detected by the guide header or two canned-placeholder hits and dropped before parsing. New: `extract._is_boilerplate_page`.
- **Reconciler no longer flags an attached garage door as a secondary structure.** "R&R Wrap wood garage door frame", "Overhead (garage) door opener", and "garage floor" are dwelling (Coverage A) components; the coverage-sublimit caution was firing on the word "garage" (a $267 false "secondary structure" warning on the Black claim). `is_extension_item` now excludes garage door/floor/opener/slab descriptions, and the caution no longer fires when the only signal is a `$0.00` "Other Structures" bucket named in the standard coverage recap. Real "Garage Roof" / "Shed Roof" sections and ribbed metal-building panels are still detected.
- Carrier grand RCV is now read from the estimate's recap total instead of summing every "Replacement Cost Value" occurrence, which double-counted coverage subtotals and picked up legend-page example numbers (e.g. Gritzman read $33,056.74 instead of the correct $32,813.71). Extraction now tries, in order: an Allstate-style "Loss Recap Summary" grand `TOTAL` row, the sum of distinct per-coverage "Replacement Cost Value" lines, then the "Line Item Totals" row (RCV column identified by RCV − depreciation = ACV). Verified against 14 carrier estimates.

### Training data
- Added a page classifier (`extract.classify_page` / `estimate_page_indexes`) that separates estimate pages (line items, totals, coverage statements) from photo sheets, vector sketches, blanks, and the sample guide page. `reconciler/build_training.py` uses it to strip the raw estimate PDFs into a clean, sorted `training/carrier` + `training/contractor` corpus (935 photo/sketch pages removed from the contractor files) and verifies every strip is lossless — the parser reads the identical line-item count and grand RCV from the stripped copy. The bundled `playbook.json` was rebuilt from the cleaned corpus (17 claims, O&P 14/17 at 20%, 286 distinct items).

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
