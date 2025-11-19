from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, cast, String
from . import bp
from app.db import SessionLocal
from app.models import Assignment, Device, Course, User

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

