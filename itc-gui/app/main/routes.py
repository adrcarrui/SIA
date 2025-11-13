from flask import render_template, session
from flask_login import login_required
from . import bp

@bp.route("/")
@login_required
def index():
    return render_template("index.html", page_title="Inicio")
