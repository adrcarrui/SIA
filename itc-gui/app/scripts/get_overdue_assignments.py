from datetime import date
from collections import defaultdict
from app.models import Assignment, Course, Device
from sqlalchemy import func

OVERDUE_7_DAYS = 7


def get_overdue_assignments(db):
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
    Devuelve una lista de alertas del tipo:
    - curso
    - nº de tarjetas asignadas (assignments activos)
    - nº de trainees
    - diff (+ faltan, - sobran)
    """

    rows = (
        db.query(
            Course,
            func.count(Assignment.id).label("assigned_cards"),
        )
        .outerjoin(
            Assignment,
            (Assignment.course_id == Course.id)
            & (Assignment.released_at.is_(None))
        )
        .group_by(Course.id)
        .all()
    )

    alerts = []
    for course, assigned_cards in rows:
        # si el curso no tiene trainees, no molestamos
        if course.trainees is None:
            continue

        diff = course.trainees - assigned_cards
        if diff == 0:
            continue  # todo cuadra, no es alerta

        level = "missing" if diff > 0 else "extra"

        alerts.append({
            "course": course,
            "assigned": assigned_cards,
            "trainees": course.trainees,
            "diff": diff,
            "level": level,
        })

    return alerts