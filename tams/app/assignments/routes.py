from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, cast, String
from . import bp
from app.db import SessionLocal
from app.models import Assignment, Device, Course, User, Movements
from datetime import date, datetime, timedelta
from app.scripts import get_overdue_assignments, log_movement

def log_bulk_return_movement(db, *, user_id, items, action="return", success=True):
    """
    Registra un único movimiento en movements para una devolución masiva,
    potencialmente con tarjetas de distintos cursos.

    items: lista de dicts con:
      - device: instancia Device
      - course: instancia Course o None
      - assignment: instancia Assignment
      - before: dict (before_data)
      - after: dict (after_data)
    """
    if not items:
        return

    device_labels = []
    course_labels = set()
    entries_before = []
    entries_after = []

    def course_display_name(course):
        if not course:
            return None
        return (
            getattr(course, "name", None)
            or getattr(course, "course", None)
            or f"Course #{course.id}"
        )

    for it in items:
        device = it["device"]
        course = it.get("course")
        assignment = it["assignment"]
        before = it.get("before") or {}
        after = it.get("after") or {}

        device_name = device.name or f"Device #{device.id}"
        device_labels.append(device_name)

        course_name = course_display_name(course)
        if course_name:
            course_labels.add(course_name)

        base_info = {
            "device_id": device.id,
            "device_name": device.name,
            "uid": device.uid,
            "assignment_id": assignment.id,
            "course_id": course.id if course else None,
            "course_name": course_name,
        }

        entries_before.append({
            **base_info,
            **before,
        })

        entries_after.append({
            **base_info,
            **after,
        })

    # Descripción humana
    device_part = ", ".join(device_labels)

    if not course_labels:
        course_part = "no linked course"
    elif len(course_labels) == 1:
        course_part = f"course {next(iter(course_labels))}"
    else:
        course_part = "courses " + ", ".join(sorted(course_labels))

    desc = (
        f"Devices {device_part} returned from {course_part} "
        f"({len(items)} assignment(s) closed)."
    )

    movement = Movements(
        user_id=user_id,
        entity_type="bulk_return",
        entity_id=None,
        action=action,
        before_data={"items": entries_before},
        after_data={"items": entries_after},
        success=success,
        description=desc,
        user_agent=request.user_agent.string,
    )
    db.add(movement)

