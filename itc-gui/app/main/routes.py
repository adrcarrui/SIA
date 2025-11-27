from flask import render_template, session
from flask_login import login_required
from . import bp
from app.db import SessionLocal
from app.scripts.get_overdue_assignments import get_overdue_assignments
from app.models import User, Device, Course, Assignment, Movements
from sqlalchemy import func, case  # <-- añade esto


@bp.route("/")
@login_required
def index():
    db = SessionLocal()
    try:
        # Overdue usando la misma sesión
        overdue = get_overdue_assignments(db)

        # Totales globales usando SessionLocal (no Model.query)
        total_users = db.query(User).count()
        total_devices = db.query(Device).count()
        total_courses = db.query(Course).count()
        total_assignments = db.query(Assignment).count()
        total_movements = db.query(Movements).count()

        # Total de devices asignados
        assigned_devices = (
            db.query(Device)
            .filter(Device.status == "assigned")
            .count()
        )

        # Stats por tipo de device
        raw_stats = (
            db.query(
                Device.type.label("type"),
                func.count(Device.id).label("total"),
                func.sum(
                    case(
                        (Device.status == "assigned", 1),
                        else_=0
                    )
                ).label("assigned"),
            )
            .group_by(Device.type)
            .order_by(Device.type)
            .all()
        )

        device_stats = []
        for s in raw_stats:
            assigned = s.assigned or 0
            ratio = (assigned / s.total * 100) if s.total else 0
            device_stats.append({
                "type": s.type,
                "total": s.total,
                "assigned": assigned,
                "ratio": ratio,
            })

    finally:
        db.close()

    return render_template(
        "index.html",
        overdue=overdue,
        total_users=total_users,
        total_devices=total_devices,
        total_courses=total_courses,
        total_assignments=total_assignments,
        total_movements=total_movements,
        assigned_devices=assigned_devices,
        device_stats=device_stats,
    )
