"""Application factory. Builds the Flask app, registers the hub plus one
blueprint per tool from the registry, and exposes tools + capabilities to
every template. Edit here to change app-wide wiring.
"""
import importlib

from flask import Blueprint, render_template

from .config import Config
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

    @app.context_processor
    def inject_globals():
        return {"tools": TOOLS, "caps": capabilities.detect()}

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
