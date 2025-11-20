from datetime import date
from app.models import Assignment, Course, Device
from app.courses.routes import OVERDUE_1_DAYS  # o defines el número aquí también

def get_overdue_assignments(db):
    today = date.today()

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

    result = []
    for assignment, course, device in rows:
        days_late = (today - course.end_date).days

        if days_late <= 0:
            overdue_level = "active"
        elif days_late <= OVERDUE_1_DAYS:
            overdue_level = "overdue_1"
        else:
            overdue_level = "overdue_2"

        result.append({
            "assignment": assignment,
            "course": course,
            "device": device,
            "days_late": days_late,
            "overdue_level": overdue_level,
        })

    return result
