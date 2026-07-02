"""Application factory. Builds the Flask app, registers the hub plus one
blueprint per tool from the registry, and exposes tools + capabilities to
every template. Edit here to change app-wide wiring.
"""
import importlib

from flask import Blueprint, g, redirect, render_template, request, url_for

from .config import Config
from .core import auth as core_auth
from .core import capabilities, hub
from .registry import TOOLS


def _placeholder_blueprint(tool):
    """A stand-in blueprint for a tool that is not built yet, so its nav link
    and url_for(<id>.index) keep working."""
    bp = Blueprint(tool.id, __name__)

    @bp.route("/")
    def index():
        return render_template("placeholder.html", tool=tool)

    return bp


def _load_blueprint(tool):
    if not tool.ready:
        return _placeholder_blueprint(tool)
    module = importlib.import_module("toolbox.tools.%s" % tool.id)
    return module.bp


def create_app(config=Config):
    app = create_flask_app()
    app.config.from_object(config)
    config.ensure_dirs()

    app.register_blueprint(hub.bp)
    for tool in TOOLS:
        app.register_blueprint(_load_blueprint(tool), url_prefix=tool.url_prefix)

    @app.before_request
    def _auth_and_role():
        if not Config.WEB_MODE:
            g.role = "employee"
            g.caps = capabilities.detect("employee")
            return

        # web mode
        role = core_auth.get_current_role(request)
        g.role = role
        g.caps = capabilities.detect(role)

        # public endpoints
        if request.endpoint in ("core.login", "core.logout", "static"):
            return
        # bootstrap: first token creation allowed without auth (and login POST can accept any token to become first)
        if request.endpoint in ("core.admin_tokens_create", "core.admin_tokens_revoke") and not core_auth.has_any_tokens():
            return

        if not role:
            return redirect(url_for("core.login"))

        # customers: only Enhancer + IWS
        if role == "customer":
            if request.blueprint in ("photo_report", "documents"):
                return redirect(url_for("core.index"))
            if request.endpoint and "files" in request.endpoint:
                return redirect(url_for("core.index"))
            # Also block direct hub tile access if somehow rendered (belt-and-suspenders)
            if request.endpoint in ("photo_report.index", "documents.index"):
                return redirect(url_for("core.index"))

        # admin and token mgmt require employee
        if request.endpoint and (request.endpoint.startswith("core.admin") or "admin" in (request.endpoint or "")):
            if role != "employee":
                return redirect(url_for("core.index"))

    def _visible_tools(role):
        if role == "employee":
            return TOOLS
        return [t for t in TOOLS if t.id in ("estimate_enhancer", "iws")]

    @app.context_processor
    def inject_globals():
        role = getattr(g, "role", None) or "employee"
        caps = getattr(g, "caps", capabilities.detect(role))
        return {"tools": _visible_tools(role), "caps": caps}

    if Config.WEB_MODE:
        @app.after_request
        def _no_cache_html(response):
            if 'text/html' in (response.content_type or ''):
                response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'
            return response

    return app


def create_flask_app():
    from flask import Flask
    from pathlib import Path

    core = Path(__file__).resolve().parent / "core"
    return Flask(
        "toolbox",
        static_folder=str(core / "static"),
        static_url_path="/static",
        template_folder=str(core / "templates"),
    )
