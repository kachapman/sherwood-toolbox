# Known Issues & Historical Problems

This document records problems that were encountered during development and deployment
so they are not accidentally re-introduced. It is intended for maintainers and future
agents working on the project.

## Estimate Enhancer Background Jobs (Web Mode)

### Problem: "Working outside of application context"
- **Symptom**: Calling `process()` on a PDF in web mode produced:
  `RuntimeError: Working outside of application context.`
- **Root cause**: The `/process` route became a lightweight starter that spawned a
  `threading.Thread` running `_run_enhance()`. Inside that thread, code called
  `build_image_link_payload()`, which used Flask's `url_for()`.
- `url_for()` requires an active application context (and for blueprint routes, usually
  a request context or `SERVER_NAME` configured).
- We only pushed `app.app_context()`, which was insufficient.
- **Fix (Option B)**: Removed all reliance on `url_for` from the background worker.
  Introduced a pure helper `_build_processed_href()` that constructs the deterministic
  relative path:
  `/estimate-enhancer/uploads/processed_{filename}#page={N}`
  using the prefix from `registry.TOOLS`.
- `build_image_link_payload()` now uses the pure helper.
- The worker no longer receives or uses the Flask app object for URL construction.

### Problem: "Unable to build URLs outside an active request without 'SERVER_NAME'"
- **Symptom**: Same background processing path failed with a different but related
  Flask error about `SERVER_NAME`, `APPLICATION_ROOT`, and `PREFERRED_URL_SCHEME`.
- **Why it appeared**: Even with an app context, Flask's URL building for non-external
  routes still needs request context or explicit server name configuration when there
  is no active request.
- The project deliberately does **not** set `SERVER_NAME` (supports localhost, arbitrary
  LAN IPs, different ports, and droplet deployments).
- **Fix**: Same as above — pure relative URL construction. No `url_for` calls from
  non-request threads.

### Related anti-patterns to avoid
- Never call `url_for` (especially for blueprint routes) from daemon threads,
  background workers, or any code path that is not inside a real Flask request or a
  properly created `test_request_context()`.
- If you ever need Flask URL helpers outside a request, prefer building them from
  configuration or registry data (as done for image links) or explicitly create a
  request context only for that small scope.
- Do not rely on setting `SERVER_NAME` globally just to make background jobs work;
  it makes the app less portable.

## Estimate Enhancer Large Photo Jobs on Low-Resource Web Servers

### Problem: Crashes / OOM with 50+ photo pages on droplet
- **Symptom**: Jobs that worked locally would hang or crash on the production droplet
  when the estimate had many photo pages (50+).
- Suspected causes: multiple full materializations of the PDF (pypdf copy + fitz opens
  + fork subprocess + final insert_pdf of attachments) + high memory during flattening.
- **Mitigations implemented**:
  - Web-only configurable photo page cap (`enhancer_max_photo_pages`, default 50,
    editable in Admin, shown in the UI as a muted note with the limit value).
  - Warning only (never hard block on web).
  - Background processing + polling so the HTTP request returns immediately.
  - Coarse progress stages visible to the user.
  - psutil RSS logging at start / before fork / before & after final save.
  - Configurable fork subprocess timeout (`ENHANCER_FORK_TIMEOUT`, default 180s).
- The cap and background work together to make large jobs more survivable on small
  droplets while still allowing the job to run.

## Authentication & Web Mode

### Problem: "not in web mode" when trying to create tokens
- **Symptom**: On the hosting machine, going to Admin showed no token UI, or API calls
  returned "Not in web mode".
- **Cause**: Token auth, roles, and the Admin token section are entirely gated behind
  `TOOLBOX_WEB_MODE=1`. In normal desktop/local mode, everyone is treated as an
  employee with full access and there are no tokens.
- Additionally, the server was often bound only to 127.0.0.1, so even with WEB_MODE,
  other machines on the LAN could not reach it.
- **Correct usage**:
  ```
  TOOLBOX_WEB_MODE=1 \
  TOOLBOX_HOST=0.0.0.0 \
  python3 run/standalone.py
  ```
- First login with any value bootstraps an employee token.
- After that, only valid tokens work.

### Problem: Login / tokens work locally but not from other LAN machines
- Caused by default bind (`127.0.0.1`) + missing WEB_MODE.
- Always use `TOOLBOX_HOST=0.0.0.0` when testing web mode from other devices.

## Server Runtime Behavior

### Problem: Changes to .py files not picked up
- **Symptom**: Edit a route or logic file, reload the browser, see old behavior.
- **Cause**: The production server is started with `waitress` and `use_reloader=False`.
  waitress does not auto-reload Python code.
