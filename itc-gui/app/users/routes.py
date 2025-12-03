from flask import render_template, request, redirect, url_for, flash,jsonify,abort
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
import bcrypt
from app.models import User
# === NFC: imports y flag de disponibilidad ===
try:
    NFC_AVAILABLE = True
except Exception:
    # Si falla la importación (no hay lib, no hay lector, etc.)
    ACR122 = None

    class NoCardException(Exception):
        pass

    NFC_AVAILABLE = False

ALL_ROLES = ["admin", "supervisor", "employee", "user"]

def _role_level(role: str) -> str:
    """
    Normaliza el rol a un 'nivel' genérico:
    - 'admin' -> 'admin'
    - '*supervisor' -> 'supervisor'
    - '*employee' -> 'employee'
    - resto -> 'user'
    """
    if not role:
        return "user"
    r = role.lower()
    if r == "admin":
        return "admin"
    if r.endswith("supervisor"):
        return "supervisor"
    if r.endswith("employee") or r == "employee":
        return "employee"
    return "user"


def can_delete_user(actor, target) -> bool:
    if not actor.is_authenticated:
        return False

    # Nadie se borra a sí mismo
    if actor.id == target.id:
        return False

    actor_role = (actor.role or "user").lower()
    target_role = (target.role or "user").lower()

    actor_dept = (actor.department or "").strip().lower()
    target_dept = (target.department or "").strip().lower()

    a_level = _role_level(actor_role)
    t_level = _role_level(target_role)

    # Admin puede todo (menos a sí mismo)
    if a_level == "admin":
        return True

    # Supervisor:
    # - puede borrar user de cualquier dept
    # - puede borrar employee solo de su mismo dept
    if a_level == "supervisor":
        if t_level == "user":
            return True
        if t_level == "employee":
            return bool(actor_dept and target_dept and actor_dept == target_dept)
        return False

    # Employee: solo puede borrar user de su mismo dept
    if a_level == "employee":
        return (
            t_level == "user"
            and actor_dept
            and target_dept
            and actor_dept == target_dept
        )

    # User normal: no borra a nadie
    return False

def get_assignable_roles(actor_role: str):
    """
    Devuelve la lista de roles que el usuario actual puede asignar a otros.
    """
    actor_role = (actor_role or "").lower()

    if actor_role == "admin":
        # Puede crear cualquiera
        return ["admin", "supervisor", "employee", "user"]

    if actor_role == "supervisor":
        # Puede crear supervisor/employee/user, pero NO admin
        return ["supervisor", "employee", "user"]

    if actor_role == "employee":
        # Puede crear employee o user, pero no subir a nadie a supervisor/admin
        return ["employee", "user"]

    # role == "user" o cualquier otra cosa → no puede crear/editar usuarios
    return []

@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    # Búsqueda global (lo que ya tenías)
    q = (request.args.get("q") or "").strip()

    # Filtros por columna (fila encima de la tabla)
    username = (request.args.get("username") or "").strip()
    name     = (request.args.get("name") or "").strip()
    surname  = (request.args.get("surname") or "").strip()
    uid      = (request.args.get("uid") or "").strip()
    email    = (request.args.get("email") or "").strip()
    role     = (request.args.get("role") or "").strip()

    db = SessionLocal()
    try:
        query = db.query(models.User)

        # Filtro global q (como antes)
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

        # Filtros por columna (se acumulan con AND)
        if name:
            query = query.filter(models.User.name.ilike(f"%{name}%"))
        if surname:
            query = query.filter(models.User.surname.ilike(f"%{surname}%"))
        if username:
            query = query.filter(models.User.username.ilike(f"%{username}%"))
        if uid:
            query = query.filter(models.User.uid.ilike(f"%{uid}%"))
        if email:
            query = query.filter(models.User.email.ilike(f"%{email}%"))
        if role:
            query = query.filter(models.User.role.ilike(f"%{role}%"))

        total = query.count()
        users = (
            query.order_by(models.User.id.asc())
                 .offset((page-1)*per_page)
                 .limit(per_page)
                 .all()
        )

        return render_template(
            "users/index.html",
            users=users,
            # búsqueda global
            q=q,
            # paginación
            page=page,
            per_page=per_page,
            has_prev=page > 1,
            has_next=page * per_page < total,
            # filtros por columna (para rellenar los inputs)
            filter_name=name,
            filter_surname=surname,
            filter_username=username,
            filter_uid=uid,
            filter_email=email,
            filter_role=role,
            # helpers
            can_edit_user=can_edit_user,
            can_delete_user=can_delete_user,
        )
    finally:
        db.close()


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_user():
    actor_role = getattr(current_user, "role", None)
    assignable_roles = get_assignable_roles(actor_role)

    # Si este tío no puede asignar ningún rol → no entra aquí
    if not assignable_roles:
        abort(403)

    if request.method == "POST":
        name = request.form["name"].strip()
        surname = request.form.get("surname", "").strip()
        raw_uid = request.form["uid"].strip()
        username = request.form["username"].strip()
        password = request.form["password"]
        raw_email = request.form.get("email", "").strip()
        raw_role = (request.form.get("role", "user") or "user").strip().lower()
        active = bool(request.form.get("active"))

        # 🔒 validar que el rol elegido está permitido para el actor
        if raw_role not in assignable_roles:
            flash("You are not allowed to assign this role.", "danger")
            return render_template(
                "users/form.html",
                page_title="New user",
                user=None,
                assignable_roles=assignable_roles,
            )

        # 🔒 Hashear la contraseña antes de guardarla
        hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        uid = raw_uid or None
        email = raw_email or None
        role = raw_role  # ya validado

        db = SessionLocal()
        actor_id = getattr(current_user, "id", None)

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

    # GET
    return render_template(
        "users/form.html",
        page_title="New user",
        user=None,
        assignable_roles=assignable_roles,
    )



@bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def edit_user(user_id):
    db = SessionLocal()
    try:
        user = db.query(models.User).get(user_id)

        if not user:
            flash("User not found", "danger")
            return redirect(url_for("users.index"))

        actor = current_user
        actor_role = (getattr(actor, "role", None) or "user").lower()
        actor_id = getattr(actor, "id", None)
        is_self = (actor_id == user.id)

        # 🔒 Reglas de acceso (rol + departamento)
        if not can_edit_user(actor, user):
            flash("You are not allowed to edit this user.", "danger")
            return redirect(url_for("users.index"))

        # Roles asignables según el actor
        assignable_roles = get_assignable_roles(actor_role)

        # Si edita a OTRO y no tiene roles asignables, fuera
        if not is_self and not assignable_roles:
            flash("You are not allowed to change roles for this user.", "danger")
            return redirect(url_for("users.index"))

        if request.method == "POST":

            # Estado ANTES
            before_data = {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "active": user.active,
                "uid": user.uid,
                "department": user.department,
            }

            # ==========================
            # DATOS NEUTROS (cualquiera)
            # ==========================
            user.name = request.form["name"].strip()
            user.surname = request.form.get("surname", "").strip()

            raw_uid = (request.form.get("uid") or "").strip()
            if raw_uid == "" or raw_uid.lower() in ("none", "null"):
                user.uid = None
            else:
                user.uid = raw_uid

            user.username = (request.form.get("username") or "").strip()
            raw_email = (request.form.get("email") or "").strip()
            user.email = raw_email or None

            # ==========================
            # ROLE / ACTIVE / DEPARTMENT
            # ==========================
            raw_role = (request.form.get("role", user.role or "user") or "user").strip().lower()
            raw_department = (request.form.get("department", user.department or "") or "").strip()

            if is_self:
                # Editando SUS PROPIOS DATOS:
                # no dejamos que cambie role / department / active desde el form
                raw_role = (user.role or "user").lower()
                raw_department = user.department
                # user.active se queda como está

            else:
                # employee → NO toca role / active / department de OTROS
                if actor_role == "employee":
                    raw_role = (user.role or "user").lower()
                    raw_department = user.department
                    # user.active no se toca

                # supervisores
                elif actor_role.endswith("supervisor"):
                    if raw_role not in ("user", "employee"):
                        flash("Supervisors can only assign 'user' or 'employee' roles.", "danger")
                        return render_template(
                            "users/form.html",
                            page_title="Edit user",
                            user=user,
                            assignable_roles=assignable_roles,
                        )

                    if raw_role not in assignable_roles:
                        flash("You are not allowed to assign this role.", "danger")
                        return render_template(
                            "users/form.html",
                            page_title="Edit user",
                            user=user,
                            assignable_roles=assignable_roles,
                        )

                    # Supervisor no cambia department
                    raw_department = user.department
                    user.role = raw_role
                    user.active = bool(request.form.get("active", ""))

                # admin: puede cambiar role/active/department dentro de assignable_roles
                elif actor_role == "admin":
                    if raw_role not in assignable_roles:
                        flash("You are not allowed to assign this role.", "danger")
                        return render_template(
                            "users/form.html",
                            page_title="Edit user",
                            user=user,
                            assignable_roles=assignable_roles,
                        )
                    user.role = raw_role
                    user.active = bool(request.form.get("active", ""))
                    user.department = raw_department or None

                else:
                    # Rol raro → no toca role/active/department
                    raw_role = (user.role or "user").lower()
                    raw_department = user.department

                # Para roles no admin/supervisor, aseguramos que no hemos tocado department
                if actor_role in ("employee",) or (not actor_role.endswith("supervisor") and actor_role != "admin"):
                    user.department = user.department  # explícito pero inútil

            # ==========================
            # PASSWORD
            # ==========================
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
                "department": user.department,
            }

            try:
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
                    flash("UID is already in use by another user.", "danger")
                elif "users_username_key" in detail:
                    flash("Username is already in use by another user.", "danger")
                elif "users_email_key" in detail:
                    flash("Email is already in use by another user.", "danger")
                else:
                    print(e)
                    flash("Integrity error in DB (UNIQUE constraint).", "danger")
            except SQLAlchemyError as e:
                db.rollback()
                print("SQLAlchemyError on edit_user:", e)
                flash("Database error while updating user.", "danger")

        # GET o POST con error
        return render_template(
            "users/form.html",
            page_title="Edit user",
            user=user,
            assignable_roles=assignable_roles,
        )

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

        actor = current_user

        # 🔒 Regla global: nadie se borra a sí mismo
        if getattr(actor, "id", None) == user.id:
            flash("You cannot delete your own user.", "warning")
            return redirect(url_for("users.index"))

        # 🔒 Reglas por rol + departamento
        if not can_delete_user(actor, user):
            flash("You are not allowed to delete this user.", "danger")
            return redirect(url_for("users.index"))

        actor_id = getattr(actor, "id", None)

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
        flash("Cannot delete: related records exist (FK).", "danger")
    except SQLAlchemyError as e:
        db.rollback()
        print("SQLAlchemyError on delete:", e)
        flash(f"Database error while deleting user: {e}", "danger")
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


