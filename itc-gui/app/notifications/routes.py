from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import desc
from datetime import datetime, timezone
from app.db import SessionLocal
import app.models as models
from . import bp


def _is_admin():
    role = (getattr(current_user, "role", "") or "").strip().lower()
    return "admin" in role


def _dept_scope():
    # Admin ve todo
    if _is_admin():
        return None

    dept = (getattr(current_user, "department", "") or "").strip()
    if dept.lower() == "itc support":
        return "ITC support"
    if dept.upper() == "TCO":
        return "TCO"

    return None


@bp.before_request
def _guard():
    # Solo usuarios autenticados y con dept válido (o admin)
    if not current_user.is_authenticated:
        abort(403)

    scope = _dept_scope()
    if scope is None and not _is_admin():
        abort(403)


@bp.route("/")
@login_required
def index():
    db = SessionLocal()
    try:
        scope = _dept_scope()

        status = (request.args.get("status") or "").strip()
        unread = (request.args.get("unread") or "").strip()  # "1" para solo no leídas

        q = db.query(models.Notification).filter(models.Notification.active.is_(True))

        if scope:
            q = q.filter(models.Notification.department_target == scope)

        if status:
            q = q.filter(models.Notification.status == status)

        if unread == "1":
            q = q.filter(models.Notification.read_at.is_(None))

        notifications = q.order_by(desc(models.Notification.created_at)).limit(200).all()

        unread_count = (
            db.query(models.Notification.id)
              .filter(models.Notification.active.is_(True))
              .filter(models.Notification.department_target == (scope or models.Notification.department_target))
              .filter(models.Notification.read_at.is_(None))
        )

        # Si scope es None (admin), no filtros por dept; si scope existe, filtramos
        if scope:
            unread_count = unread_count.filter(models.Notification.department_target == scope)

        unread_count = unread_count.count()

        return render_template(
            "notifications/index.html",
            notifications=notifications,
            unread_count=unread_count,
            filter_status=status,
            filter_unread=unread,
            page_title="Notifications",
        )
    finally:
        db.close()


@bp.route("/<int:notif_id>/read", methods=["POST"])
@login_required
def mark_read(notif_id):
    db = SessionLocal()
    try:
        scope = _dept_scope()

        n = db.query(models.Notification).get(notif_id)
        if not n or not n.active:
            flash("Notification not found.", "warning")
            return redirect(url_for("notifications.index"))

        if scope and n.department_target != scope and not _is_admin():
            abort(403)

        n.read_at = datetime.now(timezone.utc)
        n.read_by_user_id = getattr(current_user, "id", None)

        db.commit()
        return redirect(url_for("notifications.index", **request.args))
    finally:
        db.close()


@bp.route("/<int:notif_id>/status", methods=["POST"])
@login_required
def change_status(notif_id):
    new_status = (request.form.get("status") or "").strip()
    allowed = {"open", "in_progress", "done", "dismissed"}
    if new_status not in allowed:
        flash("Invalid status.", "danger")
        return redirect(url_for("notifications.index"))

    db = SessionLocal()
    try:
        scope = _dept_scope()

        n = db.query(models.Notification).get(notif_id)
        if not n or not n.active:
            flash("Notification not found.", "warning")
            return redirect(url_for("notifications.index"))

        if scope and n.department_target != scope and not _is_admin():
            abort(403)

        n.status = new_status
        n.updated_at = datetime.now(timezone.utc)

        # si lo marcas done/dismissed, lo damos por leído automáticamente
        if new_status in ("done", "dismissed") and n.read_at is None:
            n.read_at = datetime.now(timezone.utc)
            n.read_by_user_id = getattr(current_user, "id", None)

        db.commit()
        return redirect(url_for("notifications.index", **request.args))
    finally:
        db.close()