- **Rule**: After any `.py` change, you **must** restart the server (Ctrl+C and relaunch).
- Templates, CSS, and JS usually hot-reload (still do a hard refresh in the browser:
  Ctrl+Shift+R).

## UI State for Enhancer Log Button

### Problem: "View Enhancer Log" button disappeared after successful processing
- **Symptom**: The log button (web only) was visible after Analyze and during processing,
  but vanished once the job completed successfully.
- **Cause**: The button lives inside `#processSection` (Enhance step). After success
  the code shows `#downloadSection` (Deliver step) and never re-shows the process
  section or the log button.
- On error paths the process section was sometimes re-shown, making the button appear
  only on failure.
- This was a UI placement / state machine decision, not a server-side "failure only"
  gate.
- Documented so future changes to the log button location or persistence are deliberate.

## Packaging & Dependencies

### psutil
- Added as a regular dependency so RSS logging in the enhancer worker is always
  available on web deployments.
- Previously it was best-effort (`try: import psutil`).

### Fork timeout
- Previously hardcoded to 120 seconds inside `process_with_fork`.
- Made configurable via `ENHANCER_FORK_TIMEOUT` (default 180) so different
  deployments can tune it.

### AppImage builds but does not launch

- **Symptom** (reported after v0.3.0): `./run/build-appimage.sh` (and the GitHub
  Actions build on `v*` tags) completes successfully and produces
  `Sherwood_Toolbox-<ver>-x86_64.AppImage`. After `chmod +x` and running it,
  nothing happens or it fails to start the desktop shell.
- The containerized web build and .deb paths were the focus of the v0.3.0 release;
  the AppImage was not re-validated on target hardware immediately after the web
  deployment round.
- Common external causes for "build green, won't run":
  - Missing runtime libs or FUSE on the target (especially Fedora 43 + AMD).
  - The AppRun / desktop integration or pywebview GTK bits not matching the host.
  - Architecture / glibc mismatch between the Ubuntu 22.04 CI runner and the
    user's distro.
- Workarounds historically used: `LIBGL_ALWAYS_SOFTWARE=1`, forcing X11,
  ensuring `fuse` + `libfuse2` (or fuse3 equivalent) are present.
- Recommendation: After any AppImage-producing change, download the artifact and
  smoke-test launch on at least one target (ideally the Fedora/AMD case the
  build script tries to support).

**Fat GTK AppImage (post this change):** `run/build-appimage.sh` now produces a
self-contained ("fat") image that bundles WebKitGTK + GTK + gi from the build
host using linuxdeploy + linuxdeploy-plugin-gtk + a clean venv. A
`BUILD_INFO.txt` (inside) and `.buildinfo` sidecar record the exact Python and
WebKitGTK versions used. Runtime no longer requires webkit2gtk4.1/python3-gobject
on the target for the core stack (only FUSE or `--appimage-extract-and-run` plus
basic graphics). The AppRun still applies the AMD workarounds. The build leaves
`AppDir` behind for inspection and hard-fails the post-build gi/WebKit2 import
test if bundling is broken. The GitHub CI workflow still produces a thin
Ubuntu-22.04 (WebKit 4.0) image; local fat builds on the target distro are
recommended for AMD/Fedora 43.

See also `run/build-appimage.sh` and `.github/workflows/build-appimage.yml`.

## Deployment Notes (Droplet / Web)

- Always mount a persistent volume for `TOOLBOX_DATA_DIR` (contains uploads,
  `web_tokens.json`, `web_limits.json`).
- CRM credentials (`crm.ini`) are still at the standard user path unless explicitly
  mounted.
- Reverse proxy must forward to the container on 8777 and terminate TLS.
- On first start with `WEB_MODE=1`, anyone who hits `/login` with any value becomes
  the first employee. After that, control it via Admin.
- The new enhancer photo page limit and background job behavior are the main things
  that changed for web stability on small droplets.

### nginx `client_max_body_size` too low (413 "Content Too Large")

- **Symptom (real deploy)**: Estimate Enhancer "Server returned 413" on Analyze PDF.
  Photo Report "Error: Generation failed." with 413 in the network tab, even with only
  a few photos under the web limits.
- **Cause**: nginx default (or previous site config) had a tiny `client_max_body_size`
  (often 1m). The reverse proxy rejected the request body before it reached the app.
  Photo Report sends all selected images in one POST. Enhancer sends the full PDF.
