# app/core/routes.py
from flask import Blueprint, render_template
from flask_login import login_required, current_user

core_bp = Blueprint("core", __name__, template_folder="../templates")

@core_bp.route("/")
@login_required
def home():
    # Pasa datos que ya usas en tu layout/base (p.ej. page_title)
    return render_template("home.html", page_title="Inicio", user=current_user)
