from flask import render_template, request, redirect, url_for, flash, send_file, Response
from flask_login import login_required, current_user
from . import bp
from io import StringIO, BytesIO
import csv
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from app.db import SessionLocal
import app.models as models
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, aliased
from math import ceil
from datetime import datetime, timezone

from app.scripts import log_movement

# Opciones (legacy)
DEVICE_TYPES = ["vending", "canteen", "instructor", "guest"]
DEVICE_STATUSES = ["assigned", "available", "lost", "annulled"]


def _notif_dept_scope():
    role = (getattr(current_user, "role", "") or "").strip().lower()
    dept = (getattr(current_user, "department", "") or "").strip()

    # Admin ve todo
    if "admin" in role:
        return None

    if dept.lower() == "itc support":
        return "ITC support"
    if dept.upper() == "TCO":
        return "TCO"

    # Si no tiene dept válido, no enseñamos nada (evita leaks)
    return "__none__"


@bp.app_context_processor
def inject_notifications_unread_count():
    """
    Disponible en TODOS los templates:
    notifications_unread_count
    """
    if not current_user.is_authenticated:
        return dict(notifications_unread_count=0)

    scope = _notif_dept_scope()
    if scope == "__none__":
        return dict(notifications_unread_count=0)

    db = SessionLocal()
    try:
        q = db.query(models.Notification.id).filter(models.Notification.active.is_(True))

        if scope is not None:
            q = q.filter(models.Notification.department_target == scope)

        # Unread = no leída y no cerrada
        q = q.filter(
            models.Notification.read_at.is_(None),
            models.Notification.status.notin_(["done", "dismissed"]),
        )

        return dict(notifications_unread_count=q.count())
    finally:
        db.close()


def get_asset_roots_and_children_map(db):
    roots = (
        db.query(models.AssetType)
          .filter(models.AssetType.parent_id.is_(None), models.AssetType.active.is_(True))
          .order_by(models.AssetType.sort_order.asc(), models.AssetType.code.asc())
          .all()
    )

    children = (
        db.query(models.AssetType)
          .filter(models.AssetType.parent_id.isnot(None), models.AssetType.active.is_(True))
          .order_by(models.AssetType.sort_order.asc(), models.AssetType.code.asc())
          .all()
    )

    children_map = {}
    for c in children:
        children_map.setdefault(str(c.parent_id), []).append({
            "id": c.id,
            "name": c.name,
            "requires_rfid": bool(getattr(c, "requires_rfid", False)),
            "requires_barcode": bool(getattr(c, "requires_barcode", False)),
        })

    return roots, children_map


def legacy_type_from_asset_code(asset_code: str) -> str:
    if not asset_code:
        return "guest"
    c = asset_code.upper()
    if c == "CARD_VENDING":
        return "vending"
    if c == "CARD_CANTEEN":
        return "canteen"
    if c == "CARD_INSTRUCTOR":
        return "instructor"
    if c == "CARD_GUEST":
        return "guest"
    return "guest"


def build_devices_query(db, args):
    """
    Filtros:
    q, name, uid, root_type_id, asset_type_id, status, notes.
    """
    q       = (args.get("q") or "").strip()
    name    = (args.get("name") or "").strip()
    uid     = (args.get("uid") or "").strip()
    barcode = (args.get("barcode") or "").strip()
    root_id = (args.get("root_type_id") or "").strip()
    sub_id  = (args.get("asset_type_id") or "").strip()
    status  = (args.get("status") or "").strip()
    notes   = (args.get("notes") or "").strip()

    Parent = aliased(models.AssetType)

    query = (
        db.query(models.Device)
          .outerjoin(models.AssetType, models.Device.asset_type_id == models.AssetType.id)
          .outerjoin(Parent, models.AssetType.parent_id == Parent.id)
          .options(joinedload(models.Device.asset_type).joinedload(models.AssetType.parent))
    )

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                models.Device.name.ilike(like),
                models.Device.uid.ilike(like),
                models.Device.status.ilike(like),
                models.Device.notes.ilike(like),
                models.AssetType.name.ilike(like),
                models.AssetType.code.ilike(like),
                Parent.name.ilike(like),
                Parent.code.ilike(like),
            )
        )

    if name:
        query = query.filter(models.Device.name.ilike(f"%{name}%"))
    if uid:
        query = query.filter(models.Device.uid.ilike(f"%{uid}%"))
    if barcode:
        query = query.filter(models.Device.barcode.ilike(f"%{barcode}%"))

    # ✅ Root filter: incluye devices cuyo asset_type ES el root (USB sin hijos)
    # y también devices cuyo asset_type es hijo de ese root.
    if root_id:
        try:
            root_id_int = int(root_id)
            query = query.filter(
                or_(
                    Parent.id == root_id_int,              # subtypes del root
                    models.AssetType.id == root_id_int     # el propio root
                )
            )
        except ValueError:
            pass

    if sub_id:
        try:
            sub_id_int = int(sub_id)
            query = query.filter(models.Device.asset_type_id == sub_id_int)
        except ValueError:
            pass

    if status:
        query = query.filter(models.Device.status == status)
    if notes:
        query = query.filter(models.Device.notes.ilike(f"%{notes}%"))

    return query


