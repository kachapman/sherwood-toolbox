# Production notes for sherwood-toolbox web deployment

See deploy/DEPLOY.md for the authoritative guide.

Quick references:
- Start command (dev/LAN test): TOOLBOX_WEB_MODE=1 TOOLBOX_HOST=0.0.0.0 TOOLBOX_PORT=8777 .venv/bin/python run/standalone.py
- Bootstrap: first /login with any token creates employee token.
- Tokens + limits live under TOOLBOX_DATA_DIR (web_tokens.json, web_limits.json).
- Desktop builds ignore WEB_MODE entirely.
- CRM creds are shared via the standard crm.ini path.

Hostname: tools.sherwoodestimates.com (enhancer.sherwoodestimates.com is retired).
