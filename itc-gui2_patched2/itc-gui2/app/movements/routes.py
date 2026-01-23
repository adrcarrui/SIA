from flask import render_template, request, redirect, url_for, flash, send_file, Response
from flask_login import login_required, current_user
from io import BytesIO
import csv  # solo si luego quieres CSV
from openpyxl import Workbook  # solo si quieres Excel
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import app.models as models
from math import ceil
from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, cast, String
from . import bp
from app.db import SessionLocal
from app.models import Movements, User
from io import StringIO, BytesIO

def build_movements_query(db, args):
    """
    Construye la query de Movements con los mismos filtros que el index().
    """
    # Global search
    q = (args.get("q") or "").strip()

    # Column filters
    f_user        = (args.get("user") or "").strip()
    f_action      = (args.get("action") or "").strip()
    f_entity_type = (args.get("entity_type") or "").strip()
    f_description = (args.get("description") or "").strip()
    f_success     = (args.get("success") or "").strip()  # "1" / "0" / ""
    f_date_from   = (args.get("date_from") or "").strip()
    f_date_to     = (args.get("date_to") or "").strip()

    query = (
        db.query(Movements)
        .options(joinedload(Movements.user))
        .order_by(Movements.created_at.desc())
    )

    if q:
        term = f"%{q}%"
        query = query.filter(
            or_(
                Movements.action.ilike(term),
                Movements.entity_type.ilike(term),
                Movements.description.ilike(term),
                Movements.user_agent.ilike(term),
                cast(Movements.entity_id, String).ilike(term),
                Movements.user.has(
                    or_(
                        User.username.ilike(term),
                        User.email.ilike(term),
                    )
                ),
            )
        )

    if f_user:
        term = f"%{f_user}%"
        query = query.filter(
            Movements.user.has(
                or_(
                    User.username.ilike(term),
                    User.email.ilike(term),
                )
            )
        )

    if f_action:
        query = query.filter(Movements.action == f_action)

    if f_entity_type:
        query = query.filter(Movements.entity_type.ilike(f"%{f_entity_type}%"))

    if f_description:
        query = query.filter(Movements.description.ilike(f"%{f_description}%"))

    if f_success == "1":
        query = query.filter(Movements.success.is_(True))
    elif f_success == "0":
        query = query.filter(Movements.success.is_(False))

    from datetime import datetime, timedelta

    if f_date_from:
        try:
            start_dt = datetime.strptime(f_date_from, "%Y-%m-%d")
            query = query.filter(Movements.created_at >= start_dt)
        except ValueError:
            pass

    if f_date_to:
        try:
            end_dt = datetime.strptime(f_date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Movements.created_at < end_dt)
        except ValueError:
            pass

    return query


@bp.route("/", methods=["GET"])
@login_required
def index():
    db = SessionLocal()

    # Global search
    q = (request.args.get("q") or "").strip()

    # Pagination
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    # Column filters (para mantenerlos en el template)
    f_user        = (request.args.get("user") or "").strip()
    f_action      = (request.args.get("action") or "").strip()
    f_entity_type = (request.args.get("entity_type") or "").strip()
    f_description = (request.args.get("description") or "").strip()
    f_success     = (request.args.get("success") or "").strip()  # "1" / "0" / ""
    f_date_from   = (request.args.get("date_from") or "").strip()
    f_date_to     = (request.args.get("date_to") or "").strip()

    # ¿Exportación?
    export_fmt = (request.args.get("export") or "").lower()

    try:
        query = build_movements_query(db, request.args)

        total = query.count()

        movements = (
            query
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        # Si hay parámetro export → devolvemos fichero en vez de HTML
        if export_fmt:
            if export_fmt == "pdf":
                return _export_movements_pdf(movements)
            elif export_fmt == "csv":
                return _export_movements_csv(movements)
            elif export_fmt in ("xlsx", "excel"):
                return _export_movements_excel(movements)
            else:
                return Response("Unsupported format", status=400)

        # Modo normal: HTML
        has_prev = page > 1
        has_next = page * per_page < total

        return render_template(
            "movements/index.html",
            movements=movements,
            total=total,
            q=q,
            page=page,
            per_page=per_page,
            has_prev=has_prev,
            has_next=has_next,
            # filters
            filter_user=f_user,
            filter_action=f_action,
            filter_entity_type=f_entity_type,
            filter_description=f_description,
            filter_success=f_success,
            filter_date_from=f_date_from,
            filter_date_to=f_date_to,
        )
    finally:
        db.close()

def _movement_rows(movements):
    """
    Filas para export: cabecera + datos.
    """
    rows = []
    # Cabecera
    rows.append([
        "ID",
        "Date",
        "User",
        "Action",
        "Entity type",
        "Entity ID",
        "Success",
        "Description",
    ])

    for m in movements:
        if m.user:
            user_label = m.user.username or m.user.email or ""
        else:
            user_label = ""

        date_str = m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else ""
        success_str = "Yes" if m.success else "No"

        rows.append([
            m.id,
            date_str,
            user_label,
            m.action or "",
            m.entity_type or "",
            str(m.entity_id) if m.entity_id is not None else "",
            success_str,
            (m.description or "")[:120],
        ])

    return rows


@bp.route("/export", methods=["GET"])
@login_required
def export_movements():
    """
    Exporta EXACTAMENTE los movements que el usuario está viendo:
    mismos filtros + misma página.
    Endpoint: movements.export_movements
    """
    fmt = (request.args.get("format") or "pdf").lower()

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    db = SessionLocal()
    try:
        query = build_movements_query(db, request.args)

        movements = (
            query
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
    finally:
        db.close()

    if fmt == "pdf":
        return _export_movements_pdf(movements)
    elif fmt == "csv":
        return _export_movements_csv(movements)
    elif fmt in ("xlsx", "excel"):
        return _export_movements_excel(movements)
    else:
        return Response("Unsupported format", status=400)
    
def _movement_rows(movements):
    rows = []
    rows.append([
        "ID",
        "Date",
        "User",
        "Action",
        "Entity type",
        "Entity ID",
        "Description",
    ])

    for m in movements:
        if m.user:
            user_label = m.user.username or m.user.email or ""
        else:
            user_label = ""

        date_str = m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else ""
        success_str = "Yes" if m.success else "No"

        rows.append([
            m.id,
            date_str,
            user_label,
            m.action or "",
            m.entity_type or "",
            str(m.entity_id) if m.entity_id is not None else "",
            (m.description or "")[:120],
        ])

    return rows


def _export_movements_csv(movements):
    output = StringIO()
    writer = csv.writer(output)

    for row in _movement_rows(movements):
        writer.writerow(row)

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=movements.csv"},
    )


def _export_movements_excel(movements):
    wb = Workbook()
    ws = wb.active
    ws.title = "Movements"

    for row in _movement_rows(movements):
        ws.append(row)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="movements.xlsx",
    )


def _export_movements_pdf(movements):
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

    title = Paragraph("Movements report", styles["Heading1"])
    elements.append(title)
    elements.append(Spacer(1, 12))

    data = _movement_rows(movements)
    table = Table(data, repeatRows=1)

    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00205d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),

        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

        ("ALIGN", (0, 1), (0, -1), "RIGHT"),   # ID
        ("ALIGN", (1, 1), (1, -1), "CENTER"),  # Date
        ("ALIGN", (2, 1), (6, -1), "LEFT"),    # resto

        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),

        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ])

    table.setStyle(table_style)
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="movements.pdf",
    )
