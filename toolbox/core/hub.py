"""The core blueprint: the hub landing page plus the shared CRM credential
route. Edit the tool grid in hub.html; the credential save logic is below."""
import configparser
import json
import os
import time
from pathlib import Path

from flask import Blueprint, jsonify, make_response, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from ..config import Config
from ..registry import TOOLS
from . import auth as core_auth

bp = Blueprint("core", __name__, template_folder="templates")

UNIFIED_CRM_DIR = Path.home() / ".config" / "photo_report_generator"
UNIFIED_CRM_PATH = UNIFIED_CRM_DIR / "crm.ini"

# Web limits storage (visible to users in tools, editable in Admin)
WEB_LIMITS_FILE = Config.DATA_DIR / "web_limits.json"

def _load_web_limits():
    defaults = {
        "photo_max_count": Config.WEB_PHOTO_MAX_COUNT,
        "photo_max_mb_per_file": Config.WEB_PHOTO_MAX_MB_PER_FILE,
        "enhancer_max_mb": Config.WEB_ENHANCER_MAX_MB,
        "enhancer_max_photo_pages": Config.WEB_ENHANCER_MAX_PHOTO_PAGES,
    }
    try:
        if WEB_LIMITS_FILE.exists():
            data = json.loads(WEB_LIMITS_FILE.read_text())
            for k in defaults:
                if k in data:
                    defaults[k] = int(data[k])
    except Exception:
        pass
    return defaults

def _save_web_limits(limits):
    try:
        Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        WEB_LIMITS_FILE.write_text(json.dumps(limits, indent=2))
    except Exception:
        pass

# Allowed dirs for file manager (popouts from sidebar buttons)
# Code Docs now uses the configurable writable location (TOOLBOX_ATTACHMENTS_DIR / Config.ATTACHMENTS_DIR).
# Packaged IRC references remain in toolbox/tools/estimate_enhancer/attachments (read-only for Enhancer).
ARCHIVE_DIR = Config.UPLOAD_DIR

def _ensure_code_docs_seeded():
    """Silently copy packaged IRC reference PDFs into the writable Code Docs dir if missing.
    Idempotent: never overwrites user-added files. Best-effort, no output."""
    target = Path(Config.ATTACHMENTS_DIR)
    target.mkdir(parents=True, exist_ok=True)
    src = None
    try:
        # Import inside the function to avoid any import-time cycles.
        # enhancer.routes only imports _load_web_limits from this module.
        from ..tools.estimate_enhancer.routes import ATTACHMENTS_DIR as _pkg_src
        src = Path(_pkg_src)
    except Exception:
        # Fallback to the location relative to this file (works in source tree and installed packages).
        src = Path(__file__).resolve().parent.parent / "tools" / "estimate_enhancer" / "attachments"
    if not src or not src.exists():
        return
    try:
        import shutil
        for pdf in sorted(src.glob("*.pdf")):
            dst = target / pdf.name
            if not dst.exists():
                shutil.copy2(pdf, dst)
    except Exception:
        pass  # silent best effort

# Public alias for startup seeding (called from app.py after ensure_dirs).
ensure_code_docs_seeded = _ensure_code_docs_seeded

def _resolve_dir(key):
    if key == "code_docs":
        _ensure_code_docs_seeded()
        d = Path(Config.ATTACHMENTS_DIR)
    elif key == "archive":
        d = ARCHIVE_DIR
    else:
        return None
    d.mkdir(parents=True, exist_ok=True)
    return d

def _safe_path(base, name):
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    p = (base / name).resolve()
    try:
        if not str(p).startswith(str(base.resolve())):
            return None
    except Exception:
        return None
    return p

@bp.route("/files")
def files_list():
    key = request.args.get("dir", "")
    if Config.WEB_MODE and not core_auth.is_employee(request):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    base = _resolve_dir(key)
    if not base:
        return jsonify({"error": "Invalid dir"}), 400
    items = []
    try:
        for f in sorted(base.iterdir()):
            if f.is_file():
                st = f.stat()
                items.append({
                    "name": f.name,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                })
    except Exception:
        pass
    return jsonify({"dir": key, "items": items})

