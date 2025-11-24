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

    try:
        # GET → mostrar formulario genérico de devoluciones
        if request.method == "GET":
            return render_template("assignments/bulk_return.html")

        # POST → procesar devoluciones
        raw_uids = (request.form.get("uids") or "").strip()
        if not raw_uids:
            flash("No card UIDs received.", "warning")
            return render_template("assignments/bulk_return.html")

        # Una UID por línea
        uids = [u.strip() for u in raw_uids.splitlines() if u.strip()]

        # Buscar dispositivos existentes
        devices = (
            db.query(Device)
            .filter(Device.uid.in_(uids))
            .all()
        )
        devices_by_uid = {d.uid: d for d in devices}

        processed = []           # detalle por tarjeta
        per_course = {}          # course_id -> {course, returned, pending}
        skipped_not_found = []   # UIDs sin device
        skipped_no_assignment = []  # devices sin asignación activa
        returned_count = 0

        now = datetime.utcnow()

        for uid in uids:
            device = devices_by_uid.get(uid)

            # 1) UID no encontrado en devices
            if not device:
                skipped_not_found.append(uid)
                processed.append({
                    "uid": uid,
                    "status": "unknown_device",
                    "device": None,
                    "course": None,
                    "message": "Card not found in devices table.",
                })
                continue

            # 2) Buscar asignación activa (released_at IS NULL)
            q = db.query(Assignment).filter(
                Assignment.device_id == device.id,
                Assignment.released_at.is_(None),
            )

            # Preferir las 'active'
            q = q.order_by(
                (Assignment.status == "active").desc(),
                Assignment.assigned_at.desc(),
            )

            assignment = q.first()

            if not assignment:
                skipped_no_assignment.append(device)
                processed.append({
                    "uid": uid,
                    "status": "no_active_assignment",
                    "device": device,
                    "course": None,
                    "message": "Card has no active assignment.",
                })
                continue

            course = assignment.course

            # BEFORE (antes de devolver)
            before_data = {
                "assignment_status": assignment.status,
                "released_at": assignment.released_at.isoformat()
                    if assignment.released_at else None,
                "device_status": getattr(device, "status", None),
            }

            # 3) Marcar devolución
            assignment.status = "closed"
            assignment.released_at = now

            old_device_status = getattr(device, "status", None)
            if hasattr(Device, "status"):
                device.status = "available"

            # AFTER (después de devolver)
            after_data = {
                "assignment_status": assignment.status,
                "released_at": assignment.released_at.isoformat()
                    if assignment.released_at else None,
                "device_status": getattr(device, "status", None),
            }

            # AUDITORÍA: movimiento de devolución
            log_movement_assignment(
                db,
                user_id=current_user.id,
                assignment=assignment,
                device=device,
                course=course,
                action="returned",
                before=before_data,
                after=after_data,
                success=True,
            )

            returned_count += 1

            # Acumular resumen por curso
            if course.id not in per_course:
                per_course[course.id] = {
                    "course": course,
                    "returned": 0,
                    "pending": 0,
                }
            per_course[course.id]["returned"] += 1

            processed.append({
                "uid": uid,
                "status": "returned",
                "device": device,
                "course": course,
                "message": "Assignment closed and device returned to stock.",
            })

        # Calcular cuántas quedan pendientes por curso
        for cid, info in per_course.items():
            pending = (
                db.query(Assignment)
                .filter(
                    Assignment.course_id == cid,
                    Assignment.released_at.is_(None),
                )
                .count()
            )
            info["pending"] = pending

        db.commit()

        # Mensajes flash como antes
        if returned_count:
            flash(f"{returned_count} devices returned.", "success")

        if skipped_no_assignment:
            names = ", ".join(
                f"{d.name or 'Device #' + str(d.id)}" for d in skipped_no_assignment
            )
            flash(
                f"Some devices had no active assignment and were skipped: {names}",
                "warning",
            )

        if skipped_not_found:
            flash(
                f"Some UIDs did not match any device and were skipped: {', '.join(skipped_not_found)}",
                "warning",
            )

        # Renderizar la misma plantilla con el resumen
        return render_template(
            "assignments/bulk_return.html",
            processed=processed,
            per_course=list(per_course.values()),
        )

    except Exception as e:
        db.rollback()
        print("Error in bulk_return:", e)
        flash("Error returning devices.", "danger")
        return render_template("assignments/bulk_return.html")
    finally:
        db.close()

@bp.route("/overdue")
@login_required
def overdue_list():
    db = SessionLocal()
    overdue = get_overdue_assignments(db)

    return render_template(
        "assignments/overdue_list.html",
        overdue=overdue,
    )
