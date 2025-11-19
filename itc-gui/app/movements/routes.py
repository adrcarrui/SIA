from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, cast, String
from . import bp
from app.db import SessionLocal
from app.models import Movements, User  # ajusta nombres si los tuyos son distintos


@bp.route("/", methods=["GET"])
@login_required
def index():
    db = SessionLocal()

    # Filtro de búsqueda
    q = (request.args.get("q") or "").strip()

    # Paginación
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = (
        db.query(Movements)
        .options(joinedload(Movements.user))
        .order_by(Movements.created_at.desc())
    )

    if q:
        term = f"%{q}%"
        query = query.filter(
            or_(
                Movements.action.ilike(term),
                Movements.entity_type.ilike(term),
                Movements.description.ilike(term),
                Movements.user_agent.ilike(term),
                cast(Movements.entity_id, String).ilike(term),
                Movements.user.has(
                    or_(
                        User.username.ilike(term),
                        User.email.ilike(term),
                    )
                ),
            )
        )

    total = query.count()

    movements = (
        query
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    has_prev = page > 1
    has_next = page * per_page < total

    return render_template(
        "movements/index.html",
        movements=movements,
        total=total,
        q=q,
        page=page,
        per_page=per_page,
        has_prev=has_prev,
        has_next=has_next,
    )
