from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from . import bp

from app.db import SessionLocal
import app.models as models
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from math import ceil
from datetime import datetime,timezone

from app.scripts import log_movement

# Opciones (ajústalas si usas ENUM en la DB)
DEVICE_TYPES = ["vending", "canteen", "instructor", "guest"]
DEVICE_STATUSES = ["assigned", "available", "lost", "annulled"]


@bp.route("/")
@login_required
def index():
    """Listado con búsqueda y filtros por columna"""
    q = (request.args.get("q") or "").strip()
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 20

    # Column filters
    name   = (request.args.get("name") or "").strip()
    uid    = (request.args.get("uid") or "").strip()
    dtype  = (request.args.get("type") or "").strip()
    status = (request.args.get("status") or "").strip()
    notes  = (request.args.get("notes") or "").strip()

    db = SessionLocal()
    try:
        query = db.query(models.Device)

        # Global search (q) - lo que ya tenías
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(
                    models.Device.name.ilike(like),
                    models.Device.uid.ilike(like),
                    models.Device.type.ilike(like),
                    models.Device.status.ilike(like),
                    models.Device.notes.ilike(like),
                )
            )

        # Column filters (se acumulan con AND)
        if name:
            query = query.filter(models.Device.name.ilike(f"%{name}%"))
        if uid:
            query = query.filter(models.Device.uid.ilike(f"%{uid}%"))
        if dtype:
            # usamos igualdad porque tienes un set cerrado: vending, canteen, etc.
            query = query.filter(models.Device.type == dtype)
        if status:
            query = query.filter(models.Device.status == status)
        if notes:
            query = query.filter(models.Device.notes.ilike(f"%{notes}%"))

        total = query.count()
        devices = (
            query.order_by(models.Device.id.asc())
                 .offset((page-1)*per_page)
                 .limit(per_page)
                 .all()
        )
        pages = ceil(total / per_page) if total else 1

        return render_template(
            "devices/index.html",
            page_title="TCO GUI",
            devices=devices,
            # búsqueda global
            q=q,
            # paginación
            page=page,
            per_page=per_page,
            total=total,
            pages=pages,
            has_prev=page > 1,
            has_next=page < pages,
            # filtros por columna (para mantener los valores en los inputs)
            filter_name=name,
            filter_uid=uid,
            filter_type=dtype,
            filter_status=status,
            filter_notes=notes,
            # por si quieres usar las listas en el template algún día
            DEVICE_TYPES=DEVICE_TYPES,
            DEVICE_STATUSES=DEVICE_STATUSES,
        )
    finally:
        db.close()


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_device():
    db = SessionLocal()
    try:
        if request.method == "POST":
            # JAMÁS leas id del form si tienes serial autoincremental
            name   = (request.form.get("name") or "").strip()
            uid    = (request.form.get("uid") or "").strip()
            dtype  = (request.form.get("type") or "guest").strip() or "guest"
            status = (request.form.get("status") or "available").strip() or "available"
            notes  = (request.form.get("notes") or "").strip()

            # Checkbox opcional; si no lo envías, DB tiene default true
            active_val = request.form.get("active")
            active = True if active_val is None else (active_val == "on")

            if not uid:
                flash("UID es obligatorio.", "warning")
                return render_template(
                    "devices/form.html",
                    page_title="New device",
                    device=None,
                    DEVICE_TYPES=DEVICE_TYPES,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                )

            if dtype not in DEVICE_TYPES:
                flash("Tipo inválido. Se usará 'guest'.", "warning")
                dtype = "guest"

            if status not in DEVICE_STATUSES:
                flash("Estado inválido. Se usará 'available'.", "warning")
                status = "available"

            d = models.Device(
                # id lo genera la DB
                uid=uid,
                name=name or None,   # name puede ser NULL según tu schema
                type=dtype,
                status=status,
                active=active,        # si tu modelo lo permite; si no, quítalo y deja default server-side
                notes=notes or None,  # notes puede ser NULL
                # Si tu modelo incluye created_at/updated_at con defaults de DB, no asignes aquí
                updated_at=datetime.now(timezone.utc),  # opcional, si no tienes trigger
            )

            db.add(d)
            db.flush()

            log_movement(
                db,
                user_id=getattr(current_user, "id", None),
                entity_type="device",
                entity_id=d.id,
                action="create",
                before_data=None,
                after_data={
                    "id": d.id,
                    "name": d.name,
                    "uid": d.uid,
                    "type": d.type,
                    "status": d.status,
                    "active": d.active,
                    "notes": d.notes,
                },
                description=f"Device '{d.name or d.uid}' created",
                success=True,
                user_agent=request.user_agent.string,
            )

            try:
                db.commit()
            except IntegrityError as e:
                db.rollback()
                # Si uid es UNIQUE, caes aquí; si no lo es, esto será otro conflicto
                flash("No se pudo crear el dispositivo. Revisa UID y valores únicos.", "danger")
                # Opcional: loggear e.orig para diagnóstico
                return render_template(
                    "devices/form.html",
                    page_title="New device",
                    device=None,
                    DEVICE_TYPES=DEVICE_TYPES,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                )

            flash("Device creado.", "success")
            return redirect(url_for("devices.index"))

        # GET
        return render_template(
            "devices/form.html",
            page_title="New device",
            device=None,
            DEVICE_TYPES=DEVICE_TYPES,
            DEVICE_STATUSES=DEVICE_STATUSES,
        )
    finally:
        db.close()