def _load_asset_type_for_device_or_error(db, asset_type_id_raw):
    """
    Devuelve (asset_type, error_msg)

    Permite:
    - Subtipo (parent_id != None): OK
    - Root (parent_id == None): OK SOLO si NO tiene hijos activos
      (caso típico: USB root sin subtipos)

    Si el root tiene hijos activos, obliga a seleccionar uno de ellos.
    """
    asset_type_id = int(asset_type_id_raw) if (asset_type_id_raw or "").isdigit() else None
    if not asset_type_id:
        return None, "Subtype es obligatorio."

    at = (
        db.query(models.AssetType)
          .filter(models.AssetType.id == asset_type_id, models.AssetType.active.is_(True))
          .first()
    )
    if not at:
        return None, "Subtype inválido."

    # Si es subtipo, perfecto
    if at.parent_id is not None:
        return at, None

    # Si es root, solo lo permitimos si no tiene hijos activos
    children_count = (
        db.query(models.AssetType.id)
          .filter(models.AssetType.parent_id == at.id, models.AssetType.active.is_(True))
          .count()
    )
    if children_count > 0:
        return None, "Debes seleccionar un subtipo (este tipo raíz tiene subtipos)."

    return at, None


@bp.route("/")
@login_required
def index():
    q        = (request.args.get("q") or "").strip()
    page     = max(int(request.args.get("page", 1)), 1)
    per_page = 20

    name          = (request.args.get("name") or "").strip()
    uid           = (request.args.get("uid") or "").strip()
    barcode       = (request.args.get("barcode") or "").strip()
    root_type_id  = (request.args.get("root_type_id") or "").strip()
    asset_type_id = (request.args.get("asset_type_id") or "").strip()
    status        = (request.args.get("status") or "").strip()
    notes         = (request.args.get("notes") or "").strip()

    db = SessionLocal()
    try:
        roots, children_map = get_asset_roots_and_children_map(db)
        query = build_devices_query(db, request.args)

        total = query.count()
        devices = (
            query.order_by(models.Device.id.asc())
                 .offset((page - 1) * per_page)
                 .limit(per_page)
                 .all()
        )
        pages = ceil(total / per_page) if total else 1

        return render_template(
            "devices/index.html",
            page_title="Devices",
            devices=devices,
            q=q,
            page=page,
            per_page=per_page,
            total=total,
            pages=pages,
            has_prev=page > 1,
            has_next=page < pages,

            filter_name=name,
            filter_uid=uid,
            filter_barcode=barcode,
            filter_root_type_id=root_type_id,
            filter_asset_type_id=asset_type_id,
            filter_status=status,
            filter_notes=notes,

            roots=roots,
            children_map=children_map,
            DEVICE_STATUSES=DEVICE_STATUSES,
        )
    finally:
        db.close()


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_device():
    db = SessionLocal()
    try:
        roots, children_map = get_asset_roots_and_children_map(db)

        if request.method == "POST":
            page_title = "New device"

            name   = (request.form.get("name") or "").strip()
            uid    = (request.form.get("uid") or "").strip()
            status = (request.form.get("status") or "available").strip() or "available"
            notes  = (request.form.get("notes") or "").strip()
            barcode = (request.form.get("barcode") or "").strip() or None

            asset_type_id_raw = (request.form.get("asset_type_id") or "").strip()

            active_val = request.form.get("active")
            active = True if active_val is None else (active_val in ("on", "1", "true", "True"))

            if status not in DEVICE_STATUSES:
                flash("Estado inválido. Se usará 'available'.", "warning")
                status = "available"

            # ✅ Validar asset type (subtipo o root sin hijos)
            at, err = _load_asset_type_for_device_or_error(db, asset_type_id_raw)
            if err:
                flash(err, "danger")
                return render_template(
                    "devices/form.html",
                    page_title=page_title,
                    device=None,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                    roots=roots,
                    children_map=children_map,
                    selected_root_id=None,
                    selected_child_id=None,
                )

            # Si es subtipo -> root = parent_id, child = at.id
            # Si es root sin hijos -> root = at.id, child = None
            selected_root_id = at.parent_id if at.parent_id else at.id
            selected_child_id = at.id if at.parent_id else None

            # ✅ Reglas por flags (si no existen en root, da igual, queda False)
            if getattr(at, "requires_rfid", False) and not uid:
                flash("UID es obligatorio para este tipo de asset.", "danger")
                return render_template(
                    "devices/form.html",
                    page_title=page_title,
                    device=None,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                    roots=roots,
                    children_map=children_map,
                    selected_root_id=selected_root_id,
                    selected_child_id=selected_child_id,
                )

            if getattr(at, "requires_barcode", False) and not barcode:
                flash("Barcode es obligatorio para este tipo de asset.", "danger")
                return render_template(
                    "devices/form.html",
                    page_title=page_title,
                    device=None,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                    roots=roots,
                    children_map=children_map,
                    selected_root_id=selected_root_id,
                    selected_child_id=selected_child_id,
                )

            # limpia valores si no aplican
            if not getattr(at, "requires_rfid", False):
                uid = None
            if not getattr(at, "requires_barcode", False):
                barcode = None

            # Fallback: si no hay uid pero hay barcode -> uid = barcode
            if not uid and barcode:
                uid = barcode

            if not uid:
                flash("Debes indicar UID o Barcode.", "danger")
                return redirect(url_for("devices.new_device"))

            dtype = legacy_type_from_asset_code(at.code)

            d = models.Device(
                uid=uid,
                name=name or None,
                type=dtype,  # legacy
                status=status,
                active=active,
                notes=notes or None,
                asset_type_id=at.id,
                barcode=barcode,
                updated_at=datetime.now(timezone.utc),
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
                    "asset_type_id": d.asset_type_id,
                    "barcode": getattr(d, "barcode", None),
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
            except IntegrityError:
                db.rollback()
                flash("No se pudo crear el dispositivo. Revisa UID y valores únicos.", "danger")
                return render_template(
                    "devices/form.html",
                    page_title=page_title,
                    device=None,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                    roots=roots,
                    children_map=children_map,
                    selected_root_id=selected_root_id,
                    selected_child_id=selected_child_id,
                )

            flash("Device creado.", "success")
            return redirect(url_for("devices.index"))

        # GET
        return render_template(
            "devices/form.html",
            page_title="New device",
            device=None,
            DEVICE_STATUSES=DEVICE_STATUSES,
            roots=roots,
            children_map=children_map,
            selected_root_id=None,
            selected_child_id=None,
        )
    finally:
        db.close()


@bp.route("/<int:device_id>/edit", methods=["GET", "POST"])
@login_required
def edit_device(device_id):
    db = SessionLocal()
    try:
        d = db.query(models.Device).get(device_id)
        if not d:
            flash("Dispositivo no encontrado", "warning")
            return redirect(url_for("devices.index"))

        roots, children_map = get_asset_roots_and_children_map(db)

        selected_child_id = getattr(d, "asset_type_id", None)
        selected_root_id = None
        if selected_child_id:
            child = db.query(models.AssetType).filter(models.AssetType.id == selected_child_id).first()
            if child:
                selected_root_id = child.parent_id if child.parent_id else child.id

        if request.method == "POST":
            page_title = "Edit device"

            before_data = {
                "id": d.id,
                "name": d.name,
                "uid": d.uid,
                "type": d.type,
                "asset_type_id": getattr(d, "asset_type_id", None),
                "barcode": getattr(d, "barcode", None),
                "status": d.status,
                "active": d.active,
                "notes": d.notes,
            }

            uid    = (request.form.get("uid") or "").strip()
            name   = (request.form.get("name") or "").strip()
            status = (request.form.get("status") or "available").strip() or "available"
            notes  = (request.form.get("notes") or "").strip()
            barcode = (request.form.get("barcode") or "").strip() or None
            active_val = request.form.get("active")

            asset_type_id_raw = (request.form.get("asset_type_id") or "").strip()

            if status not in DEVICE_STATUSES:
                flash("Estado inválido. Se usará 'available'.", "warning")
                status = "available"

            # ✅ Validar asset type (subtipo o root sin hijos)
            at, err = _load_asset_type_for_device_or_error(db, asset_type_id_raw)
            if err:
                flash(err, "danger")
                return render_template(
                    "devices/form.html",
                    page_title=page_title,
                    device=d,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                    roots=roots,
                    children_map=children_map,
                    selected_root_id=selected_root_id,
                    selected_child_id=selected_child_id,
                )

            selected_root_id = at.parent_id if at.parent_id else at.id
            selected_child_id = at.id if at.parent_id else None

            if getattr(at, "requires_rfid", False) and not uid:
                flash("UID es obligatorio para este tipo de asset.", "danger")
                return render_template(
                    "devices/form.html",
                    page_title=page_title,
                    device=d,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                    roots=roots,
                    children_map=children_map,
                    selected_root_id=selected_root_id,
                    selected_child_id=selected_child_id,
                )

            if getattr(at, "requires_barcode", False) and not barcode:
                flash("Barcode es obligatorio para este tipo de asset.", "danger")
                return render_template(
                    "devices/form.html",
                    page_title=page_title,
                    device=d,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                    roots=roots,
                    children_map=children_map,
                    selected_root_id=selected_root_id,
                    selected_child_id=selected_child_id,
                )

            if not getattr(at, "requires_rfid", False):
                uid = None
            if not getattr(at, "requires_barcode", False):
                barcode = None

            if not uid and barcode:
                uid = barcode

            if not uid:
                flash("Debes indicar UID o Barcode.", "danger")
                return render_template(
                    "devices/form.html",
                    page_title=page_title,
                    device=d,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                    roots=roots,
                    children_map=children_map,
                    selected_root_id=selected_root_id,
                    selected_child_id=selected_child_id,
                )

            dtype = legacy_type_from_asset_code(at.code)

            d.uid = uid
            d.name = name or None
            d.asset_type_id = at.id
            d.barcode = barcode
            d.type = dtype
            d.status = status
            d.notes = notes or None
            if hasattr(d, "active"):
                d.active = (active_val == "on")

            if hasattr(d, "updated_at"):
                d.updated_at = datetime.now(timezone.utc)

            db.flush()

            after_data = {
                "id": d.id,
                "name": d.name,
                "uid": d.uid,
                "type": d.type,
                "asset_type_id": getattr(d, "asset_type_id", None),
                "barcode": getattr(d, "barcode", None),
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
                    page_title=page_title,
                    device=d,
                    DEVICE_STATUSES=DEVICE_STATUSES,
                    roots=roots,
                    children_map=children_map,
                    selected_root_id=selected_root_id,
                    selected_child_id=selected_child_id,
                )

            flash("Dispositivo actualizado.", "success")
            return redirect(url_for("devices.index"))

        return render_template(
            "devices/form.html",
            page_title="Edit device",
            device=d,
            roots=roots,
            children_map=children_map,
            selected_root_id=selected_root_id,
            selected_child_id=selected_child_id,
            DEVICE_STATUSES=DEVICE_STATUSES,
        )
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


@bp.route("/export")
@login_required
def export_devices():
    fmt = request.args.get("format", "csv").lower()

    page     = max(int(request.args.get("page", 1)), 1)
    per_page = int(request.args.get("per_page", 20))

    db = SessionLocal()
    try:
        query = build_devices_query(db, request.args)
        devices = (
            query.options(
                joinedload(models.Device.asset_type).joinedload(models.AssetType.parent)
            )
            .order_by(models.Device.id.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
    finally:
        db.close()

    if fmt == "csv":
        return _export_devices_csv(devices)
    elif fmt in ("xlsx", "excel"):
        return _export_devices_excel(devices)
    elif fmt == "pdf":
        return _export_devices_pdf(devices)
    else:
        return Response("Unsupported format", status=400)


def _device_rows(devices):
    """
    Exporta el listado mostrando:
    - Root type = asset_type.parent.name (si existe)
    - Subtype = asset_type.name
    - UID y Barcode según aplique
    """
    rows = []

    has_barcode = False
    if devices:
        has_barcode = hasattr(devices[0], "barcode")

    header = ["ID", "Name", "UID", "Root type", "Subtype", "Status", "Notes"]
    if has_barcode:
        header.insert(3, "Barcode")
    rows.append(header)

    for d in devices:
        root_name = ""
        sub_name = ""

        if getattr(d, "asset_type", None):
            sub_name = getattr(d.asset_type, "name", "") or ""
            if getattr(d.asset_type, "parent", None):
                root_name = getattr(d.asset_type.parent, "name", "") or ""

        row = [
            d.id,
            d.name or "",
            d.uid or "",
            root_name,
            sub_name,
            d.status or "",
            d.notes or "",
        ]

        if has_barcode:
            row.insert(3, getattr(d, "barcode", "") or "")

        rows.append(row)

    return rows


def _export_devices_csv(devices):
    output = StringIO()
    writer = csv.writer(output)
    for row in _device_rows(devices):
        writer.writerow(row)

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=devices.csv"}
    )


def _export_devices_excel(devices):
    wb = Workbook()
    ws = wb.active
    ws.title = "Devices"

    for row in _device_rows(devices):
        ws.append(row)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="devices.xlsx"
    )


def _export_devices_pdf(devices):
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

    title = Paragraph("Devices report", styles["Heading1"])
    elements.append(title)
    elements.append(Spacer(1, 12))

    data = _device_rows(devices)
    table = Table(data, repeatRows=1)

    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00205d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),

        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 1), (0, -1), "RIGHT"),
        ("ALIGN", (1, 1), (4, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),

        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])

    table.setStyle(table_style)
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="devices.pdf",
    )
