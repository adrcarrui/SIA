from flask import render_template, session, request
from flask_login import login_required, current_user
from . import bp
from app.db import SessionLocal
from app.scripts.get_overdue_assignments import (
    get_overdue_course_alerts,
    get_cards_vs_trainees_alerts,
)
from app.models import User, Device, Course, Assignment, Movements
from sqlalchemy import func, case

@bp.app_context_processor
def inject_alerts_summary():
    """
    Hace que 'alerts_summary' esté disponible en TODOS los templates,
    para que el badge del sidebar funcione siempre.
    """
    db = SessionLocal()
    try:
        cards_alerts = get_cards_vs_trainees_alerts(db)
        overdue_alerts = get_overdue_course_alerts(db)

        alerts = []

        # +/- tarjetas  → notice
        for a in cards_alerts:
            c = a["course"]

            if a["type"] == "cards_missing":
                severity = "notice"
            else:
                severity = "notice"

            alerts.append({
                "severity": severity,
                "course": c,
            })

        # overdue → warning / critical
        for o in overdue_alerts:
            c = o["course"]

            if o["type"] == "overdue_1":
                severity = "warning"
            else:
                severity = "critical"

            alerts.append({
                "severity": severity,
                "course": c,
            })

        summary = {
            "notice":   sum(1 for a in alerts if a["severity"] == "notice"),
            "warning":  sum(1 for a in alerts if a["severity"] == "warning"),
            "critical": sum(1 for a in alerts if a["severity"] == "critical"),
        }

        return dict(alerts_summary=summary)
    finally:
        db.close()

@bp.route("/")
@login_required
def index():
    db = SessionLocal()
    try:
        # Métricas rápidas
        total_users = db.query(func.count(User.id)).scalar() or 0
        total_devices = db.query(func.count(Device.id)).scalar() or 0
        total_courses = db.query(func.count(Course.id)).scalar() or 0
        total_assignments = db.query(func.count(Assignment.id)).scalar() or 0
        total_movements = db.query(func.count(Movements.id)).scalar() or 0

        # Tarjetas activas
        total_active_cards = (
            db.query(func.count(Assignment.id))
              .filter(Assignment.released_at.is_(None))
              .scalar()
        ) or 0

        # Stats de devices
        raw_stats = (
            db.query(
                Device.type.label("type"),
                func.count(Device.id).label("total"),
                func.sum(
                    case(
                        (Device.status == "assigned", 1),
                        else_=0,
                    )
                ).label("assigned"),
            )
            .group_by(Device.type)
            .all()
        )

        device_stats = []
        for row in raw_stats:
            total = row.total or 0
            assigned = row.assigned or 0
            ratio = (assigned / total * 100) if total else 0
            device_stats.append(
                {
                    "type": row.type or "Unknown",
                    "total": total,
                    "assigned": assigned,
                    "ratio": ratio,
                }
            )

        # Bloques de alertas
        cards_alerts = get_cards_vs_trainees_alerts(db)
        overdue_alerts = get_overdue_course_alerts(db)

        alerts = []

        # 1) +/- tarjetas (nivel: notice)
        for a in cards_alerts:
            c = a["course"]
            cname = c.name or c.course or f"Course #{c.id}"

            if a["type"] == "cards_missing":
                msg = (
                    f"{cname}: {a['assigned']} cards / {a['trainees']} trainees "
                    f"(missing {a['diff']})."
                )
                alert_type = "cards_missing"
                severity = "notice"
            else:
                msg = (
                    f"{cname}: {a['assigned']} cards / {a['trainees']} trainees "
                    f"(extra {-a['diff']})."
                )
                alert_type = "cards_extra"
                severity = "notice"

            alerts.append({
                "type": alert_type,
                "severity": severity,
                "course": c,
                "message": msg,
            })

        # 2) Overdue (nivel: warning / critical)
        for o in overdue_alerts:
            c = o["course"]
            cname = c.name or c.course or f"Course #{c.id}"

            msg = (
                f"{cname}: {o['cards_count']} cards still assigned, "
                f"{o['days_late']} day(s) after course end."
            )

            if o["type"] == "overdue_1":
                severity = "warning"
            else:  # overdue_2
                severity = "critical"

            alerts.append({
                "type": o["type"],     # 'overdue_1' o 'overdue_2'
                "severity": severity,  # 'warning' o 'critical'
                "course": c,
                "message": msg,
            })

        # Resumen por severidad (lo que pinta tu badge en el sidebar)
        alerts_summary = {
            "notice":   sum(1 for a in alerts if a["severity"] == "notice"),
            "warning":  sum(1 for a in alerts if a["severity"] == "warning"),
            "critical": sum(1 for a in alerts if a["severity"] == "critical"),
        }

        return render_template(
            "index.html",
            total_users=total_users,
            total_devices=total_devices,
            total_courses=total_courses,
            total_assignments=total_assignments,
            total_movements=total_movements,
            device_stats=device_stats,
            alerts=alerts,
            alerts_summary=alerts_summary,
        )
    finally:
        db.close()


@bp.route("/test-calendar")
@login_required
def test_calendar():
    return render_template("test_calendar.html")


@bp.route("/alerts")
@login_required
def alerts_index():
    db = SessionLocal()
    try:
        # "my=1" -> solo alertas de cursos donde soy responsable
        my = request.args.get("my")

        cards_alerts = get_cards_vs_trainees_alerts(db)
        overdue_alerts = get_overdue_course_alerts(db)

        alerts = []

        # +/- tarjetas  → notice
        for a in cards_alerts:
            c = a["course"]
            cname = c.name or c.course or f"Course #{c.id}"

            if a["type"] == "cards_missing":
                msg = (
                    f"{cname}: {a['assigned']} cards / {a['trainees']} trainees "
                    f"(missing {a['diff']})."
                )
                alert_type = "cards_missing"
                severity = "notice"
            else:
                msg = (
                    f"{cname}: {a['assigned']} cards / {a['trainees']} trainees "
                    f"(extra {-a['diff']})."
                )
                alert_type = "cards_extra"
                severity = "notice"

            alerts.append({
                "type": alert_type,
                "severity": severity,
                "course": c,
                "message": msg,
            })

        # overdue → warning / critical
        for o in overdue_alerts:
            c = o["course"]
            cname = c.name or c.course or f"Course #{c.id}"

            msg = (
                f"{cname}: {o['cards_count']} cards still assigned, "
                f"{o['days_late']} day(s) after course end."
            )

            if o["type"] == "overdue_1":
                severity = "warning"
            else:
                severity = "critical"

            alerts.append({
                "type": o["type"],
                "severity": severity,
                "course": c,
                "message": msg,
            })

        # 🔥 Filtro "My Alerts": solo cursos donde el usuario autenticado es responsable
        if my == "1" and current_user.is_authenticated:
            user_id = current_user.id

            def is_mine(alert):
                c = alert.get("course")
                if not c:
                    return False
                return getattr(c, "responsible_id", None) == user_id

            alerts = [a for a in alerts if is_mine(a)]

        # Resumen por severidad (para usar también aquí si quieres)
        alerts_summary = {
            "notice":   sum(1 for a in alerts if a["severity"] == "notice"),
            "warning":  sum(1 for a in alerts if a["severity"] == "warning"),
            "critical": sum(1 for a in alerts if a["severity"] == "critical"),
        }

        return render_template(
            "alerts_index.html",
            alerts=alerts,
            alerts_summary=alerts_summary,
            filter_my=my,
        )
    finally:
        db.close()
