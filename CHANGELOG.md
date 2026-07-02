# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-07-02

### Added
- Full web deployment mode (`TOOLBOX_WEB_MODE=1`):
  - Token-based authentication (login form, cookie "remember me", Bearer token support).
  - Employee vs customer roles:
    - Employees see all tools + sidebar folders (Code Docs, Archive) + Admin.
    - Customers see only Estimate Enhancer + IWS; everything else is hidden or redirected.
  - First successful `/login` with any value bootstraps an employee token.
  - Admin UI to create and revoke employee and customer tokens (plaintext shown only once).
- Web-only upload limits (visible to users, enforced server-side, editable in Admin):
  - Photo Report: `photo_max_count`, `photo_max_mb_per_file`.
  - Estimate Enhancer: `enhancer_max_mb` (existing) + new `enhancer_max_photo_pages` (default 50).
- Estimate Enhancer major robustness improvements for web / low-resource servers:
  - Background processing: `/process` is now a lightweight starter; heavy work runs in a daemon thread.
  - Status polling every ~3 seconds with coarse stage updates ("Preparing…", "Linking…", "Flattening…", "Attaching…", "Finalizing…").
  - "View Enhancer Log" button (web only) that opens a popout modal with captured processing + fork output and a Refresh button.
  - Early photo page count in `/analyze` (`photo_page_count`) and a muted-note warning on web when over the configured cap (warning only; processing is never hard-blocked).
  - psutil-based RSS memory logging at key points (start, before fork, before/after final save).
  - Configurable fork subprocess timeout via `ENHANCER_FORK_TIMEOUT` (default 180s).
- Pure relative URL construction for image links inside background jobs (no Flask `url_for` from worker threads).
- `ISSUES.md` documenting historical problems (context/URL errors, large-photo crashes, auth "not in web mode", server reload behavior, log button visibility, etc.).
- Dockerfile and `deploy/docker-compose.example.yml` for containerized web deployments.
- Expanded `deploy/DEPLOY.md` covering web auth, roles, limits (including the new enhancer photo cap), volumes, CRM sharing, reverse proxy, first-run bootstrap, and updating.

### Changed
- `psutil` is now a regular dependency (was best-effort import) so memory logging is always available in web deployments.
- Estimate Enhancer fork timeout is no longer hardcoded at 120s.
- Version bumped to 0.3.0 across `pyproject.toml` and `debian/control`.
- README and SHARING install examples updated to 0.3.0.
- Enhancer "Process" flow now always goes through the starter + poll path (desktop and web).

### Fixed
- "Working outside of application context" and "Unable to build URLs outside an active request without 'SERVER_NAME'" when processing PDFs in web mode.
- Enhancer jobs with 50+ photo pages could crash or OOM on small droplets (background work + limits + logging + tunable timeout).
- Token UI and auth endpoints returned "not in web mode" unless `TOOLBOX_WEB_MODE=1` was set and the server was bound appropriately.
- Python changes were not reflected without a full server restart (documented expectation for waitress + `use_reloader=False`).
- Enhancer log button only visible in the Enhance step and disappeared on successful completion (documented current behavior; no logic change).

### Deployment / Packaging
- Pushing a `v0.3.0` (or later `v*`) tag triggers the existing AppImage CI workflow.
- Local builds still use `./run/build-deb.sh` and `./run/build-appimage.sh`.
- Web images can be built from the provided `Dockerfile` and wired via the example compose file.

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

[Unreleased]: https://github.com/kachapman/sherwood-toolbox/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/kachapman/sherwood-toolbox/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/kachapman/sherwood-toolbox/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kachapman/sherwood-toolbox/releases/tag/v0.1.0