@bp.route("/files/delete", methods=["POST"])
def files_delete():
    key = request.form.get("dir", "")
    name = request.form.get("name", "")
    if Config.WEB_MODE and not core_auth.is_employee(request):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    base = _resolve_dir(key)
    p = _safe_path(base, name)
    if not p or not p.exists():
        return jsonify({"ok": False, "error": "Not found"}), 404
    try:
        p.unlink()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})

@bp.route("/files/clear-older", methods=["POST"])
def files_clear_older():
    key = request.form.get("dir", "")
    if Config.WEB_MODE and not core_auth.is_employee(request):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    try:
        hours = int(request.form.get("older_than_hours", "24"))
    except Exception:
        hours = 24
    base = _resolve_dir(key)
    if not base or key != "archive":
        return jsonify({"ok": False, "error": "Only archive supports clear-older"}), 400
    cutoff = time.time() - (hours * 3600)
    removed = 0
    errors = []
    try:
        for f in list(base.iterdir()):
            if f.is_file():
                if f.stat().st_mtime < cutoff:
                    try:
                        f.unlink()
                        removed += 1
                    except Exception as e:
                        errors.append(f.name)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "removed": removed, "errors": errors})

@bp.route("/files/upload", methods=["POST"])
def files_upload():
    key = request.args.get("dir", "") or request.form.get("dir", "")
    if Config.WEB_MODE and not core_auth.is_employee(request):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    base = _resolve_dir(key)
    if not base or key != "code_docs":
        return jsonify({"ok": False, "error": "Uploads only allowed to Code Docs"}), 400
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "No file"}), 400
    name = secure_filename(f.filename)
    if not name:
        return jsonify({"ok": False, "error": "Invalid filename"}), 400
    dest = base / name
    try:
        f.save(str(dest))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "name": name})


def _get_current_crm_user():
    """Return the current CRM username (full) or None if not configured."""
    try:
        if not UNIFIED_CRM_PATH.exists():
            return None
        cfg = configparser.ConfigParser()
        cfg.read(UNIFIED_CRM_PATH)
        if "crm" not in cfg:
            return None
        u = (cfg["crm"].get("username", "") or "").strip()
        return u or None
    except Exception:
        return None


@bp.route("/")
def index():
    # Do not override "tools" — the context processor in app.py supplies
    # the role-filtered list (employees see all, customers see only Enhancer + IWS).
    return render_template("hub.html")


@bp.route("/admin")
def admin():
    current_user = _get_current_crm_user()
    limits = _load_web_limits()
    tokens = core_auth.list_tokens() if core_auth.is_employee(request) else []
    return render_template("admin.html", current_crm_user=current_user, limits=limits, tokens=tokens, minimal_shell=False)


@bp.route("/admin/crm", methods=["POST"])
def admin_crm():
    """Test and save (or clear) CRM credentials from the Admin page.
    Always available in local/desktop mode. In web mode this will be
    restricted to employees via token auth (added separately)."""
    action = (request.form.get("action") or "").strip().lower()
    if action == "clear":
        try:
            from restoration_common import clear_crm_credentials
            clear_crm_credentials()
        except Exception:
            # Best effort: remove section directly
            if UNIFIED_CRM_PATH.exists():
                cfg = configparser.ConfigParser()
                cfg.read(UNIFIED_CRM_PATH)
                if "crm" in cfg:
                    cfg.remove_section("crm")
                    with open(UNIFIED_CRM_PATH, "w") as f:
                        cfg.write(f)
        return jsonify({"ok": True})

    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    if not username or not password:
        return jsonify({"ok": False, "error": "Enter both a username and password."}), 400
    if Config.OFFLINE:
        return jsonify({"ok": False,
                        "error": "Offline mode: cannot verify CRM credentials right now."}), 400
    try:
        from restoration_common import crm_login, save_crm_credentials
    except Exception:
        return jsonify({"ok": False, "error": "CRM support is not available in this build."}), 500
    try:
        crm_login(username, password)
    except Exception as e:
        return jsonify({"ok": False,
                        "error": "Invalid CRM login."}), 400
    save_crm_credentials(username, password)
    return jsonify({"ok": True})