- **Fix**: In the server block for the toolbox domain:
  ```nginx
  client_max_body_size 100m;   # or at least 60m
  ```
  The app still enforces its own limits (`WEB_ENHANCER_MAX_MB`, `WEB_PHOTO_MAX_*`,
  global `MAX_CONTENT_LENGTH`).
- **Lesson**: Always set an explicit high `client_max_body_size` for any domain
  serving heavy upload tools. Do not rely on nginx defaults.

### Shared host nginx + certbot / reloads broke other sites (e.g. dashboard cert)

- **Symptom (real deploy)**: After the toolbox deploy, the active dashboard domain
  (`dashboard.publicadjustermidwest.com`, previously `dashboard.vanguardadj.com`)
  started returning the wrong certificate or 403, even though it "worked before".
- **Causes**:
  - Host systemd nginx is shared by multiple sites. The deploy performed repeated
    `systemctl reload/start`, `certbot --nginx`, site file edits, and `pkill nginx`.
    This left nginx in inconsistent states (stale `/run/nginx.pid`, "not active",
    failed starts, wrong server block winning).
  - DNS for the old dashboard name still pointed at a Cloudways IP returning a
    `*.cloudwaysapps.com` certificate. Observers saw the "wrong cert".
  - Old site symlinks (e.g. `dashboard.vanguardadj.com`) could still be enabled and
    interfere.
- **Fixes applied**:
  - Re-wrote the exact site file for the *current* dashboard domain with its own
    Let's Encrypt cert paths.
  - Removed stale symlinks for old dashboard names.
  - Hard-clean restart of host nginx:
    ```bash
    pkill -9 nginx || true
    rm -f /run/nginx.pid /var/run/nginx.pid
    systemctl restart nginx
    ```
  - Verified DNS for each public name actually points at the droplet IP.
- **Lesson**: On a shared-host nginx (not just an isolated "web" docker network),
  every nginx or certbot change is high-risk for other TLS sites. Treat it like
  editing a global config. Test other domains after any change. Prefer per-domain
  site files and explicit `server_name` matches.

### Data directory ownership (uid 1000)

- **Symptom**: Container could not write uploads / tokens / limits, or the dir was
  inaccessible inside the container.
- **Cause**: `mkdir /opt/sherwood-toolbox/data` (or similar) was done as the login
  user (ubuntu/root). The Dockerfile creates a non-root user `toolbox` with uid 1000
  and runs as that user. The bind mount inherited the wrong owner.
- **Fix**:
  ```bash
  mkdir -p /opt/sherwood-toolbox/data
  chown -R 1000:1000 /opt/sherwood-toolbox/data
  ```
- **Lesson**: Always `chown` bind-mount paths to the uid the container actually runs as
  (see `useradd -m -u 1000 toolbox` + `USER 1000` in the Dockerfile).

### Dockerfile from released tag was not web-ready

- **Symptom**: On the first real droplet deploy using `git checkout v0.3.0`, the
  container built but the app failed to start (missing flask, PyMuPDF/fitz, etc.).
- **Causes**:
  - `pip install --no-deps -e .` in the tag skipped all runtime dependencies.
  - `python:3.11-slim` image lacked PyMuPDF runtime libraries (libgl1, libglib2.0-0,
    libx11-6, libxext6, libxrender1, libsm6).
- **Fixes applied on droplet**:
  - Patched the checked-out Dockerfile:
    - Changed to `pip install -e .` (no `--no-deps`).
    - Added the missing apt packages.
  - Rebuilt.
- **Current state**: Main branch + Dockerfile in the repo now include the runtime
  libs and do not use `--no-deps`. Tags may still be "desktop-first".
- **Lesson**: Treat the first web deploy of a tag as a patching exercise. Verify
  that `python -c "import flask, fitz, bs4, psutil, PIL, pypdf, reportlab, requests"`
  succeeds inside the built image before going live.

### Host nginx left in broken state multiple times

- Symptom: "nginx.service is not active", "invalid PID number in /run/nginx.pid",
  reloads doing nothing.
- Cause: Mix of `systemctl reload`, `certbot --nginx`, manual `pkill`, and partial
  starts during troubleshooting.
- Reliable recovery:
  ```bash
  pkill -9 nginx || true
  rm -f /run/nginx.pid /var/run/nginx.pid
  systemctl restart nginx
  ```
- Lesson: On a machine where nginx is managed as a systemd service, prefer
  `systemctl restart` + `nginx -t` after invasive changes. Avoid mixing certbot
  and manual pkill without cleaning the pid file.

---

If you are about to make changes in any of the areas above (especially background
jobs + Flask context, web limits, auth bootstrap, or long-running enhancer
processing), re-read the relevant sections of this document first.