@bp.route("/<int:device_id>/edit", methods=["GET", "POST"])
@login_required
def edit_device(device_id):
    from datetime import datetime, timezone
    db = SessionLocal()
    try:
        d = db.query(models.Device).get(device_id)
        if not d:
            flash("Dispositivo no encontrado", "warning")
            return redirect(url_for("devices.index"))

        if request.method == "POST":
            # JAMÁS tocar d.id ni leer 'id' del form
            before_data = {
                "id": d.id,
                "name": d.name,
                "uid": d.uid,
                "type": d.type,
                "status": d.status,
                "active": d.active,
                "notes": d.notes,
            }

            uid    = (request.form.get("uid") or "").strip()
            name   = (request.form.get("name") or "").strip()
            dtype  = (request.form.get("type") or "guest").strip() or "guest"
            status = (request.form.get("status") or "available").strip() or "available"
            notes  = (request.form.get("notes") or "").strip()
            active_val = request.form.get("active")

            if not uid:
                flash("UID es obligatorio.", "danger")
                return render_template("devices/form.html",
                                       page_title="Edit device",
                                       device=d,
                                       DEVICE_TYPES=DEVICE_TYPES,
                                       DEVICE_STATUSES=DEVICE_STATUSES)
            
            if dtype not in DEVICE_TYPES:
                flash("Tipo inválido. Se usará 'guest'.", "warning")
                dtype = "guest"

            if status not in DEVICE_STATUSES:
                flash("Estado inválido. Se usará 'available'.", "warning")
                status = "available"

            # Normaliza valores
            d.uid    = uid
            d.name   = name or None
            d.type   = dtype
            d.status = status
            d.notes  = notes or None
            if hasattr(d, "active"):
                d.active = (active_val == "on")

            # Timestamp si no tienes trigger
            if hasattr(d, "updated_at"):
                d.updated_at = datetime.now(timezone.utc)

            db.flush()
            after_data = {
                "id": d.id,
                "name": d.name,
                "uid": d.uid,
                "type": d.type,
                "status": d.status,
                "active": d.active,
                "notes": d.notes,
            }
            log_movement(
                db,
                user_id=getattr(current_user, "id", None),
                entity_type="device",
                entity_id=d.id,
                action="update",
                before_data=before_data,
                after_data=after_data,
                description=f"Device '{d.name or d.uid}' updated",
                success=True,
                user_agent=request.user_agent.string,
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("No se pudo actualizar el dispositivo. Revisa UID y valores únicos.", "danger")
                return render_template(
                    "devices/form.html",
                    page_title="Edit device",
                    device=d,
                    DEVICE_TYPES=DEVICE_TYPES,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                )
            flash("Dispositivo actualizado.", "success")
            return redirect(url_for("devices.index"))

        return render_template("devices/form.html",
                               page_title="Edit device",
                               device=d,
                               DEVICE_TYPES=DEVICE_TYPES,
                               DEVICE_STATUSES=DEVICE_STATUSES)
    finally:
        db.close()

@bp.route("/<int:device_id>/delete", methods=["POST"])
@login_required
def delete_device(device_id):
    db = SessionLocal()
    try:
        d = db.query(models.Device).get(device_id)
        if not d:
            flash("Device no encontrado.", "danger")
            return redirect(url_for("devices.index"))

        # Snapshot ANTES de borrar
        before_data = {
            "id": d.id,
            "name": d.name,
            "uid": d.uid,
            "type": d.type,
            "status": d.status,
            "active": d.active,
            "notes": d.notes,
        }

        db.delete(d)
        db.flush()

        log_movement(
            db,
            user_id=getattr(current_user, "id", None),
            entity_type="device",
            entity_id=device_id,
            action="delete",
            before_data=before_data,
            after_data=None,
            description=f"Device '{before_data['name'] or before_data['uid']}' deleted",
            success=True,
            user_agent=request.user_agent.string,
        )

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash("No se pudo eliminar el dispositivo. Puede estar referenciado en otros registros.", "danger")
            return redirect(url_for("devices.index"))

        flash("Device eliminado.", "success")
        return redirect(url_for("devices.index"))

    finally:
        db.close()