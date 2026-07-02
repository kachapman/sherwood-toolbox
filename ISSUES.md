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

---

If you are about to make changes in any of the areas above (especially background
jobs + Flask context, web limits, auth bootstrap, or long-running enhancer
processing), re-read the relevant sections of this document first.
