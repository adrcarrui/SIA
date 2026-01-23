# app/routes_auth.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from .models import db, User
from flask_bcrypt import Bcrypt
from werkzeug.urls import url_parse
from flask import current_app as app

auth_bp = Blueprint("auth", __name__, template_folder="templates")
bcrypt = Bcrypt()

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()
        if not user:
            flash("Incorrect username or password", "danger")
            return render_template("auth/login.html"), 401

        if not bcrypt.check_password_hash(user.password_hash, password):
            flash("Incorrect username or password", "danger")
            return render_template("auth/login.html"), 401

        login_user(user, remember=bool(request.form.get("remember")))
        flash(f"Welcome, {user.name or user.username}!", "success")

        # redirecciÃ³n segura (param next=?)
        next_page = request.args.get("next")
        if not next_page or url_parse(next_page).netloc != "":
            next_page = url_for("home")  # cambia por tu endpoint principal
        return redirect(next_page)

    return render_template("auth/login.html")

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Session closed.", "info")
    return redirect(url_for("auth.login"))
