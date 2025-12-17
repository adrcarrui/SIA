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


def _alerts_scope_for_user():
    dept = (getattr(current_user, "department", "") or "").strip()
    role = (getattr(current_user, "role", "") or "").strip().lower()

    # Admin ve todo
    if "admin" in role:
        return None

    # ITC support ve solo ITC
    if dept.lower() == "itc support":
        return "ITC support"

    # TCO ve solo TCO
    if dept.upper() == "TCO":
        return "TCO"

    # fallback: nada (o todo). Mejor nada para no mezclar departamentos.
    return None


@bp.app_context_processor
def inject_alerts_summary():
    """
    Hace que 'alerts_summary' esté disponible en TODOS los templates,
    para que el badge del sidebar funcione siempre.
    """
    db = SessionLocal()
    try:
        managed_by = _alerts_scope_for_user()

        cards_alerts = get_cards_vs_trainees_alerts(db, managed_by=managed_by)
        overdue_alerts = get_overdue_course_alerts(db, managed_by=managed_by)

        alerts = []

        # +/- tarjetas  → notice
        for a in cards_alerts:
            alerts.append({
                "severity": "notice",
                "course": a["course"],
            })

        # overdue → warning / critical
        for o in overdue_alerts:
            severity = "warning" if o["type"] == "overdue_1" else "critical"
            alerts.append({
                "severity": severity,
                "course": o["course"],
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

        # Tarjetas activas (esto ahora mismo cuenta TODO; si quieres, luego lo filtramos por dept también)
        total_active_cards = (
            db.query(func.count(Assignment.id))
              .filter(Assignment.released_at.is_(None))
              .scalar()
        ) or 0

        # Stats de devices (legacy por Device.type)
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

        # Bloques de alertas (filtrados por dept)
        managed_by = _alerts_scope_for_user()
        cards_alerts = get_cards_vs_trainees_alerts(db, managed_by=managed_by)
        overdue_alerts = get_overdue_course_alerts(db, managed_by=managed_by)

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
            else:
                msg = (
                    f"{cname}: {a['assigned']} cards / {a['trainees']} trainees "
                    f"(extra {-a['diff']})."
                )
                alert_type = "cards_extra"

            alerts.append({
                "type": alert_type,
                "severity": "notice",
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

            severity = "warning" if o["type"] == "overdue_1" else "critical"

            alerts.append({
                "type": o["type"],     # 'overdue_1' o 'overdue_2'
                "severity": severity,
                "course": c,
                "message": msg,
            })

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
            total_active_cards=total_active_cards,
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
        my = request.args.get("my")

        # Scope por dept
        managed_by = _alerts_scope_for_user()

        cards_alerts = get_cards_vs_trainees_alerts(db, managed_by=managed_by)
        overdue_alerts = get_overdue_course_alerts(db, managed_by=managed_by)

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
            else:
                msg = (
                    f"{cname}: {a['assigned']} cards / {a['trainees']} trainees "
                    f"(extra {-a['diff']})."
                )
                alert_type = "cards_extra"

            alerts.append({
                "type": alert_type,
                "severity": "notice",
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

            severity = "warning" if o["type"] == "overdue_1" else "critical"

            alerts.append({
                "type": o["type"],
                "severity": severity,
                "course": c,
                "message": msg,
            })

        # Filtro "My Alerts": solo cursos donde soy responsable
        if my == "1" and current_user.is_authenticated:
            user_id = current_user.id
            alerts = [
                a for a in alerts
                if getattr(a.get("course"), "responsible_id", None) == user_id
            ]

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
