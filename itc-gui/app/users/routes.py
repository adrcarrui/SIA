from flask import render_template, request, redirect, url_for, flash,jsonify
from . import bp
from app.db import SessionLocal
import app.models as models
from sqlalchemy import or_
import bcrypt
from app.nfc.acr122 import ACR122
from smartcard.Exceptions import NoCardException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from flask_login import login_required, current_user
from app.scripts import log_movement

# === NFC: imports y flag de disponibilidad ===
try:
    NFC_AVAILABLE = True
except Exception:
    # Si falla la importación (no hay lib, no hay lector, etc.)
    ACR122 = None

    class NoCardException(Exception):
        pass

    NFC_AVAILABLE = False

@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    q = (request.args.get("q") or "").strip()

    db = SessionLocal()
    try:
        query = db.query(models.User)
        if q:
            like = f"%{q}%"
            query = query.filter(or_(
                models.User.name.ilike(like),
                models.User.surname.ilike(like),
                models.User.username.ilike(like),
                models.User.uid.ilike(like),
                models.User.email.ilike(like),
                models.User.role.ilike(like),
            ))

        total = query.count()
        users = (
            query.order_by(models.User.id.asc())   # 👈 orden por ID ascendente
                .offset((page-1)*per_page)
                .limit(per_page)
                .all()
        )

        return render_template(
            "users/index.html",
            users=users, q=q, page=page, per_page=per_page,
            has_prev=page>1, has_next=page*per_page<total
        )
    finally:
        db.close()

@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_user():
    if request.method == "POST":
        #id=request.form["id"].strip()
        name = request.form["name"].strip()
        surname = request.form.get("surname", "").strip()
        raw_uid= request.form["uid"].strip()
        username = request.form["username"].strip()
        password = request.form["password"]
        raw_email = request.form.get("email", "").strip()
        raw_role = request.form.get("role", "user").strip()
        active = bool(request.form.get("active"))


        # 🔒 Hashear la contraseña antes de guardarla
        hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        uid = raw_uid or None
        email = raw_email or None
        role = raw_role or 'User'
        db = SessionLocal()
        actor_id = getattr(current_user, "id", None)
        #db.add(u)
        #db.flush()  # para que u.id exista antes del commit

        try:
            new_user = models.User(
                name=name,
                surname=surname,
                uid=uid,
                username=username,
                password_hash=hashed_password,
                email=email,
                role=role,
                active=active,
            )
            db.add(new_user)
            #db.commit()
            db.flush()
            log_movement(
                    db,
                    user_id=actor_id,
                    entity_type="user",
                    entity_id=new_user.id,
                    action="create",
                    after_data={
                        "id": new_user.id,
                        "username": new_user.username,
                        "email": new_user.email,
                        "role": new_user.role,
                        "active": new_user.active,
                    },
                    description=f"User '{new_user.username}' created",
                    user_agent=request.user_agent.string,
                )
            db.commit()
            flash("✅ User created successfully", "success")
            return redirect(url_for("users.index"))
        except Exception as e:
            db.rollback()
            flash(f"❌ Error creating user: {e}", "danger")
        finally:
            db.close()

    return render_template("users/form.html", page_title="New user", user=None)

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import bcrypt

@bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def edit_user(user_id):
    db = SessionLocal()
    try:
        user = db.query(models.User).get(user_id)

        if not user:
            flash("User not found", "danger")
            return redirect(url_for("users.index"))

        if request.method == "POST":
            actor_id = getattr(current_user, "id", None)

            # Estado ANTES
            before_data = {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "active": user.active,
                "uid": user.uid,
            }

            user.name = request.form["name"]
            user.surname = request.form.get("surname", "")

            # UID saneado
            raw_uid = (request.form.get("uid") or "").strip()
            if raw_uid == "" or raw_uid.lower() in ("none", "null"):
                user.uid = None
            else:
                user.uid = raw_uid

            user.username = request.form.get("username", "").strip()
            raw_email = request.form.get("email", "").strip()
            user.email = raw_email or None
            user.role = request.form.get("role", "user")
            user.active = bool(request.form.get("active", ""))

            new_password = request.form.get("password", "")
            if new_password:
                user.password_hash = bcrypt.hashpw(
                    new_password.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")

            # Estado DESPUÉS
            after_data = {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "active": user.active,
                "uid": user.uid,
            }

            try:
                # registrar movimiento
                log_movement(
                    db,
                    user_id=actor_id,
                    entity_type="user",
                    entity_id=user.id,
                    action="update",
                    before_data=before_data,
                    after_data=after_data,
                    description=f"User '{user.username}' updated",
                    user_agent=request.user_agent.string,
                )

                db.commit()
                flash("✅ User updated successfully", "success")
                return redirect(url_for("users.index"))

            except IntegrityError as e:
                db.rollback()
                detail = str(getattr(e, "orig", e))

                print("IntegrityError on edit_user:", detail)

                if "users_uid_key" in detail:
                    flash("UID ya está en uso por otro usuario.", "danger")
                elif "users_username_key" in detail:
                    flash("Username ya está en uso por otro usuario.", "danger")
                elif "users_email_key" in detail:
                    flash("Email ya está en uso por otro usuario.", "danger")
                else:
                    print(e)
                    flash("Error de integridad en BD (constraint UNIQUE).", "danger")
            except SQLAlchemyError as e:
                db.rollback()
                print("SQLAlchemyError on edit_user:", e)
                flash("Error de base de datos al actualizar el usuario.", "danger")

        # GET o POST con error: mostramos el formulario con el user aún ligado a la sesión
        return render_template("users/form.html", page_title="Edit user", user=user)

    finally:
        db.close()

@bp.route("/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    db = SessionLocal()
    try:
        print("DELETE /users", user_id, "form=", dict(request.form))
        user = db.get(models.User, user_id)
        if not user:
            flash("User not found.", "warning")
            return redirect(url_for("users.index"))

        if getattr(current_user, "id", None) == user.id:
            flash("No puedes borrarte a ti mismo.", "warning")
            return redirect(url_for("users.index"))

        actor_id = getattr(current_user, "id", None)

        # estado ANTES de borrar
        before_data = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "active": user.active,
        }

        username = user.username

        log_movement(
            db,
            user_id=actor_id,
            entity_type="user",
            entity_id=user.id,
            action="delete",
            before_data=before_data,
            after_data=None,
            description=f"User '{username}' deleted",
            user_agent=request.user_agent.string,
        )

        db.delete(user)
        db.commit()

        # Verifica de inmediato
        still = db.query(models.User.id).filter_by(id=user_id).first()
        print("Deleted?", "NO (still exists)" if still else "YES")
        flash(f"🗑️ User '{username}' deleted successfully.", "success")
    except IntegrityError as e:
        db.rollback()
        print("IntegrityError on delete:", e)
        flash("No se puede borrar: existen registros relacionados (FK).", "danger")
    except SQLAlchemyError as e:
        db.rollback()
        print("SQLAlchemyError on delete:", e)
        flash(f"Error de base de datos: {e}", "danger")
    finally:
        db.close()
    return redirect(url_for("users.index"))

@bp.route("/read-uid", methods=["POST"])
def read_uid_once():
    """
    Intentar leer una tarjeta NFC una vez y devolver el UID en JSON.
    No modifica la BD, solo sirve para rellenar el campo 'uid' del formulario.
    """
    if not NFC_AVAILABLE:
        return jsonify({
            "success": False,
            "reason": "nfc_unavailable",
            "error": "NFC no disponible en el servidor."
        })

    try:
        reader = ACR122()
        info = reader.get_uid()          # puede lanzar NoCardException
        uid = info.get("uid_hex", "").upper()
    except NoCardException:
        return jsonify({
            "success": False,
            "reason": "no_card",
            "error": "No se ha detectado ninguna tarjeta."
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "reason": "reader_error",
            "error": f"Error del lector NFC: {e}"
        })

    if not uid:
        return jsonify({
            "success": False,
            "reason": "no_uid",
            "error": "No se ha podido obtener un UID válido."
        })
    db = SessionLocal()
    try:
        device = (
            db.query(models.Device)
              .filter(models.Device.uid == uid)
              .first()
        )
        return jsonify({
            "success": True,
            "uid": uid,
            "device_id": device.id if device else None,
            "device_name": device.name if device else None,
        })
    finally:
        db.close()