def log_bulk_assignment_movement(db, *, user_id, course, devices_info, action="assign", success=True):
    """
    Registra un único movimiento en movements para una operación de asignación
    de varias tarjetas (o una sola).

    devices_info: lista de dicts con:
      - device: instancia Device
      - assignment: instancia Assignment
      - before: dict (before_data)
      - after: dict (after_data)
    """
    if not devices_info:
        return

    device_labels = []
    devices_before = []
    devices_after = []

    for info in devices_info:
        device = info["device"]
        assignment = info["assignment"]
        before = info["before"]
        after = info["after"]

        device_labels.append(device.name or f"Device #{device.id}")

        devices_before.append({
            "device_id": device.id,
            "device_name": device.name,
            "uid": device.uid,
            "assignment_id": assignment.id,
            **(before or {}),
        })

        devices_after.append({
            "device_id": device.id,
            "device_name": device.name,
            "uid": device.uid,
            "assignment_id": assignment.id,
            **(after or {}),
        })

    if len(device_labels) == 1:
        desc = (
            f"Device {device_labels[0]} assigned to course "
            f"{course.name} (ID {course.id})."
        )
    else:
        desc = (
            f"Devices {', '.join(device_labels)} assigned to course "
            f"{course.name} (ID {course.id})."
        )

    movement = Movements(
        user_id=user_id,
        entity_type="device",             # o "assignment"/"bulk_assignment" si prefieres
        entity_id=course.id,              # referencia al curso
        action=action,
        before_data={
            "course": {
                "id": course.id,
                "name": course.name,
            },
            "devices": devices_before,
        },
        after_data={
            "course": {
                "id": course.id,
                "name": course.name,
            },
            "devices": devices_after,
        },
        success=success,
        description=desc,
        user_agent=request.user_agent.string,
    )
    db.add(movement)

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
    try:
        devices = db.query(Device).all()
        courses = db.query(Course).all()

        if request.method == "POST":
            # Leer SIEMPRE como int
            device_id = request.form.get("device_id", type=int)
            course_id = request.form.get("course_id", type=int)
            notes = (request.form.get("notes") or "").strip() or None

            # 1) Validar que vienen los IDs
            if not device_id or not course_id:
                flash("Device and course are mandatory.", "danger")
                return render_template(
                    "assignments/form.html",
                    title="New assignment",
                    form_action=url_for("assignments.new"),
                    assignment=None,
                    devices=devices,
                    courses=courses,
                )

            # 2) Comprobar que existen en la BD
            device = db.query(Device).get(device_id)
            course = db.query(Course).get(course_id)

            if not device or not course:
                flash("Device or course is invalid.", "danger")
                return render_template(
                    "assignments/form.html",
                    title="New assignment",
                    form_action=url_for("assignments.new"),
                    assignment=None,
                    devices=devices,
                    courses=courses,
                )

            # (Opcional) evitar que el device esté activo en otro curso
            active_other = (
                db.query(Assignment)
                .filter(
                    Assignment.device_id == device.id,
                    Assignment.status == "active",
                    Assignment.course_id != course.id,
                )
                .first()
            )
            if active_other:
                flash(
                    f"Device {device.name or f'Device #{device.id}'} "
                    f"is already assigned to another active course (ID {active_other.course_id}).",
                    "danger",
                )
                return render_template(
                    "assignments/form.html",
                    title="New assignment",
                    form_action=url_for("assignments.new"),
                    assignment=None,
                    devices=devices,
                    courses=courses,
                )

            # 3) Crear assignment enlazado al curso y al device
            assignment = Assignment(
                device=device,   # relación
                course=course,   # relación
                status="active",
                created_by=current_user.id,
                notes=notes,
                assigned_at=datetime.utcnow(),
            )
            db.add(assignment)
            db.flush()  # para tener assignment.id

            # 4) Actualizar estado del device
            before = {"device_status": getattr(device, "status", None)}

            if hasattr(Device, "status"):
                device.status = "assigned"

            after = {
                "device_status": getattr(device, "status", None),
                "assignment_status": assignment.status,
                "assigned_at": assignment.assigned_at.isoformat(),
            }

            # 5) Log de movimiento
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

            db.commit()
            check_cards_vs_trainees(db,course.id)
            flash("Assignment created.", "success")
            return redirect(url_for("assignments.index"))

        # GET → mostrar formulario
        return render_template(
            "assignments/form.html",
            title="New assignment",
            form_action=url_for("assignments.new"),
            assignment=None,
            devices=devices,
            courses=courses,
        )

    finally:
        db.close()

