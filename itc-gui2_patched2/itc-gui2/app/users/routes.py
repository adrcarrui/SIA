from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    abort,
    send_file,
    Response,
)
from . import bp
from app.db import SessionLocal
import app.models as models
from sqlalchemy import or_
import bcrypt
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from flask_login import login_required, current_user
from app.scripts import log_movement
from app.models import User

from io import StringIO, BytesIO
import csv
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

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


def build_users_query(db, args):
    """
    Construye la query de User con los mismos filtros que el índice.
    """
    # Búsqueda global
    q = (args.get("q") or "").strip()

    # Filtros por columna
    username = (args.get("username") or "").strip()
    name = (args.get("name") or "").strip()
    surname = (args.get("surname") or "").strip()
    uid = (args.get("uid") or "").strip()
    email = (args.get("email") or "").strip()
    role = (args.get("role") or "").strip()

    query = db.query(models.User)

    # Filtro global q
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                models.User.name.ilike(like),
                models.User.surname.ilike(like),
                models.User.username.ilike(like),
                models.User.uid.ilike(like),
                models.User.email.ilike(like),
                models.User.role.ilike(like),
            )
        )

    # Filtros por columna (AND)
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

    return query


@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    # Búsqueda global (lo que ya tenías)
    q = (request.args.get("q") or "").strip()

    # Filtros por columna (fila encima de la tabla)
    username = (request.args.get("username") or "").strip()
    name = (request.args.get("name") or "").strip()
    surname = (request.args.get("surname") or "").strip()
    uid = (request.args.get("uid") or "").strip()
    email = (request.args.get("email") or "").strip()
    role = (request.args.get("role") or "").strip()

    db = SessionLocal()
    try:
        query = db.query(models.User)

        # Filtro global q (como antes)
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    models.User.name.ilike(like),
                    models.User.surname.ilike(like),
                    models.User.username.ilike(like),
                    models.User.uid.ilike(like),
                    models.User.email.ilike(like),
                    models.User.role.ilike(like),
                )
            )

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
            .offset((page - 1) * per_page)
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

        # validar rol
        if raw_role not in assignable_roles:
            flash("You are not allowed to assign this role.", "danger")
            return render_template(
                "users/form.html",
                page_title="New user",
                user=None,
                assignable_roles=assignable_roles,
            )

        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        uid = raw_uid or None
        email = raw_email or None
        role = raw_role

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
        is_self = actor_id == user.id

        if not can_edit_user(actor, user):
            flash("You are not allowed to edit this user.", "danger")
            return redirect(url_for("users.index"))

        assignable_roles = get_assignable_roles(actor_role)

        if not is_self and not assignable_roles:
            flash("You are not allowed to change roles for this user.", "danger")
            return redirect(url_for("users.index"))

        if request.method == "POST":
            before_data = {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "active": user.active,
                "uid": user.uid,
                "department": user.department,
            }

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

            raw_role = (
                request.form.get("role", user.role or "user") or "user"
            ).strip().lower()
            raw_department = (
                request.form.get("department", user.department or "") or ""
            ).strip()

            if is_self:
                raw_role = (user.role or "user").lower()
                raw_department = user.department
            else:
                if actor_role == "employee":
                    raw_role = (user.role or "user").lower()
                    raw_department = user.department
                elif actor_role == "supervisor":
                    if raw_role not in ("user", "employee"):
                        flash(
                            "Supervisors can only assign 'user' or 'employee' roles.",
                            "danger",
                        )
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

                    raw_department = user.department
                    user.role = raw_role
                    user.active = bool(request.form.get("active", ""))
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
                    raw_role = (user.role or "user").lower()
                    raw_department = user.department

                if actor_role in ("employee",) or (
                    not actor_role.endswith("supervisor") and actor_role != "admin"
                ):
                    user.department = user.department

            new_password = request.form.get("password", "")
            if new_password:
                user.password_hash = bcrypt.hashpw(
                    new_password.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")

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

        if getattr(actor, "id", None) == user.id:
            flash("You cannot delete your own user.", "warning")
            return redirect(url_for("users.index"))

        if not can_delete_user(actor, user):
            flash("You are not allowed to delete this user.", "danger")
            return redirect(url_for("users.index"))

        actor_id = getattr(actor, "id", None)

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
    Devolver el UID leído en el *cliente* (PC local) y opcionalmente resolverlo
    contra la BD.

    Nuevo modelo (Option 1): el navegador obtiene el UID desde un agente local
    (127.0.0.1) y lo envía aquí. El servidor NO lee el lector PC/SC.
    """

    payload = request.get_json(silent=True) or {}
    uid_raw = payload.get("uid") or request.form.get("uid") or request.args.get("uid")
    uid = "".join(ch for ch in str(uid_raw or "").strip() if ch.isalnum()).upper()

    if not uid:
        return jsonify(
            {
                "success": False,
                "reason": "missing_uid",
                "error": "No UID received from client.",
            }
        )
    db = SessionLocal()
    try:
        device = db.query(models.Device).filter(models.Device.uid == uid).first()
        return jsonify(
            {
                "success": True,
                "uid": uid,
                "device_id": device.id if device else None,
                "device_name": device.name if device else None,
            }
        )
    finally:
        db.close()


@bp.route("/users", methods=["GET"])
def users_list():
    db = SessionLocal()

    username = request.args.get("username", type=str)
    first_name = request.args.get("first_name", type=str)
    last_name = request.args.get("last_name", type=str)
    role = request.args.get("role", type=str)
    department = request.args.get("department", type=str)

    q = db.query(User)

    if username:
        q = q.filter(User.username.ilike(f"%{username.strip()}%"))

    if first_name:
        q = q.filter(User.first_name.ilike(f"%{first_name.strip()}%"))

    if last_name:
        q = q.filter(User.last_name.ilike(f"%{last_name.strip()}%"))

    if role:
        q = q.filter(User.role == role)

    if department:
        q = q.filter(User.department.ilike(f"%{department.strip()}%"))

    users = q.order_by(User.id).all()

    return render_template(
        "users/list.html",
        users=users,
        username=username or "",
        first_name=first_name or "",
        last_name=last_name or "",
        role=role or "",
        department=department or "",
    )


# ===========================
#   EXPORT: CSV / EXCEL / PDF
# ===========================


def _user_rows(users):
    """
    Filas comunes para exportar usuarios.
    """
    rows = []
    rows.append(
        [
            "ID",
            "Name",
            "Surname",
            "Username",
            "Email",
            "Role",
            "Active",
        ]
    )

    for u in users:
        if u.active is True:
            active_str = "Yes"
        elif u.active is False:
            active_str = "No"
        else:
            active_str = ""

        rows.append(
            [
                u.id,
                u.name or "",
                u.surname or "",
                u.username or "",
                u.email or "",
                u.role or "",
                active_str,
            ]
        )

    return rows


def _export_users_csv(users):
    output = StringIO()
    writer = csv.writer(output)

    for row in _user_rows(users):
        writer.writerow(row)

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


def _export_users_excel(users):
    wb = Workbook()
    ws = wb.active
    ws.title = "Users"

    for row in _user_rows(users):
        ws.append(row)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="users.xlsx",
    )


def _export_users_pdf(users):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=40,
        bottomMargin=30,
    )

    styles = getSampleStyleSheet()
    elements = []

    title = Paragraph("Users report", styles["Heading1"])
    elements.append(title)
    elements.append(Spacer(1, 12))

    data = _user_rows(users)
    table = Table(data, repeatRows=1)

    table_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00205d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 1), (0, -1), "RIGHT"),
            ("ALIGN", (1, 1), (-1, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
    )

    table.setStyle(table_style)
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="users.pdf",
    )


@bp.route("/export", methods=["GET"])
@login_required
def export_users():
    """
    Exporta EXACTAMENTE los usuarios que el usuario está viendo:
    mismos filtros + misma página.
    """
    fmt = (request.args.get("format") or "pdf").lower()

    page = max(int(request.args.get("page", 1)), 1)
    per_page = int(request.args.get("per_page", 20))

    db = SessionLocal()
    try:
        query = build_users_query(db, request.args)

        users = (
            query.order_by(models.User.id.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
    finally:
        db.close()

    if fmt == "pdf":
        return _export_users_pdf(users)
    elif fmt == "csv":
        return _export_users_csv(users)
    elif fmt in ("xlsx", "excel"):
        return _export_users_excel(users)
    else:
        return Response("Unsupported format", status=400)
