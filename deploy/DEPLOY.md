# Web Deployment (Docker / VPS)

This documents running the **web version** of Sherwood Toolbox at a public or LAN URL (e.g. `https://tools.sherwoodestimates.com`) with token-based role auth.

**Desktop builds (`.deb`, AppImage) are completely unaffected.** They continue to run locally with full access and no web limits or login.

## Key behaviors in WEB_MODE

- `TOOLBOX_WEB_MODE=1` (or env) enables:
  - Token auth (cookie "remember me", or `?token=...` / form / Bearer).
  - Role-based UI:
    - **employee**: all 4 tools + sidebar (Code Docs, Archive, Admin).
    - **customer**: only Estimate Enhancer + IWS. Photo Report, Documents, folders, and Admin are hidden/redirected.
  - Web upload limits (visible to all, enforced server-side):
    - Photo Report: default max 10 photos, 10 MB per file (configurable in Admin).
    - Estimate Enhancer: default 15 MB PDF (configurable).
  - Global hard cap remains `MAX_CONTENT_LENGTH` (60 MB by default).
- No tokens yet → first successful `/login` with **any** value creates an employee token (bootstrap). After that, only valid tokens work.
- Tokens are stored (hashed) under `TOOLBOX_DATA_DIR` (default `~/.local/share/sherwood-toolbox/web_tokens.json`).
- CRM credentials (for Fetch + deal title search) are still the shared `~/.config/photo_report_generator/crm.ini` (or the unified path). They are used server-side for both roles.
- "Remember me" sets an httponly cookie for 30 days. Logout clears it.
- Admin → Access Tokens: employees can create/revoke employee or customer tokens. Plaintext is shown **only once** at creation.

Desktop/AppImage always behave as "employee" and ignore WEB_MODE, tokens, and web limits.

## Run locally for testing (browser)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install --no-deps -e vendor/restoration-common
pip install waitress   # recommended

# Web mode + LAN reachable (for testing from other machines on your network)
TOOLBOX_WEB_MODE=1 \
TOOLBOX_HOST=0.0.0.0 \
TOOLBOX_PORT=8777 \
.venv/bin/python run/standalone.py
```

- Local: http://127.0.0.1:8777/
- LAN (printed): http://192.168.x.x:8777/
- Go to `/login`, enter any token string → it becomes the first employee token.
- Open Admin (after login) to create more tokens and set web limits.
- **After editing any .py files you MUST restart the server (Ctrl+C then relaunch).** waitress is started with use_reloader=False and does not pick up Python changes at runtime.
- When testing customer vs employee tokens, logout or clear the `toolbox_token` cookie between attempts.

Firewall on the test box: `sudo ufw allow 8777/tcp` (or equivalent).

## Production (Digital Ocean droplet example)

Assumptions (matching the dashboard/kanban setup):
- Same external Docker network as the OnlyOffice/CRM/Kanban stack.
- No outbound SMTP (so no email flows).
- Reverse proxy (nginx) terminates TLS and forwards to the container.
- Persistent volume for `~/.local/share/sherwood-toolbox` (uploads, web_tokens.json, web_limits.json).
- Optional: mount CRM creds if you want to share the `crm.ini` with the host or another container.

### Minimal Dockerfile

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the app + vendored common package
COPY . /app
RUN pip install --no-deps -e . \
 && pip install --no-deps -e vendor/restoration-common \
 && pip install waitress gunicorn

# Non-root user (optional but recommended)
RUN useradd -m -u 1000 toolbox
USER 1000

# Data dir inside container (mount a volume here)
ENV TOOLBOX_DATA_DIR=/data \
    TOOLBOX_UPLOAD_DIR=/data/uploads \
    TOOLBOX_ATTACHMENTS_DIR=/data/attachments

EXPOSE 8777

# Use waitress by default (simple). Swap to gunicorn if you prefer.
CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=8777", "--threads=4", "--call", "toolbox.app:create_app"]
```

### Example docker-compose service (excerpt)

```yaml
services:
  sherwood-toolbox:
    build: .
    container_name: sherwood-toolbox
    restart: unless-stopped
    environment:
      - TOOLBOX_WEB_MODE=1
      - TOOLBOX_HOST=0.0.0.0
      - TOOLBOX_PORT=8777
      # Optional: pin data dir inside container
      - TOOLBOX_DATA_DIR=/data
      - TOOLBOX_UPLOAD_DIR=/data/uploads
      # CRM base if different from default
      # - TOOLBOX_CRM_BASE_URL=https://office.publicadjustermidwest.com
    volumes:
      - toolbox-data:/data
      # If sharing CRM creds with host/other container:
      # - /root/.config/photo_report_generator:/root/.config/photo_report_generator:ro
    networks:
      - web   # the external/shared network used by your nginx/kanban stack
    # If your nginx is in the same compose, use depends_on + the service name for proxying.
    # Expose only on the internal network; let the reverse proxy terminate TLS.

volumes:
  toolbox-data:

networks:
  web:
    external: true   # or define it in this file if you own the whole stack
```

### Nginx snippet (example)