@bp.route("/<int:id>/edit", methods=["GET", "POST"])
@login_required
def edit(id):
    db = SessionLocal()
    a = db.query(Assignment).get(id)
    if not a:
        flash("Assignment not found.", "danger")
        return redirect(url_for("assignments.index"))

    devices = db.query(Device).all()
    courses = db.query(Course).all()

    if request.method == "POST":
        a.device_id = request.form.get("device_id")
        a.course_id = request.form.get("course_id")
        a.notes = request.form.get("notes") or None
        a.status = request.form.get("status")

        db.commit()
        flash("Updated assignment.", "success")
        return redirect(url_for("assignments.index"))

    # GET → mostrar formulario con datos
    return render_template(
        "assignments/form.html",
        title=f"Edit assignment #{a.id}",
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
        flash("Assignment not found.", "danger")
        return redirect(url_for("assignments.index"))

    db.delete(a)
    db.commit()
    flash("Assignment deleted.", "success")
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

        # Para agrupar los movimientos en UNA sola entrada
        bulk_devices_info = []

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
            db.flush()  # Necesario para tener assignment.id

            before = {"device_status": device.status}

            device.status = "assigned"

            after = {
                "device_status": device.status,
                "assignment_status": assignment.status,
                "assigned_at": assignment.assigned_at.isoformat(),
            }

            # En vez de log_movement_assignment individual, acumulamos
            bulk_devices_info.append({
                "device": device,
                "assignment": assignment,
                "before": before,
                "after": after,
            })

            created_count += 1

        # Aquí, UNA sola entrada en movements para todo el bloque
        if bulk_devices_info:
            log_bulk_assignment_movement(
                db,
                user_id=current_user.id,
                course=course,
                devices_info=bulk_devices_info,
                action="assign",
                success=True,
            )

        db.commit()
        check_cards_vs_trainees(db,course_id_value)
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

    return redirect(url_for("main.index"))
    #return redirect(url_for("courses.detail", course_id=course_id_value))
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
        for cid in per_course.keys():
            check_cards_vs_trainees(db, cid)
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

@bp.route("/bulk-returns", methods=["GET", "POST"])
@login_required
def bulk_returns():
    db = SessionLocal()
    try:
        if request.method == "GET":
            # Pantalla de devolución masiva
            return render_template("assignments/bulk_returns.html")

        # POST → procesar devoluciones (borrado de asociaciones)
        raw_ids = request.form.getlist("assignment_ids")
        assignment_ids = [int(x) for x in raw_ids if x.strip()]

        if not assignment_ids:
            flash("No cards selected for return.", "warning")
            return redirect(url_for("assignments.bulk_returns"))

        assignments = (
            db.query(Assignment)
              .options(joinedload(Assignment.device), joinedload(Assignment.course))
              .filter(Assignment.id.in_(assignment_ids))
              .all()
        )

        if not assignments:
            flash("No matching assignments found.", "warning")
            return redirect(url_for("assignments.bulk_returns"))

        # Acumularemos aquí la info para el movimiento único
        bulk_items = []
        processed_assignments = []

        skipped_assignment_status = []  # assignment no active
        skipped_device_status = []     # device con estado que no es assigned/lost
        skipped_no_device = []         # assignment sin device (si se ha roto algo)

        for a in assignments:
            device = a.device
            course = a.course

            # 1) Solo devolvemos assignments en estado active
            if a.status != "active":
                skipped_assignment_status.append(a)
                continue

            # 2) Si por lo que sea no hay device asociado, lo saltamos
            if not device:
                skipped_no_device.append(a)
                continue

            # 3) Solo devolvemos si el device está en assigned o lost
            if device.status not in ("assigned", "lost"):
                skipped_device_status.append((a, device))
                continue

            # Snapshot antes de borrar la asignación
            before_assignment = {
                "id": a.id,
                "device_id": a.device_id,
                "course_id": a.course_id,
                "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
                "released_at": a.released_at.isoformat() if a.released_at else None,
                "status": a.status,
            }

            # Snapshot del device antes
            before_device = {
                "id": device.id,
                "status": device.status,
                "uid": device.uid,
                "name": device.name,
            }

            # 1) Poner el device como disponible (lo recuperamos)
            device.status = "available"

            after_device = {
                **before_device,
                "status": device.status,
            }

            # Guardamos en la lista para el movimiento global
            bulk_items.append({
                "device": device,
                "course": course,
                "assignment": a,
                "before": {
                    "assignment": before_assignment,
                    "device": before_device,
                },
                "after": {
                    "assignment": None,   # se borra
                    "device": after_device,
                },
            })

            # 2) Borrar la asociación de la base de datos
            processed_assignments.append(a)
            db.delete(a)

        # Movimiento único para toda la operación
        if bulk_items:
            log_bulk_return_movement(
                db,
                user_id=current_user.id,
                items=bulk_items,
                action="return",
                success=True,
            )

        # Sólo revisamos cursos de las asignaciones realmente procesadas
        course_ids = {a.course_id for a in processed_assignments if a.course_id is not None}

        db.commit()

        # Comprobación cards vs trainees tras devolver
        for cid in course_ids:
            check_cards_vs_trainees(db, cid)

        if processed_assignments:
            flash(
                f"{len(processed_assignments)} card associations deleted and devices set to available.",
                "success",
            )
        else:
            flash("No assignments were returned (no valid status combination).", "warning")

        # Mensajes de lo que se ha saltado

        if skipped_assignment_status:
            ids_txt = ", ".join(f"#{a.id} (status={a.status})" for a in skipped_assignment_status)
            flash(
                "Some assignments were skipped because their status is not 'active': "
                + ids_txt,
                "warning",
            )

        if skipped_device_status:
            parts = []
            for a, d in skipped_device_status:
                device_label = d.name or f"Device #{d.id}"
                parts.append(
                    f"assignment #{a.id} -> device {device_label} (status={d.status})"
                )
            txt = ", ".join(parts)
            flash(
                "Some assignments were skipped because the device status is not 'assigned' or 'lost': "
                + txt,
                "warning",
            )

        if skipped_no_device:
            ids_txt = ", ".join(f"#{a.id}" for a in skipped_no_device)
            flash(
                "Some assignments have no linked device and were skipped: "
                + ids_txt,
                "warning",
            )

        return redirect(url_for("main.index"))

    finally:
        db.close()


@bp.route("/bulk-return/find", methods=["POST"])
@login_required
def bulk_return_find():
    """
    Dado un UID de tarjeta, devuelve la ÚLTIMA asignación asociada a ese device,
    esté activa o no. Sirve para mostrar a qué curso ha estado vinculada la tarjeta.

    Respuesta tipo:
    {
      "ok": true,
      "data": {
        "uid": "ABC123",
        "device_name": "...",
        "device_id": 5,
        "assignment_id": 42,           # o null si nunca ha tenido asignaciones
        "course_name": "Course X",     # o null / "Not linked"
        "course_end_date": "2025-12-31",
        "overdue_days": 3,
        "status": "assigned" | "released" | "never_assigned" | "unknown_device"
      }
    }
    """
    db = SessionLocal()
    try:
        payload = request.get_json(silent=True) or {}
        uid = (payload.get("uid") or "").strip()

        if not uid:
            return jsonify({
                "ok": False,
                "error": "Empty UID."
            }), 400

        # 1) Buscar device por UID
        device = (
            db.query(Device)
              .filter(Device.uid == uid)
              .first()
        )

        if not device:
            # Tarjeta no registrada como device
            return jsonify({
                "ok": True,
                "data": {
                    "uid": uid,
                    "device_name": None,
                    "device_id": None,
                    "assignment_id": None,
                    "course_name": None,
                    "course_end_date": None,
                    "overdue_days": 0,
                    "status": "unknown_device",
                }
            })

        # 2) Buscar la ÚLTIMA asignación que haya tenido ese device
        assignment = (
            db.query(Assignment)
              .options(joinedload(Assignment.course))
              .filter(Assignment.device_id == device.id)
              .order_by(Assignment.assigned_at.desc())
              .first()
        )

        if not assignment:
            # Device existe pero jamás ha tenido assignments
            return jsonify({
                "ok": True,
                "data": {
                    "uid": uid,
                    "device_name": device.name,
                    "device_id": device.id,
                    "assignment_id": None,
                    "course_name": None,
                    "course_end_date": None,
                    "overdue_days": 0,
                    "status": "never_assigned",
                }
            })

        course = assignment.course

        # Sacar fecha de fin del curso (si existe)
        course_end_date = getattr(course, "end_date", None)
        if isinstance(course_end_date, datetime):
            course_end_date = course_end_date.date()

        overdue_days = 0
        if isinstance(course_end_date, date):
            today = date.today()
            if today > course_end_date:
                overdue_days = (today - course_end_date).days

        # Estado "lógico" de la asignación solo a título informativo
        if assignment.released_at is None:
            status = "assigned"
        else:
            status = "released"
        course = assignment.course

        # Sacar fecha de fin del curso (si existe)
        course_end_date = getattr(course, "end_date", None)
        if isinstance(course_end_date, datetime):
            course_end_date = course_end_date.date()

        # Nombre "visible" del curso, con fallback
        if course:
            course_display_name = (
                getattr(course, "name", None)
                or getattr(course, "course", None)
                or f"Course #{course.id}"
            )
        else:
            course_display_name = None
        return jsonify({
            "ok": True,
            "data": {
                "uid": uid,
                "device_name": device.name,
                "device_id": device.id,
                "assignment_id": assignment.id,
                "course_name": course_display_name,
                "course_end_date": course_end_date.isoformat() if course_end_date else None,
                "overdue_days": overdue_days,
                "status": status,
            }
        })
    finally:
        db.close()

def check_cards_vs_trainees(db, course_id: int):
    """
    Comprueba si el número de tarjetas activas asignadas a un curso
    coincide con el número de trainees. Si no coincide, lanza un flash.

    - Cuenta solo Assignment con released_at IS NULL.
    - Ignora cursos sin trainees (> 0).
    """
    course = db.query(Course).get(course_id)
    if not course:
        return

    # Si no hay número de trainees definido o es 0, no molestamos
    if course.trainees is None or course.trainees <= 0:
        return

    # Contamos solo asignaciones 'vivas'
    assigned = (
        db.query(Assignment)
        .filter(
            Assignment.course_id == course_id,
            Assignment.released_at.is_(None),
        )
        .count()
    )

    # Si coincide, silencio administrativo
    if assigned == course.trainees:
        return

    diff = course.trainees - assigned

    # Nombre legible del curso
    course_label = (
        (course.name or "").strip()
        or (course.course or "").strip()
        or f"Course #{course.id}"
    )

    if diff > 0:
        # Faltan tarjetas
        flash(
            f"[{course_label}] There are {diff} missing cards for this course "
            f"(assigned {assigned} / trainees {course.trainees}).",
            "warning",
        )
    else:
        # Sobran tarjetas
        flash(
            f"[{course_label}] There are {-diff} extra cards assigned for this course "
            f"(assigned {assigned} / trainees {course.trainees}).",
            "warning",
        )