@bp.route("/admin/limits", methods=["POST"])
def admin_limits():
    """Save web limits (visible to all users in the tools, editable here)."""
    try:
        limits = {
            "photo_max_count": int(request.form.get("photo_max_count", "10")),
            "photo_max_mb_per_file": int(request.form.get("photo_max_mb_per_file", "10")),
            "enhancer_max_mb": int(request.form.get("enhancer_max_mb", "15")),
            "enhancer_max_photo_pages": int(request.form.get("enhancer_max_photo_pages", "50")),
        }
    except Exception:
        return jsonify({"ok": False, "error": "Invalid numbers."}), 400
    _save_web_limits(limits)
    return jsonify({"ok": True})


@bp.route("/crm/credentials", methods=["POST"])
def crm_credentials():
    """Save the CRM login for this machine after verifying it. Used by the
    credential form shown when no crm.ini exists (e.g. a freshly installed
    machine). Localhost-only, like the rest of the app."""
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    if not username or not password:
        return jsonify({"ok": False, "error": "Enter both a username and password."}), 400
    if Config.OFFLINE:
        return jsonify({"ok": False,
                        "error": "Offline mode: cannot verify CRM credentials right now."}), 400
    try:
        from restoration_common import crm_login, save_crm_credentials
    except Exception:
        return jsonify({"ok": False, "error": "CRM support is not available in this build."}), 500
    try:
        crm_login(username, password)  # verify before saving
    except Exception as e:
        return jsonify({"ok": False,
                        "error": f"Could not sign in to the CRM: {e}"}), 400
    save_crm_credentials(username, password)
    return jsonify({"ok": True})


# --- CRM deal title search (only inside Photo Report and Documents) ---

def _crm_base_url():
    try:
        from restoration_common.paths import CRM_BASE_URL
        return CRM_BASE_URL.rstrip("/")
    except Exception:
        return "https://office.publicadjustermidwest.com"


@bp.route("/crm/deal-search", methods=["POST"])
def crm_deal_search():
    """Search open deals by title. Returns {id, title} list.
    Shows concise "CRM Offline" on any failure.
    """
    if Config.OFFLINE:
        return jsonify({"ok": False, "error": "CRM Offline"}), 503
    title = (request.form.get("title") or "").strip()
    if not title:
        return jsonify({"ok": True, "deals": []})

    try:
        from restoration_common import crm_login, load_crm_credentials
    except Exception:
        return jsonify({"ok": False, "error": "CRM Offline"}), 503

    try:
        username, password = load_crm_credentials()
        session = crm_login(username, password)
    except Exception:
        return jsonify({"ok": False, "error": "CRM Offline"}), 503

    base = _crm_base_url()
    params = {
        "filterValue": title,
        "count": "10",
        "startIndex": "0",
        "sortBy": "date_created",
        "sortOrder": "descending",
    }
    try:
        resp = session.get(f"{base}/api/2.0/crm/opportunity/filter", params=params, timeout=20)
        if resp.status_code != 200:
            return jsonify({"ok": False, "error": "CRM Offline"}), 503
        data = resp.json()
        raw = data.get("response") or []
        deals = []
        for d in (raw or []):
            try:
                did = d.get("id") or d.get("ID")
                dtitle = (d.get("title") or d.get("Title") or "").strip()
                if did and dtitle:
                    deals.append({"id": did, "title": dtitle})
            except Exception:
                continue
        return jsonify({"ok": True, "deals": deals})
    except Exception:
        return jsonify({"ok": False, "error": "CRM Offline"}), 503