```nginx
server {
    listen 443 ssl http2;
    server_name tools.sherwoodestimates.com;

    ssl_certificate     /etc/letsencrypt/live/tools.sherwoodestimates.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tools.sherwoodestimates.com/privkey.pem;

    client_max_body_size 60m;

    location / {
        proxy_pass http://sherwood-toolbox:8777;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Important for auth cookies + large uploads
        proxy_http_version 1.1;
        proxy_request_buffering off;
    }
}
```

### First run on the droplet

1. Build and start the container (with the shared network).
 2. Open `https://tools.sherwoodestimates.com/login`.
 3. Enter any string as the token → it becomes the first employee token (bootstrap).
 4. Log in, go to Admin, create additional tokens (employee/customer) and adjust web limits if needed.
 5. Give the plaintext token to the intended user. They use it once to log in; "Remember me" keeps them signed in.

**Note:** The canonical public hostname for this deployment is `tools.sherwoodestimates.com`. The previous `enhancer.sherwoodestimates.com` is no longer used.

### CRM credentials

- Use the Admin page (employee only) "CRM Credentials" section: Test & Save or Clear.
- This writes the shared `crm.ini` used for Fetch and deal title search in Photo Report and Documents.
- In web mode this is still a single shared login (not per-user).

### Limits and notices

- All web users see the current limits in the tool UIs (Photo Report and Enhancer).
- Limits are editable only in Admin (employee).
- Server enforces them in addition to the global 60 MB cap.
- On web, Photo Report "Max file size" input is disabled (static 10 MB guidance + server guard).
- Estimate Enhancer on web shows a muted note with the current photo page count and the configured cap (e.g. "62 / 50"). Processing is allowed but may be slow or fail on small servers.
- Enhancer jobs on web run in the background with status polling. A "View Enhancer Log" button (web only) is available after Analyze to open a live log modal.

### File manager (sidebar buttons)

- Code Docs and Archive buttons open a simple in-app modal (list / delete / upload for Code Docs; list / delete + 24h clear-all-older for Archive).
- These are employee-only (hidden for customers).
- Same behavior in desktop and web.

### Security notes

- Tokens are stored as SHA-256 hashes. Plaintext is only shown at creation time.
- Use HTTPS in production; consider setting the cookie `secure=True` if you control the entrypoint (see `toolbox/core/auth.py`).
- The app does not implement password auth or user accounts — only bearer-style tokens + remember cookie.
- No rate limiting or brute-force protection is built in; rely on your reverse proxy / firewall if needed.
- CRM credentials remain on disk in the standard location; protect the volume.

### Updating the web image

- Rebuild the image with the new code.
- `docker compose pull && docker compose up -d` (or equivalent).
- No database migrations. Tokens and limits persist via the mounted volume.

### Common env vars for web

- `TOOLBOX_WEB_MODE=1`
- `TOOLBOX_HOST=0.0.0.0`
- `TOOLBOX_PORT=8777`
- `TOOLBOX_DATA_DIR=/data` (inside container)
- `WEB_PHOTO_MAX_COUNT`, `WEB_PHOTO_MAX_MB_PER_FILE`, `WEB_ENHANCER_MAX_MB`, `WEB_ENHANCER_MAX_PHOTO_PAGES` (optional overrides; Admin page edits the persisted values)
- `ENHANCER_FORK_TIMEOUT` (seconds, optional; default 180)
- `TOOLBOX_CRM_BASE_URL` (if not the default)

### Health / smoke test

```bash
curl -I http://localhost:8777/          # inside the network
curl -I https://tools.sherwoodestimates.com/
```

Expect `200 OK` and the Sherwood hub (after login).

## Desktop vs Web differences (summary)

| Area                  | Desktop / AppImage          | Web (WEB_MODE=1)                     |
|-----------------------|-----------------------------|--------------------------------------|
| Auth                  | None (local only)           | Token + remember cookie              |
| Roles                 | Always full                 | employee (full) or customer (limited)|
| Tools visible         | All 4                       | All 4 or only Enhancer + IWS         |
| Sidebar folders/Admin | Visible                     | Employee only                        |
| Upload limits         | None (app-level)            | Web limits + notices + server guards (incl. enhancer photo pages) |
| CRM creds             | Per-machine                 | Shared (still via Admin)             |
| Downloads             | Native Save As (pywebview)  | Normal browser download              |

Keep the two deployment paths independent. Do not gate desktop features on web tokens or vice-versa.

### Estimate Enhancer on web (large jobs)
- Web deployments default to a 50 photo page cap (`enhancer_max_photo_pages`).
- After Analyze, the UI shows the actual photo page count and the limit.
- The cap is a warning only. The job will still be attempted.
- Jobs run in the background. The browser polls for status and shows coarse stages.
- Use the "View Enhancer Log" button (visible after Analyze on web) to open a popout modal with processing/fork output.
- If jobs are still too heavy, lower the cap in Admin or increase RAM/swap on the droplet.
- The fork timeout can be tuned per deployment with the `ENHANCER_FORK_TIMEOUT` environment variable (seconds).
