from flask import render_template, session
from flask_login import login_required
from . import bp
from app.db import SessionLocal
from app.scripts.get_overdue_assignments import get_overdue_assignments
from app.models import User, Device, Course, Assignment, Movements


@bp.route("/")
@login_required
def index():
    db = SessionLocal()
    
    try:
        overdue = get_overdue_assignments(db)
    finally:
        db.close()

    total_users = User.query.count()
    total_devices = Device.query.count()
    total_courses = Course.query.count()
    total_assignments = Assignment.query.count()
    total_movements = Movements.query.count()
    return render_template(
        "index.html",
        overdue=overdue,  # lista de dicts: {assignment, course, device, days_late, overdue_level}
        total_users=total_users,
        total_devices=total_devices,
        total_courses=total_courses,
        total_assignments=total_assignments,
        total_movements=total_movements,
    )


