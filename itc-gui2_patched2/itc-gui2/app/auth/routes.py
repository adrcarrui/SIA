# app/auth/routes.py
from flask import render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_user, logout_user, current_user
from . import bp
from app.db import SessionLocal
import app.models as models
import bcrypt
from urllib.parse import urlparse
"""Auth routes.

NOTE about NFC login:
Historically, the server tried to read the PC/SC reader directly.
That breaks multi-PC usage because all clients end up polling the same reader.

New model (Option 1): each client PC runs a small local agent that reads its own
PC/SC reader and sends the UID to this endpoint.
"""

from app.scripts import log_movement


def _normalize_uid(uid: str) -> str:
    """Normalize UID for DB lookup.

    Accepts formats like:
      - "04AABBCCDD"
      - "04:AA:BB:CC:DD"
      - "04 AA BB CC DD"
    """
    if not uid:
        return ""
    return "".join(ch for ch in str(uid).strip() if ch.isalnum()).upper()

@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "")

        db = SessionLocal()
        try:
            user = db.query(models.User).filter(models.User.username == username).first()
            if not user:
                error = "Usuario o contraseña incorrectos"
            else:
                pw_ok = False
                # --- Case A: password_hash looks like bcrypt (starts with $2b$, $2y$, $2a$ etc.)
                ph = user.password_hash or ""
                if isinstance(ph, str) and ph.startswith("$2"):
                    try:
                        pw_ok = bcrypt.checkpw(password.encode("utf-8"), ph.encode("utf-8"))
                    except Exception:
                        pw_ok = False
                else:
                    # --- Case B: legacy plaintext password stored in password_hash
                    # direct compare (insecure but we treat as migration path)
                    try:
                        if password == ph:
                            pw_ok = True
                            # Re-hash now and store securely
                            new_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                            user.password_hash = new_hash
                            db.add(user)
                            db.commit()
                    except Exception:
                        pw_ok = False

                if pw_ok:
                    if not user.active:
                        error= "Inactive user. Contact and administrator."
                    else:
                        # login_user espera un objeto que implemente get_id() (tu modelo SQLAlchemy lo hace)
                        login_user(user, remember=bool(request.form.get("remember")))
                        session["reset_sidebar"] = True
                        return redirect(url_for("main.index"))
                else:
                    error = "Usuario o contraseña incorrectos"
        finally:
            db.close()

    return render_template(
        "auth/login.html",
        page_title="Login",
        hide_sidebar=True,
        error=error,
        hide_topbar=True,
    )

@bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

@bp.route("/nfc-login", methods=["POST"])
def nfc_login():
    """NFC login endpoint.

    Expected flow:
      - The browser calls a *local* agent on the client PC (127.0.0.1) to read UID.
      - The browser sends the UID here (JSON: {"uid": "..."}).
      - Server validates UID against DB and creates the session.

    This makes multi-PC usage safe because each PC uses its own reader.
    """

    payload = request.get_json(silent=True) or {}
    uid_raw = payload.get("uid") or request.form.get("uid") or request.args.get("uid")
    uid = _normalize_uid(uid_raw)

    if not uid:
        return jsonify({
            "success": False,
            "reason": "missing_uid",
            "error": "No UID received from client."
        })

    # 2) Buscar usuario por UID
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.uid == uid).first()

        if not user:
            return jsonify({
                "success": False,
                "reason": "unknown_uid",
                "error": "Tarjeta no asociada a ningún usuario."
            })
        
        if not user.active:
            return jsonify({
                "success": False,
                "reason": "inactive_user",
                "error": "Usuario inactivo, acceso no permitido."
            })

        # 3) Login
        login_user(user)
        session["reset_sidebar"] = True

        # movement log (best effort)
        try:
            db.flush()
            log_movement(
                db,
                user_id=user.id,
                entity_type="user",
                entity_id=user.id,
                action="login",
                before_data=None,
                after_data=None,
                description=f"User {user.username} logged in via NFC (client UID) from {request.remote_addr}",
                success=True,
                user_agent=request.user_agent.string,
            )
            db.commit()
        except Exception:
            db.rollback()

        return jsonify({
            "success": True,
            "next": url_for("main.index"),
            "username": user.username,
        })
    finally:
        db.close()


@bp.route("/read-uid", methods=["POST"])
def read_uid_once():
    """Compatibility endpoint.

    Previously the server read the NFC reader directly to fill forms.
    With the distributed-reader model, the client should call its local agent
    and send the UID here.
    """
    payload = request.get_json(silent=True) or {}
    uid = _normalize_uid(payload.get("uid") or request.form.get("uid"))
    if not uid:
        return jsonify({"success": False, "error": "No UID received", "reason": "missing_uid"})
    return jsonify({"success": True, "uid": uid})