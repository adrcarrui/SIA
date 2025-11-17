# app/movements/routes.py  (o donde tengas el blueprint)

from flask import render_template, request
from . import bp
from app.db import SessionLocal
import app.models as models
from flask_login import login_required, current_user


@bp.route("/")
@login_required
def index():
    """
    Historial de auditoría: lista de movimientos ordenados por fecha descendente.
    """
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    db = SessionLocal()
    try:
        query = db.query(models.Movements).order_by(models.Movements.created_at.desc())

        total = query.count()
        movements = (
            query
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        return render_template(
            "movements/index.html",
            movements=movements,
            page=page,
            per_page=per_page,
            has_prev=page > 1,
            has_next=page * per_page < total,
            total=total,
        )
    finally:
        db.close()
