from . import bp
from flask import jsonify
from flask_login import login_required, current_user
from sqlalchemy import func
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