# app/auth/routes.py
from flask import render_template, request, redirect, url_for, flash, session, jsonify
from flask_login import login_user, logout_user, current_user
from . import bp
from app.db import SessionLocal
import app.models as models
import bcrypt
from urllib.parse import urlparse
from app.nfc.acr122 import ACR122
from smartcard.Exceptions import NoCardException
from app.db import SessionLocal

# === NFC: imports y flag de disponibilidad ===
try:
    NFC_AVAILABLE = True
except Exception:
    # Si falla la importación (no hay lib, no hay lector, etc.)
    ACR122 = None

    class NoCardException(Exception):
        pass

    NFC_AVAILABLE = False

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
    if not NFC_AVAILABLE:
        return jsonify({
            "success": False,
            "reason": "nfc_unavailable",
            "error": "NFC no disponible en el servidor."
        })

    # 1) Leer UID de la tarjeta
    try:
        reader = ACR122()
        info = reader.get_uid()
        uid = info["uid_hex"]   # "04AABBCCDD"
    except NoCardException:
        # No hay tarjeta ahora mismo: no es un “error”, solo no hay nada que hacer
        return jsonify({
            "success": False,
            "reason": "no_card"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "reason": "reader_error",
            "error": f"Error del lector NFC: {e}"
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

        return jsonify({
            "success": True,
            "next": url_for("main.index"),
            "username": user.username,
        })
    finally:
        db.close()


@bp.route("/read-uid", methods=["POST"])
def read_uid_once():
    """
    Intentar leer una tarjeta NFC una vez y devolver el UID en JSON.
    No modifica BD. El front rellenará el campo uid del formulario.
    """
    if not NFC_AVAILABLE:
        return jsonify({"success": False, "error": "NFC no disponible", "reason": "nfc_unavailable"})

    try:
        reader = ACR122()
        info = reader.get_uid()           # puede lanzar NoCardException
        uid = info.get("uid_hex", "").upper()
    except NoCardException:
        return jsonify({"success": False, "error": "No se detectó tarjeta", "reason": "no_card"})
    except Exception as e:
        return jsonify({"success": False, "error": f"Error lector: {e}", "reason": "reader_error"})

    if not uid:
        return jsonify({"success": False, "error": "UID vacío", "reason": "no_uid"})

    return jsonify({"success": True, "uid": uid})