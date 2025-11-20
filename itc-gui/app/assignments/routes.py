from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, cast, String
from . import bp
from app.db import SessionLocal
from app.models import Assignment, Device, Course, User, Movements
from datetime import date, datetime, timedelta
from app.scripts import get_overdue_assignments

def log_movement_assignment(db, *, user_id, assignment, device, course, action, before, after, success=True):
    """
    Helper para insertar un registro en movements para una Assignment.
    """
    m = Movements(
        user_id=user_id,
        entity_type="device",
        entity_id=device.id if device is not None else None,
        action=action,
        before_data=before,
        after_data=after,
        success=success,
        description=f"Assignment {action}: device {device.id} -> course {course.id}",
        user_agent=request.user_agent.string,
    )
    db.add(m)

@bp.route("/", methods=["GET"])
@login_required
def index():
    db = SessionLocal()

    q = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = (
        db.query(Assignment)
        .options(
            joinedload(Assignment.device),
            joinedload(Assignment.course),
            joinedload(Assignment.creator),
        )
        .order_by(Assignment.id.desc())
    )

    if q:
        term = f"%{q}%"
        query = query.filter(
            or_(
                Assignment.status.ilike(term),
                Assignment.notes.ilike(term),
                cast(Assignment.id, String).ilike(term),
                cast(Assignment.device_id, String).ilike(term),
                cast(Assignment.course_id, String).ilike(term),
                Device.name.ilike(term),
                Course.name.ilike(term),
                Assignment.creator.has(
                    or_(
                        User.username.ilike(term),
                        User.email.ilike(term),
                    )
                ),
            )
        )

    total = query.count()

    assigns = (
        query
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    has_prev = page > 1
    has_next = page * per_page < total

    return render_template(
        "assignments/index.html",
        assigns=assigns,
        q=q,
        page=page,
        per_page=per_page,
        has_prev=has_prev,
        has_next=has_next,
        total=total,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    db = SessionLocal()
    devices = db.query(Device).all()
    courses = db.query(Course).all()

    if request.method == "POST":
        device_id = request.form.get("device_id")
        course_id = request.form.get("course_id")
        notes = request.form.get("notes") or None

        a = Assignment(
            device_id=device_id,
            course_id=course_id,
            status="active",
            created_by=current_user.id,
            notes=notes,
        )

        db.add(a)
        db.commit()
        flash("Asignación creada correctamente.", "success")
        return redirect(url_for("assignments.index"))

    # GET → mostrar formulario
    return render_template(
        "assignments/form.html",
        title="Nueva asignación",
        form_action=url_for("assignments.new"),
        assignment=None,
        devices=devices,
        courses=courses,
    )


@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit(id):
    db = SessionLocal()
    a = db.query(Assignment).get(id)
    if not a:
        flash("Asignación no encontrada.", "danger")
        return redirect(url_for("assignments.index"))

    devices = db.query(Device).all()
    courses = db.query(Course).all()

    if request.method == "POST":
        a.device_id = request.form.get("device_id")
        a.course_id = request.form.get("course_id")
        a.notes = request.form.get("notes") or None
        a.status = request.form.get("status")

        db.commit()
        flash("Asignación actualizada.", "success")
        return redirect(url_for("assignments.index"))

    # GET → mostrar formulario con datos
    return render_template(
        "assignments/form.html",
        title=f"Editar asignación #{a.id}",
        form_action=url_for("assignments.edit", id=a.id),
        assignment=a,
        devices=devices,
        courses=courses,
    )


@bp.route("/<int:id>/delete", methods=["POST"])
@login_required
def delete(id):
    db = SessionLocal()
    a = db.query(Assignment).get(id)
    if not a:
        flash("Asignación no encontrada.", "danger")
        return redirect(url_for("assignments.index"))

    db.delete(a)
    db.commit()
    flash("Asignación eliminada.", "success")
    return redirect(url_for("assignments.index"))


@bp.route("/bulk-new", methods=["GET", "POST"])
@login_required
def new_bulk():
    db = SessionLocal()

    if request.method == "GET":
        course_id = request.args.get("course_id", type=int)
        if not course_id:
            abort(400, "course_id is required")

        course = db.query(Course).get(course_id)
        if not course:
            abort(404, "Course not found")

        return render_template("assignments/new_bulk.html", course=course)

    # POST
    course_id = request.form.get("course_id", type=int)
    if not course_id:
        abort(400, "course_id is required")

    course = db.query(Course).get(course_id)
    if not course:
        abort(404, "Course not found")

    course_id_value = course.id
    uids = request.form.getlist("uids[]")

    if not uids:
        flash("No cards received to assign.", "warning")
        db.close()
        return redirect(url_for("courses.detail", course_id=course_id_value))

    try:
        devices = db.query(Device).filter(Device.uid.in_(uids)).all()
        devices_by_uid = {d.uid: d for d in devices}

        created_count = 0
        skipped_same_course = []              # Caso 1
        skipped_other_course = []             # Caso 2
        skipped_not_available = []            # Caso 3
        skipped_not_found = []

        for uid in uids:
            device = devices_by_uid.get(uid)

            if not device:
                skipped_not_found.append(uid)
                continue

            # 1) ¿Asignado ACTIVAMENTE en otro curso?
            asig_other = (
                db.query(Assignment)
                .filter(
                    Assignment.device_id == device.id,
                    Assignment.status == "active",
                    Assignment.course_id != course_id_value,
                )
                .first()
            )
            if asig_other:
                skipped_other_course.append((device, asig_other))
                continue

            # 2) ¿Ya asignado a ESTE curso?
            asig_same = (
                db.query(Assignment)
                .filter(
                    Assignment.device_id == device.id,
                    Assignment.course_id == course_id_value,
                    Assignment.status == "active",
                )
                .first()
            )
            if asig_same:
                skipped_same_course.append(device)
                continue

            # 3) ¿Disponible para asignar?
            if device.status != "available":
                skipped_not_available.append(device)
                continue

            # Crear assignment
            assignment = Assignment(
                course_id=course_id_value,
                device_id=device.id,
                assigned_at=datetime.utcnow(),
                created_by=current_user.id,
                status="active",
            )
            db.add(assignment)
            db.flush()

            before = {"device_status": device.status}

            device.status = "assigned"

            after = {
                "device_status": device.status,
                "assignment_status": assignment.status,
                "assigned_at": assignment.assigned_at.isoformat(),
            }

            log_movement_assignment(
                db,
                user_id=current_user.id,
                assignment=assignment,
                device=device,
                course=course,
                action="assign",
                before=before,
                after=after,
                success=True,
            )

            created_count += 1

        db.commit()

        # Mensajes
        if created_count:
            flash(f"{created_count} devices assigned to course.", "success")

        # 1) Ya asignado a este curso
        if skipped_same_course:
            for d in skipped_same_course:
                flash(
                    f"Device {d.name or f'Device #{d.id}'} is already assigned to this course.",
                    "warning"
                )

        # 2) Asignado a otro curso
        if skipped_other_course:
            detalles = []
            for device, asig in skipped_other_course:
                other_course = getattr(asig, "course", None)
                if not other_course:
                    other_course = db.query(Course).get(asig.course_id)

                curso_text = (
                    f"{other_course.name} (ID {other_course.id})"
                    if (other_course and other_course.name)
                    else f"Course ID {asig.course_id}"
                )

                device_text = device.name or f"Device #{device.id}"
                detalles.append(f"{device_text} → {curso_text}")

            flash(
                "These devices are already assigned to another active course: "
                + "; ".join(detalles),
                "danger",
            )

        # 3) No available
        if skipped_not_available:
            for d in skipped_not_available:
                flash(
                    f"Device {d.name or f'Device #{d.id}'} is not available to assign.",
                    "danger"
                )

        if skipped_not_found:
            flash(
                "Unknown cards: " + ", ".join(skipped_not_found),
                "danger"
            )

    except Exception as e:
        db.rollback()
        print("Error in new_bulk:", e)
        flash("Error assigning devices.", "danger")
    finally:
        db.close()

    return redirect(url_for("courses.detail", course_id=course_id_value))

@bp.route("/bulk-return", methods=["GET", "POST"])
@login_required
def bulk_return():
    db = SessionLocal()

    # GET → mostrar formulario de Return
    if request.method == "GET":
        course_id = request.args.get("course_id", type=int)
        if not course_id:
            abort(400, "course_id is required")

        course = db.query(Course).get(course_id)
        if not course:
            abort(404, "Course not found")

        return render_template("assignments/bulk_return.html", course=course)

    # POST → procesar devoluciones
    course_id = request.form.get("course_id", type=int)
    if not course_id:
        abort(400, "course_id is required")

    course = db.query(Course).get(course_id)
    if not course:
        abort(404, "Course not found")

    course_id_value = course.id
    uids = request.form.getlist("uids[]")

    if not uids:
        flash("No cards received to return.", "warning")
        db.close()
        return redirect(url_for("courses.detail", course_id=course_id_value))

    try:
        # Buscar devices por UID
        devices = db.query(Device).filter(Device.uid.in_(uids)).all()
        devices_by_uid = {d.uid: d for d in devices}

        returned_count = 0
        skipped_not_found = []
        skipped_other_course = []     # (device, assignment en otro curso)
        skipped_no_assignment = []    # sin assignment activa en este curso

        for uid in uids:
            device = devices_by_uid.get(uid)

            # 1) UID sin device
            if not device:
                skipped_not_found.append(uid)
                continue

            # 2) ¿Asignado ACTIVAMENTE en OTRO curso?
            asig_other = (
                db.query(Assignment)
                .filter(
                    Assignment.device_id == device.id,
                    Assignment.status == "active",
                    Assignment.course_id != course_id_value,
                )
                .first()
            )
            if asig_other:
                skipped_other_course.append((device, asig_other))
                continue

            # 3) ¿Tiene asignación activa en ESTE curso?
            asig_course = (
                db.query(Assignment)
                .filter(
                    Assignment.device_id == device.id,
                    Assignment.course_id == course_id_value,
                    Assignment.status == "active",
                )
                .first()
            )

            if not asig_course:
                skipped_no_assignment.append(device)
                continue

            # 4) Devolución correcta:
            #    - borrar assignment
            #    - pasar device a available
            before = {
                "assignment": {
                    "id": asig_course.id,
                    "course_id": asig_course.course_id,
                    "device_id": asig_course.device_id,
                    "status": asig_course.status,
                    "assigned_at": asig_course.assigned_at.isoformat()
                    if asig_course.assigned_at else None,
                },
                "device_status": getattr(device, "status", None),
            }

            # Borrar assignment (tabla viva)
            db.delete(asig_course)

            # Actualizar estado del device
            old_device_status = getattr(device, "status", None)
            device.status = "available"

            after = {
                "assignment": None,  # ya no existe
                "device_status": device.status,
            }

            # AUDITORÍA
            log_movement_assignment(
                db,
                user_id=current_user.id,
                assignment=asig_course,
                device=device,
                course=course,
                action="return",
                before=before,
                after=after,
                success=True,
            )

            returned_count += 1

        db.commit()

        # Mensajes
        if returned_count:
            flash(f"{returned_count} devices returned successfully.", "success")

        if skipped_other_course:
            detalles = []
            for device, asig in skipped_other_course:
                other_course = getattr(asig, "course", None)
                if not other_course:
                    other_course = db.query(Course).get(asig.course_id)

                curso_text = (
                    f"{other_course.name} (ID {other_course.id})"
                    if (other_course and other_course.name)
                    else f"Course ID {asig.course_id}"
                )
                device_text = device.name or f"Device #{device.id}"
                detalles.append(f"{device_text} → {curso_text}")

            flash(
                "These devices are assigned to another active course and cannot be returned here: "
                + "; ".join(detalles),
                "danger",
            )

        if skipped_no_assignment:
            for d in skipped_no_assignment:
                flash(
                    f"Device {d.name or f'Device #{d.id}'} has no active assignment for this course.",
                    "warning",
                )

        if skipped_not_found:
            flash(
                "Unknown cards: " + ", ".join(skipped_not_found),
                "danger",
            )

    except Exception as e:
        db.rollback()
        print("Error in bulk_return:", e)
        flash("Error returning devices.", "danger")
    finally:
        db.close()

    return redirect(url_for("courses.detail", course_id=course_id_value))

@bp.route("/overdue")
@login_required
def overdue_list():
    db = SessionLocal()
    overdue = get_overdue_assignments(db)

    return render_template(
        "assignments/overdue_list.html",
        overdue=overdue,
    )
