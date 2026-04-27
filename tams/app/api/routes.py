from . import bp
from flask import jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from app.db import SessionLocal
from app import models
from app.scripts.alerts_service import get_alerts_for_user
from app.scripts.alert_filters import reason_counts_for_calendar



def _notif_scope_for_user():
    role = (getattr(current_user, "role", "") or "").strip().lower()
    dept = (getattr(current_user, "department", "") or "").strip()

    # Admin ve todo
    if "admin" in role:
        return None

    # Dept scope
    if dept.lower() == "itc support":
        return "ITC support"
    if dept.upper() == "TCO":
        return "TCO"

    # Si no tiene dept válido: no cuentes nada
    return "__NONE__"


@bp.route("/counters", methods=["GET"])
@login_required
def counters():
    db = SessionLocal()
    try:
        # -------------------------
        # Notifications (UNREAD real)
        # -------------------------
        notif_scope = _notif_scope_for_user()
        if notif_scope == "__NONE__":
            notifications = 0
        else:
            qn = db.query(func.count(models.Notification.id)).filter(
                models.Notification.active.is_(True),
                models.Notification.read_at.is_(None),
                models.Notification.status.notin_(["done", "dismissed"]),
            )
            if notif_scope is not None:
                qn = qn.filter(models.Notification.department_target == notif_scope)

            notifications = int(qn.scalar() or 0)

        # -------------------------
        # Alerts (alineado con sidebar)
        # -------------------------
        now_utc = models.datetime.now(models.timezone.utc) if hasattr(models, "datetime") else None
        # mejor: import datetime/timezone arriba, pero te lo dejo simple:
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)

        alerts_list = get_alerts_for_user(db, current_user, include_hidden=True) or []
        alerts = 0

        for a in alerts_list:
            reasons = a.get("reasons") or []
            if reasons:
                for r in reasons:
                    if reason_counts_for_calendar(r, now_utc):
                        alerts += 1
            else:
                # legacy: si no hay reasons, cuenta 1 (o 0). Aquí lo dejo conservador.
                # alerts += 1
                pass

        return jsonify({
            "alerts": alerts,
            "notifications": notifications
        })
    finally:
        db.close()



@bp.route("/card-course-lookup", methods=["GET"])
@login_required
def card_course_lookup():
    code = (request.args.get("code") or "").strip().upper()

    if not code:
        return jsonify({
            "found": False,
            "message": "No code provided."
        }), 400

    db = SessionLocal()
    try:
        device = (
            db.query(models.Device)
            .filter(
                or_(
                    models.Device.uid == code,
                    models.Device.barcode == code
                )
            )
            .first()
        )

        if not device:
            return jsonify({
                "found": False,
                "message": "Card or barcode not found."
            })

        assignment = (
            db.query(models.Assignment)
            .join(models.Course, models.Assignment.course_id == models.Course.id)
            .filter(
                models.Assignment.device_id == device.id,
                models.Assignment.released_at.is_(None),
                models.Assignment.status == "active",
            )
            .order_by(models.Assignment.id.desc())
            .first()
        )

        if not assignment:
            return jsonify({
                "found": True,
                "assigned": False,
                "device": {
                    "id": device.id,
                    "name": device.name,
                    "uid": device.uid,
                    "barcode": getattr(device, "barcode", None),
                    "status": device.status,
                },
                "message": "Device found, but it is not assigned to any active course."
            })

        course = assignment.course

        return jsonify({
            "found": True,
            "assigned": True,
            "device": {
                "id": device.id,
                "name": device.name,
                "uid": device.uid,
                "barcode": getattr(device, "barcode", None),
                "status": device.status,
            },
            "assignment": {
                "id": assignment.id,
                "status": assignment.status,
            },
            "course": {
                "id": course.id,
                "course": course.course,
                "name": course.name,
                "client": course.client,
                "start_date": course.start_date.isoformat() if course.start_date else None,
                "end_date": course.end_date.isoformat() if course.end_date else None,
                "status_tco": getattr(course, "status_tco", None),
                "status_itc": getattr(course, "status_itc", None),
            }
        })
    finally:
        db.close()