@bp.route("/crm/deal-fetch", methods=["POST"])
def crm_deal_fetch():
    """Given a deal id (from title search), fetch structured opportunity data
    so the form populates the same fields as a manual CRM job URL:
    customer_name (from title), claim_number ("Claim #"), job_location ("Address"),
    job_id ("CRM Job/ID").
    Falls back to Deals.aspx scrape only if needed.
    Concise "CRM Offline" on failure.
    """
    if Config.OFFLINE:
        return jsonify({"ok": False, "error": "CRM Offline"}), 503

    # Extremely defensive id extraction.
    # The client sometimes sends the opportunity id (e.g. "828") as a multipart form field.
    deal_id = ""
    try:
        if request.form:
            v = request.form.get("id") or request.form.get("deal_id")
            if v:
                deal_id = str(v).strip()
    except Exception:
        pass

    if not deal_id:
        try:
            if request.args:
                v = request.args.get("id") or request.args.get("deal_id")
                if v:
                    deal_id = str(v).strip()
        except Exception:
            pass

    if not deal_id and request.is_json:
        try:
            j = request.get_json(silent=True) or {}
            v = j.get("id") or j.get("dealId") or j.get("deal_id")
            if v:
                deal_id = str(v).strip()
        except Exception:
            pass

    # Last-resort raw body scan (helps if multipart parser had any issue)
    if not deal_id:
        try:
            raw = request.get_data(as_text=True) or ""
            import re
            m = re.search(r'name\s*=\s*["\']?id["\']?\s*(?:\r?\n|\s)+([^\s&"\']+)', raw, re.I)
            if m:
                deal_id = m.group(1).strip()
        except Exception:
            pass

    if not deal_id:
        # Return debug info so we can see what actually arrived
        try:
            form_keys = list(request.form.keys()) if request.form else []
        except Exception:
            form_keys = []
        print("DEAL-FETCH DEBUG: no id found. form=", dict(request.form), "args=", dict(request.args), "is_json=", request.is_json)
        return jsonify({
            "ok": False,
            "error": "Missing id",
            "debug_received_form_keys": form_keys,
            "debug_is_json": bool(request.is_json),
        }), 400

    print("DEAL-FETCH: using deal_id=", repr(deal_id))

    base = _crm_base_url()

    try:
        from restoration_common import crm_login, load_crm_credentials
    except Exception:
        return jsonify({"ok": False, "error": "CRM Offline"}), 503

    try:
        username, password = load_crm_credentials()
        session = crm_login(username, password)
    except Exception:
        return jsonify({"ok": False, "error": "CRM Offline"}), 503

    raw = {}
    info = {}

    # 1) Get basic opportunity (title etc.)
    try:
        r = session.get(f"{base}/api/2.0/crm/opportunity/{deal_id}", timeout=20)
        if r.status_code == 200:
            raw = r.json().get("response") or r.json() or {}
            title = (raw.get("title") or raw.get("Title") or "").strip()
            if title:
                info["customer_name"] = title
    except Exception:
        pass

    # 2) Pull custom fields using the dedicated endpoint (same pattern used by crm-kanban)
    #    GET /api/2.0/crm/opportunity/{id}/customfield  returns populated values for this opp.
    try:
        cf_r = session.get(f"{base}/api/2.0/crm/opportunity/{deal_id}/customfield", timeout=20)
        if cf_r.status_code == 200:
            cf_list = cf_r.json().get("response") or []
            for cf in (cf_list or []):
                try:
                    label = (cf.get("label") or cf.get("Label") or cf.get("fieldLabel") or "").strip().lower()
                    val = (cf.get("value") or cf.get("Value") or cf.get("fieldValue") or "").strip()
                    if not val:
                        continue
                    if "claim" in label and ("#" in label or "number" in label or label.endswith("claim")):
                        info.setdefault("claim_number", val)
                    if "address" in label:
                        info.setdefault("job_location", val)
                    if "crm job" in label or "job/id" in label or "job id" in label or "job#" in label:
                        info.setdefault("job_id", val)
                except Exception:
                    continue
    except Exception:
        pass

    # 3) Also inspect customFields if the single-opp response happens to embed them
    for cf in (raw.get("customFields") or raw.get("custom_fields") or []):
        try:
            label = (cf.get("label") or cf.get("Label") or "").strip().lower()
            val = (cf.get("value") or cf.get("Value") or "").strip()
            if not val:
                continue
            if "claim" in label and ("#" in label or "number" in label or label.endswith("claim")):
                info.setdefault("claim_number", val)
            if "address" in label:
                info.setdefault("job_location", val)
            if "crm job" in label or "job/id" in label or "job id" in label or "job#" in label:
                info.setdefault("job_id", val)
        except Exception:
            continue

    # 4) Top-level fallbacks (rare)
    if not info.get("claim_number"):
        for k in ("claim_number", "claimNumber", "claim #", "claim#"):
            if raw.get(k):
                info["claim_number"] = str(raw.get(k)).strip()
                break
    if not info.get("job_location"):
        for k in ("address", "job_location", "location"):
            if raw.get(k):
                info["job_location"] = " ".join(str(raw.get(k)).split())
                break
    if not info.get("job_id"):
        for k in ("crm_job_id", "crmJobId", "job_id", "jobId", "crm job/id"):
            if raw.get(k):
                info["job_id"] = str(raw.get(k)).strip()
                break

    # 5) Parse address like the manual URL path
    if info.get("job_location"):
        try:
            from ..core.crm import parse_address
            parsed = parse_address(info["job_location"])
            info["street"] = parsed.get("street", "")
            info["city_state_zip"] = parsed.get("city_state_zip", "")
            info["address"] = parsed
        except Exception:
            pass

    if info:
        return jsonify({"ok": True, "info": info})

    # 6) Last resort: scrape Deals.aspx (best effort)
    try:
        url = f"{base}/Products/CRM/Deals.aspx?id={deal_id}"
        from ..core.crm import fetch_job_info
        res = fetch_job_info(url)
        return jsonify(res)
    except Exception:
        return jsonify({"ok": False, "error": "CRM Offline"}), 503

    # Fallback to scraping the Deals.aspx page (best effort)
    try:
        url = f"{base}/Products/CRM/Deals.aspx?id={deal_id}"
        from ..core.crm import fetch_job_info
        res = fetch_job_info(url)
        return jsonify(res)
    except Exception:
        return jsonify({"ok": False, "error": "CRM Offline"}), 503


