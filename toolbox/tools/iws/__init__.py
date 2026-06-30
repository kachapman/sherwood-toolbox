"""Ice and Water Shield calculator: a static, client-side tool. The Python side
only serves the page; all math runs in static/js/calculator.js.
Edit the coverage math there, not here."""
from flask import Blueprint, render_template

bp = Blueprint(
    "iws",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="static",
)


@bp.route("/")
def index():
    return render_template("iws.html")
