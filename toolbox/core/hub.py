"""The core blueprint: the hub landing page plus the shared CRM credential
route. Edit the tool grid in hub.html; the credential save logic is below."""
from flask import Blueprint, jsonify, render_template, request

from ..config import Config
from ..registry import TOOLS

bp = Blueprint("core", __name__, template_folder="templates")


@bp.route("/")
def index():
    return render_template("hub.html", tools=TOOLS)


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
