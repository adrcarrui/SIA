# app/scripts/get_overdue_assignments.py

from datetime import date
from app.models import Assignment, Course, Device, AssetType
from sqlalchemy import func, or_, case
from sqlalchemy.orm import joinedload, aliased

OVERDUE_7_DAYS = 7


def get_cards_vs_trainees_alerts(db, managed_by: str | None = None):
    today = date.today()

    ParentAT = aliased(AssetType)

    cond = (
        AssetType.show_in_calendar.is_(True)
        & (
            (AssetType.code == "CARD")
            | (ParentAT.code == "CARD")
        )
    )
    if managed_by:
        cond = cond & (AssetType.managed_by_department == managed_by)

    assigned_count = func.sum(case((cond, 1), else_=0))

    q = (
        db.query(Course, assigned_count.label("assigned"))
        .outerjoin(
            Assignment,
            (Assignment.course_id == Course.id)
            & (Assignment.released_at.is_(None))
            & (func.lower(Assignment.status) == "active")
            & (Assignment.is_temporary.is_(False))
        )
        .outerjoin(Device, Assignment.device_id == Device.id)
        .outerjoin(AssetType, Device.asset_type_id == AssetType.id)
        .outerjoin(ParentAT, AssetType.parent_id == ParentAT.id)
        .filter(
            Course.trainees.isnot(None),
            or_(Course.end_date.is_(None), Course.end_date >= today),
        )
        .group_by(Course.id)
    )

    rows = q.all()

    alerts = []
    for course, assigned in rows:
        assigned = int(assigned or 0)
        trainees = int(course.trainees or 0)

        if assigned == trainees:
            continue

        diff = trainees - assigned

        alerts.append({
            "course": course,
            "assigned": assigned,
            "trainees": trainees,
            "diff": diff,
            "type": "cards_missing" if diff > 0 else "cards_extra",
            "responsible": getattr(course, "responsible", None),
        })
        
    rows = (
    db.query(Assignment.id, Assignment.status, Assignment.released_at, Device.id, AssetType.code, AssetType.show_in_calendar)
    .join(Device, Device.id == Assignment.device_id)
    .outerjoin(AssetType, AssetType.id == Device.asset_type_id)
    .filter(Assignment.course_id == 42)
        .all()
    )

    print("DEBUG ASSIGNMENTS course=42:", rows)

    return alerts



def get_overdue_course_alerts(db, managed_by: str | None = None):
    """
    Overdue alerts:
    - SOLO assignments activos (released_at NULL, status active)
    - SOLO devices cuyo AssetType.show_in_calendar=True
    - Si managed_by != None, filtra por AssetType.managed_by_department == managed_by

    Además:
      - Si overdue_2, marca los devices asignados como 'lost' (si estaban 'assigned').
    """
    today = date.today()

    q = (
        db.query(Assignment, Course, Device)
        .join(Course, Assignment.course_id == Course.id)
        .join(Device, Assignment.device_id == Device.id)
        .join(AssetType, Device.asset_type_id == AssetType.id)
        .options(joinedload(Assignment.course).joinedload(Course.responsible))
        .filter(
            Assignment.status == "active",
            Assignment.released_at.is_(None),
            Course.end_date.isnot(None),
            Course.end_date < today,
            AssetType.show_in_calendar.is_(True),
        )
    )

    if managed_by:
        q = q.filter(AssetType.managed_by_department == managed_by)

    rows = q.all()

    by_course = {}
    for assignment, course, device in rows:
        days_late = (today - course.end_date).days
        key = course.id

        if key not in by_course:
            by_course[key] = {"course": course, "days_late": days_late, "devices": []}

        by_course[key]["devices"].append(device)
        by_course[key]["days_late"] = max(by_course[key]["days_late"], days_late)

    alerts = []
    for data in by_course.values():
        course = data["course"]
        days_late = data["days_late"]
        devices = data["devices"]

        if days_late <= OVERDUE_7_DAYS:
            alert_type = "overdue_1"
        else:
            alert_type = "overdue_2"
            for d in devices:
                if getattr(d, "status", None) == "assigned":
                    d.status = "lost"

        alerts.append({
            "type": alert_type,
            "course": course,
            "days_late": days_late,
            "cards_count": len(devices),
            "card_names": [d.name or f"Device #{d.id}" for d in devices],
            "responsible": getattr(course, "responsible", None),
        })

    return alerts
