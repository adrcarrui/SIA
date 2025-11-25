from datetime import date
from collections import defaultdict
from app.models import Assignment, Course, Device

OVERDUE_7_DAYS=7

def get_overdue_assignments(db):
    today = date.today()

    # 1) Traemos TODOS los assignments activos con curso vencido
    rows = (
        db.query(Assignment, Course, Device)
        .join(Course, Assignment.course_id == Course.id)
        .join(Device, Assignment.device_id == Device.id)
        .filter(
            Assignment.status == "active",
            Course.end_date != None,
            Course.end_date < today,
        )
        .all()
    )

    # 2) Agrupamos devices por curso
    devices_by_course = defaultdict(list)

    for assignment, course, device in rows:
        devices_by_course[course.id].append(device)

    # 3) Construimos el resultado por cada fila (assignment concreto)
    result = []
    for assignment, course, device in rows:
        days_late = (today - course.end_date).days

        if days_late <= 0:
            overdue_level = "active"
        elif days_late <= OVERDUE_7_DAYS:
            overdue_level = "overdue_1"
        else:
            overdue_level = "overdue_2"

        # Devices asociados a ESTE curso (según lo que ya hemos agrupado)
        course_devices = devices_by_course[course.id]
        cards_count = len(course_devices)
        card_names = [
            (d.name or f"Device #{d.id}")
            for d in course_devices
        ]

        result.append({
            "assignment": assignment,
            "course": course,
            "device": device,
            "days_late": days_late,
            "overdue_level": overdue_level,
            "cards_count": cards_count,
            "card_names": card_names,
        })

    return result