def can_edit_user(actor, target) -> bool:
    """
    - Admin: puede editar a cualquiera.
    - Cualquiera: puede editarse a sí mismo.
    - Supervisor:
        * Puede editar users (role 'user') de cualquier departamento.
        * Puede editar employees de su mismo departamento.
        * No puede editar otros supervisors ni admins.
    - Employee / user:
        * Solo pueden editarse a sí mismos.
    """
    if not getattr(actor, "is_authenticated", False):
        return False

    actor_role = (actor.role or "user").lower()
    target_role = (target.role or "user").lower()
    actor_dept = (actor.department or "").strip().lower()
    target_dept = (target.department or "").strip().lower()

    # 1) Admin: todo
    if actor_role == "admin":
        return True

    # 2) Cualquiera puede editarse a sí mismo
    if actor.id == target.id:
        return True

    # 3) Supervisor
    if actor_role == "supervisor":
        # Puede editar cualquier 'user'
        if target_role == "user":
            return True

        # Puede editar 'employee' de su mismo dept
        if (
            target_role == "employee"
            and actor_dept
            and target_dept
            and actor_dept == target_dept
        ):
            return True

        # No puede editar otros supervisors ni admins
        return False

    # 4) employee / user: sólo su propia ficha (ya cubierta arriba)
    return False

@bp.route("/users", methods=["GET"])
def users_list():
    db = SessionLocal()

    # Leer parámetros de la URL (GET)
    username = request.args.get("username", type=str)
    first_name = request.args.get("first_name", type=str)
    last_name = request.args.get("last_name", type=str)
    role = request.args.get("role", type=str)
    department = request.args.get("department", type=str)

    q = db.query(User)

    # Filtro por username
    if username:
        q = q.filter(User.username.ilike(f"%{username.strip()}%"))

    # Filtro por nombre
    if first_name:
        q = q.filter(User.first_name.ilike(f"%{first_name.strip()}%"))

    # Filtro por apellido
    if last_name:
        q = q.filter(User.last_name.ilike(f"%{last_name.strip()}%"))

    # Filtro por rol (ajusta según tu modelo)
    if role:
        # Si `role` es un string en User (ej: 'admin', 'supervisor', etc.)
        q = q.filter(User.role == role)

        # Si tienes tabla Role y relación:
        # q = q.join(User.role_rel).filter(Role.name == role)

    # Filtro por departamento
    if department:
        q = q.filter(User.department.ilike(f"%{department.strip()}%"))

    users = q.order_by(User.id).all()

    return render_template(
        "users/list.html",
        users=users,
        # reenviamos los valores al template para rellenar el formulario
        username=username or "",
        first_name=first_name or "",
        last_name=last_name or "",
        role=role or "",
        department=department or "",
    )