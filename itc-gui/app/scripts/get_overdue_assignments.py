from datetime import date
from collections import defaultdict
from app.models import Assignment, Course, Device
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import joinedload
OVERDUE_7_DAYS = 7


def get_overdue_assignments(db):
    """
    Versión simple, si la sigues usando en algún sitio.
    """
    today = date.today()

    rows = (
        db.query(Assignment, Course)
        .join(Course, Assignment.course_id == Course.id)
        .filter(
            Assignment.status == "active",
            Course.end_date != None,
            Course.end_date < today,
        )
        .all()
    )

    result = []
    for assignment, course in rows:
        days_late = (today - course.end_date).days

        if days_late <= 0:
            overdue_level = "active"
        elif days_late <= OVERDUE_7_DAYS:
            overdue_level = "overdue_1"
        else:
            overdue_level = "overdue_2"

        result.append({
            "assignment": assignment,
            "course": course,
            "device": assignment.device,
            "days_late": days_late,
            "overdue_level": overdue_level,
        })

    return result


def get_cards_vs_trainees_alerts(db):
    """
    Devuelve una lista de alertas para cursos que:
      - tienen trainees definidos
      - NO han terminado aún (end_date es NULL o >= hoy)
      - y cuyo nº de tarjetas activas != nº de trainees

    Cada elemento:
      {
        "course": Course,
        "assigned": int,
        "trainees": int,
        "diff": int,  # trainees - assigned
        "type": "cards_missing" | "cards_extra",
        "responsible": User | None
      }
    """
    today = date.today()

    rows = (
        db.query(
            Course,
            func.count(Assignment.id).label("assigned"),
        )
        .outerjoin(
            Assignment,
            (Assignment.course_id == Course.id)
            & (Assignment.released_at.is_(None))  # solo tarjetas activas
        )
        .filter(
            Course.trainees.isnot(None),
            or_(
                Course.end_date.is_(None),
                Course.end_date >= today,   # solo cursos actuales / futuros
            ),
        )
        .group_by(Course.id)
        .all()
    )

    alerts = []
    for course, assigned in rows:
        assigned = assigned or 0
        trainees = course.trainees or 0

        if assigned == trainees:
            continue  # nada que avisar

        diff = trainees - assigned

        alerts.append({
            "course": course,
            "assigned": assigned,
            "trainees": trainees,
            "diff": diff,
            "type": "cards_missing" if diff > 0 else "cards_extra",
            "responsible": getattr(course, "responsible", None),
        })

    return alerts


def get_overdue_course_alerts(db):
    """
    Devuelve una lista de dicts:
      - type: 'overdue_1' (<= 7 días) o 'overdue_2' (> 7 días)
      - course
      - days_late
      - cards_count
      - card_names
      - responsible (Course.responsible si existe)

    Solo cuenta assignments con released_at IS NULL y status 'active'.

    Además:
      - Si el curso está en overdue_2, marcamos sus devices asignados como 'lost'.
    """
    today = date.today()

    rows = (
        db.query(Assignment, Course, Device)
        .join(Course, Assignment.course_id == Course.id)
        .join(Device, Assignment.device_id == Device.id)
        .options(
            joinedload(Assignment.course).joinedload(Course.responsible)
        )
        .filter(
            Assignment.status == "active",
            Assignment.released_at.is_(None),   # SOLO SIGUEN FUERA
            Course.end_date != None,
            Course.end_date < today,
        )
        .all()
    )

    alerts = []
    by_course = {}

    for assignment, course, device in rows:
        days_late = (today - course.end_date).days
        key = course.id

        if key not in by_course:
            by_course[key] = {
                "course": course,
                "days_late": days_late,
                "devices": [],
            }

        by_course[key]["devices"].append(device)
        # por si hay varias asignaciones, nos quedamos con el máximo retraso
        by_course[key]["days_late"] = max(by_course[key]["days_late"], days_late)

    for data in by_course.values():
        course = data["course"]
        days_late = data["days_late"]
        devices = data["devices"]
        cards_count = len(devices)
        card_names = [d.name or f"Device #{d.id}" for d in devices]

        if days_late <= OVERDUE_7_DAYS:
            alert_type = "overdue_1"
        else:
            alert_type = "overdue_2"
            # aquí marcamos las tarjetas como 'lost'
            for d in devices:
                if getattr(d, "status", None) == "assigned":
                    d.status = "lost"

        alerts.append({
            "type": alert_type,
            "course": course,
            "days_late": days_late,
            "cards_count": cards_count,
            "card_names": card_names,
            "responsible": getattr(course, "responsible", None),
        })

    return alerts