# --- Token auth routes (web mode only; desktop ignores) ---

@bp.route("/login", methods=["GET", "POST"])
def login():
    if not Config.WEB_MODE:
        return redirect(url_for("core.index"))
    error = None
    if request.method == "POST":
        token = (request.form.get("token") or "").strip()
        remember = bool(request.form.get("remember"))
        role = core_auth.validate(token)
        if role:
            resp = make_response(redirect(url_for("core.index")))
            core_auth.set_token_cookie(resp, token, remember=remember)
            return resp
        # bootstrap: if no tokens exist, the token they typed becomes the first employee token
        if not core_auth.has_any_tokens() and token:
            core_auth.bootstrap_accept(token, "bootstrap")
            resp = make_response(redirect(url_for("core.index")))
            core_auth.set_token_cookie(resp, token, remember=remember)
            return resp
        error = "Invalid token."
    # Show bootstrap hint if no tokens exist yet
    bootstrap = not core_auth.has_any_tokens()
    return render_template("login.html", bootstrap=bootstrap, error=error)


@bp.route("/logout")
def logout():
    resp = make_response(redirect(url_for("core.login")))
    core_auth.clear_token_cookie(resp)
    return resp


@bp.route("/admin/tokens", methods=["POST"])
def admin_tokens_create():
    """Employee-only: create a new token."""
    if not Config.WEB_MODE:
        return jsonify({"ok": False, "error": "Not in web mode"}), 400
    # bootstrap: allow first token creation without prior auth
    if core_auth.has_any_tokens() and not core_auth.is_employee(request):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    role = (request.form.get("role") or "customer").strip()
    label = (request.form.get("label") or "").strip()
    if role not in ("employee", "customer"):
        role = "customer"
    try:
        token = core_auth.create_token(role, label)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "token": token, "role": role})


@bp.route("/admin/tokens/revoke", methods=["POST"])
def admin_tokens_revoke():
    if not Config.WEB_MODE:
        return jsonify({"ok": False}), 400
    if not core_auth.is_employee(request):
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    tid = (request.form.get("id") or "").strip()
    if not tid:
        return jsonify({"ok": False, "error": "Missing id"}), 400
    ok = core_auth.revoke(tid)
    return jsonify({"ok": ok})
