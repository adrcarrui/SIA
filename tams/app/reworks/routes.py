from datetime import datetime, timedelta

from flask import render_template, request
from flask_login import login_required
from sqlalchemy import func, or_

from . import bp
from app.db import SessionLocal
import app.models as models


def _parse_date(value):
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _base_reworks_query(db):
    return (
        db.query(
            models.CourseRework,
            models.Course,
            models.User,
        )
        .join(models.Course, models.Course.id == models.CourseRework.course_id)
        .outerjoin(models.User, models.User.id == models.CourseRework.created_by)
    )


def _apply_rework_filters(query, args):
    q = (args.get("q") or "").strip()
    status = (args.get("status") or "").strip()
    date_from = _parse_date(args.get("date_from"))
    date_to = _parse_date(args.get("date_to"))

    if q:
        term = f"%{q}%"
        query = query.filter(
            or_(
                models.Course.course.ilike(term),
                models.Course.name.ilike(term),
                models.Course.client.ilike(term),
                models.CourseRework.notes.ilike(term),
                models.User.username.ilike(term),
                models.User.email.ilike(term),
            )
        )

    if status == "active":
        query = query.filter(models.CourseRework.cancelled_at.is_(None))
    elif status == "cancelled":
        query = query.filter(models.CourseRework.cancelled_at.isnot(None))

    if date_from:
        query = query.filter(models.CourseRework.rework_date >= date_from)

    if date_to:
        query = query.filter(models.CourseRework.rework_date <= date_to)

    return query


@bp.route("/", methods=["GET"])
@login_required
def index():
    db = SessionLocal()

    try:
        q = (request.args.get("q") or "").strip()
        status = (request.args.get("status") or "").strip()
        date_from = (request.args.get("date_from") or "").strip()
        date_to = (request.args.get("date_to") or "").strip()

        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)

        if page < 1:
            page = 1

        if per_page not in [10, 20, 50, 100]:
            per_page = 20

        query = _base_reworks_query(db)
        query = _apply_rework_filters(query, request.args)

        total = query.count()

        rows = (
            query
            .order_by(models.CourseRework.rework_date.desc(), models.CourseRework.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        has_prev = page > 1
        has_next = page * per_page < total

        # =========================
        # Métricas generales
        # =========================
        filtered_query = _apply_rework_filters(_base_reworks_query(db), request.args)

        filtered_rows = filtered_query.all()

        active_count = 0
        cancelled_count = 0
        affected_courses = set()

        for rework, course, user in filtered_rows:
            affected_courses.add(course.id)

            if rework.cancelled_at is None:
                active_count += 1
            else:
                cancelled_count += 1

        total_count = active_count + cancelled_count

        # =========================
        # Gráfica mensual
        # Solo retrabajos activos
        # =========================
        monthly_query = (
            db.query(
                func.date_trunc("month", models.CourseRework.rework_date).label("month"),
                func.count(models.CourseRework.id).label("total"),
            )
            .join(models.Course, models.Course.id == models.CourseRework.course_id)
            .outerjoin(models.User, models.User.id == models.CourseRework.created_by)
            .filter(models.CourseRework.cancelled_at.is_(None))
        )

        monthly_query = _apply_rework_filters(monthly_query, request.args)

        monthly_rows = (
            monthly_query
            .group_by("month")
            .order_by("month")
            .all()
        )

        chart_labels = []
        chart_values = []

        for month, count in monthly_rows:
            if month:
                chart_labels.append(month.strftime("%Y-%m"))
                chart_values.append(int(count or 0))

        return render_template(
            "reworks/index.html",
            rows=rows,
            total=total,
            page=page,
            per_page=per_page,
            has_prev=has_prev,
            has_next=has_next,

            q=q,
            filter_status=status,
            filter_date_from=date_from,
            filter_date_to=date_to,

            total_count=total_count,
            active_count=active_count,
            cancelled_count=cancelled_count,
            affected_courses_count=len(affected_courses),

            chart_labels=chart_labels,
            chart_values=chart_values,
        )

    finally:
        db.close()

@bp.route("/print", methods=["GET"])
@login_required
def print_report():
    db = SessionLocal()

    try:
        q = (request.args.get("q") or "").strip()
        status = (request.args.get("status") or "").strip()
        date_from = (request.args.get("date_from") or "").strip()
        date_to = (request.args.get("date_to") or "").strip()

        query = _base_reworks_query(db)
        query = _apply_rework_filters(query, request.args)

        rows = (
            query
            .order_by(
                models.CourseRework.rework_date.desc(),
                models.CourseRework.created_at.desc()
            )
            .all()
        )

        active_count = 0
        cancelled_count = 0
        affected_courses = set()

        for rework, course, user in rows:
            affected_courses.add(course.id)

            if rework.cancelled_at is None:
                active_count += 1
            else:
                cancelled_count += 1

        total_count = active_count + cancelled_count

        monthly_query = (
            db.query(
                func.date_trunc("month", models.CourseRework.rework_date).label("month"),
                func.count(models.CourseRework.id).label("total"),
            )
            .join(models.Course, models.Course.id == models.CourseRework.course_id)
            .outerjoin(models.User, models.User.id == models.CourseRework.created_by)
            .filter(models.CourseRework.cancelled_at.is_(None))
        )

        monthly_query = _apply_rework_filters(monthly_query, request.args)

        monthly_rows = (
            monthly_query
            .group_by("month")
            .order_by("month")
            .all()
        )

        monthly_data = []
        max_monthly_value = 0

        for month, count in monthly_rows:
            value = int(count or 0)
            max_monthly_value = max(max_monthly_value, value)

            monthly_data.append({
                "label": month.strftime("%Y-%m") if month else "—",
                "value": value,
            })

        return render_template(
            "reworks/print.html",
            rows=rows,

            q=q,
            filter_status=status,
            filter_date_from=date_from,
            filter_date_to=date_to,

            total_count=total_count,
            active_count=active_count,
            cancelled_count=cancelled_count,
            affected_courses_count=len(affected_courses),

            monthly_data=monthly_data,
            max_monthly_value=max_monthly_value,

            generated_at=datetime.now(),
        )

    finally:
        db.close()