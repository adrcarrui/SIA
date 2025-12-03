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

    # Global search
    q = (request.args.get("q") or "").strip()

    # Pagination
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    # Column filters
    f_user        = (request.args.get("user") or "").strip()
    f_action      = (request.args.get("action") or "").strip()
    f_entity_type = (request.args.get("entity_type") or "").strip()
    f_description = (request.args.get("description") or "").strip()
    f_success     = (request.args.get("success") or "").strip()  # "1" / "0" / ""
    f_date_from   = (request.args.get("date_from") or "").strip()
    f_date_to     = (request.args.get("date_to") or "").strip()

    query = (
        db.query(Movements)
        .options(joinedload(Movements.user))
        .order_by(Movements.created_at.desc())
    )

    # Global q filter (lo que ya tenías)
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

    # Column filters (AND)
    if f_user:
        term = f"%{f_user}%"
        query = query.filter(
            Movements.user.has(
                or_(
                    User.username.ilike(term),
                    User.email.ilike(term),
                )
            )
        )

    if f_action:
        query = query.filter(Movements.action == f_action)

    if f_entity_type:
        query = query.filter(Movements.entity_type.ilike(f"%{f_entity_type}%"))

    if f_description:
        query = query.filter(Movements.description.ilike(f"%{f_description}%"))

    if f_success == "1":
        query = query.filter(Movements.success.is_(True))
    elif f_success == "0":
        query = query.filter(Movements.success.is_(False))

    from datetime import datetime, timedelta

    if f_date_from:
        try:
            start_dt = datetime.strptime(f_date_from, "%Y-%m-%d")
            query = query.filter(Movements.created_at >= start_dt)
        except ValueError:
            pass

    if f_date_to:
        try:
            end_dt = datetime.strptime(f_date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Movements.created_at < end_dt)
        except ValueError:
            pass

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
        # filters
        filter_user=f_user,
        filter_action=f_action,
        filter_entity_type=f_entity_type,
        filter_description=f_description,
        filter_success=f_success,
        filter_date_from=f_date_from,
        filter_date_to=f_date_to,
    )