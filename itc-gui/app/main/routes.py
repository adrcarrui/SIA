from flask import render_template, session
from flask_login import login_required
from . import bp
from app.db import SessionLocal
from app.scripts.get_overdue_assignments import get_overdue_assignments  # donde tengas la función


@login_required
@bp.route("/")
def index():
    db = SessionLocal()
    try:
        overdue = get_overdue_assignments(db)
    finally:
        db.close()

    return render_template(
        "main/index.html",
        overdue=overdue,  # lista de dicts: {assignment, course, device, days_late, overdue_level}
    )
