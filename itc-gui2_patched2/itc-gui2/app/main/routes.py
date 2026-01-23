from flask import render_template, session, request
from flask_login import login_required, current_user
from . import bp
from app.extensions import db
from app.db import SessionLocal
from app.scripts.get_overdue_assignments import (
    get_overdue_course_alerts,
    get_cards_vs_trainees_alerts,
)
from app.models import User, Device, Course, Assignment, Movements
from sqlalchemy import func, case
import app.models as models
from app.scripts.alerts_service import get_alerts_for_user
from app.scripts.alert_filters import reason_counts_for_calendar
from datetime import datetime, timezone

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

    # Si no tiene dept válido: no enseñes nada
    return "__NONE__"


@bp.app_context_processor
def inject_notifications_badge():
    """
    Inyecta notifications_unread_count en TODOS los templates.
    Unread = status NO cerrado (no done/dismissed) y read_at IS NULL.
    """
    if not current_user.is_authenticated:
        return dict(notifications_unread_count=0)

    db = SessionLocal()
    try:
        scope = _notif_scope_for_user()
        if scope == "__NONE__":
            return dict(notifications_unread_count=0)

        q = db.query(func.count(models.Notification.id)).filter(
            models.Notification.active.is_(True),
            models.Notification.read_at.is_(None),
            models.Notification.status.notin_(["done", "dismissed"]),
        )

        if scope is not None:
            q = q.filter(models.Notification.department_target == scope)

        count = q.scalar() or 0
        return dict(notifications_unread_count=count)
    finally:
        db.close()

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
        now_utc = datetime.now(timezone.utc)

        alerts = get_alerts_for_user(db, current_user, include_hidden=True) or []

        # Summary para pintar "hoy": SOLO cuenta reasons open (o snooze vencido)
        summary = {"notice": 0, "warning": 0, "critical": 0}

        for a in alerts:
            a_sev = (a.get("severity") or "notice").strip().lower()
            reasons = a.get("reasons") or []

            if reasons:
                for r in reasons:
                    if not reason_counts_for_calendar(r, now_utc):
                        continue
                    sev = (r.get("severity") or a_sev or "notice").strip().lower()
                    if sev not in summary:
                        sev = "notice"
                    summary[sev] += 1
            else:
                # alertas sin reasons: cuentan como 1
                sev = a_sev if a_sev in summary else "notice"
                summary[sev] += 1

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

        # Alertas (nuevo sistema con states)
        alerts = get_alerts_for_user(db, current_user, include_hidden=False) or []

        # Summary para pintar "hoy" en el calendario
        now_utc = datetime.now(timezone.utc)
        alerts_all = get_alerts_for_user(db, current_user, include_hidden=True) or []
        alerts_summary = {"notice": 0, "warning": 0, "critical": 0}
        for a in alerts_all:
            a_sev = (a.get("severity") or "notice").strip().lower()
            reasons = a.get("reasons") or []
            if reasons:
                for r in reasons:
                    if not reason_counts_for_calendar(r, now_utc):
                        continue
                    sev = (r.get("severity") or a_sev or "notice").strip().lower()
                    if sev not in alerts_summary:
                        sev = "notice"
                    alerts_summary[sev] += 1
            else:
                sev = a_sev if a_sev in alerts_summary else "notice"
                alerts_summary[sev] += 1

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

def _contains(text: str | None, q: str) -> bool:
    if not q:
        return True
    if not text:
        return False
    return q.lower() in text.lower()


def _alert_has_type(alert: dict, type_q: str) -> bool:
    if not type_q:
        return True

    type_q = type_q.strip().lower()
    keys = [k.lower() for k in (alert.get("keys") or [])]

    if type_q in keys:
        return True

    if type_q.endswith("_"):
        return any(k.startswith(type_q) for k in keys)

    if type_q in ("tco", "itc", "admin"):
        return any(k.startswith(type_q + "_") for k in keys)

    return any(type_q in k for k in keys)


def _responsible_matches(course, q: str) -> bool:
    if not q:
        return True
    if not course:
        return False

    q = q.lower().strip()
    resp = getattr(course, "responsible", None)
    if not resp:
        return False

    fields = [
        getattr(resp, "username", None),
        getattr(resp, "email", None),
        getattr(resp, "name", None),
        getattr(resp, "surname", None),
    ]
    hay = " ".join(str(f) for f in fields if f)
    return q in hay.lower()


def filter_alerts(alerts: list[dict], severity=None, type_q=None, q=None, responsible=None):
    sev = (severity or "").strip().lower()
    type_q = (type_q or "").strip()
    q = (q or "").strip()
    responsible = (responsible or "").strip()

    out = []
    for a in alerts:
        if sev and (a.get("severity") or "").lower() != sev:
            continue

        if type_q and not _alert_has_type(a, type_q):
            continue

        if q:
            msg_ok = _contains(a.get("message"), q)
            reasons_ok = any(
                _contains((r or {}).get("text"), q)
                for r in (a.get("reasons") or [])
            )

            course = a.get("course")
            course_name = (
                getattr(course, "name", None)
                or getattr(course, "course", None)
                if course else None
            )
            course_ok = _contains(course_name, q)

            if not (msg_ok or reasons_ok or course_ok):
                continue

        course = a.get("course")
        if responsible and not _responsible_matches(course, responsible):
            continue

        out.append(a)

    return out


@bp.app_context_processor
def inject_notifications_summary():
    db = SessionLocal()
    try:
        if not current_user.is_authenticated:
            return dict(notifications_summary={"unread": 0})

        role = (getattr(current_user, "role", "") or "").strip().lower()
        dept = (getattr(current_user, "department", "") or "").strip()

        q = (
            db.query(models.Notification.id)
              .filter(models.Notification.active.is_(True))
              .filter(models.Notification.read_at.is_(None))
              .filter(models.Notification.status == "open")
        )

        # admin ve todo, el resto solo su dept
        if "admin" not in role:
            if not dept:
                return dict(notifications_summary={"unread": 0})
            q = q.filter(models.Notification.department_target == dept)

        unread = q.count()
        return dict(notifications_summary={"unread": unread})
    finally:
        db.close()