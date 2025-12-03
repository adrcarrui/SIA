from math import ceil
from flask import render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from . import bp
from app.db import SessionLocal
from sqlalchemy.orm import joinedload
import app.models as models
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime, timedelta
from app.scripts import log_movement
from app.models import Assignment, Course, Device, User

PER_PAGE = 20  # ajusta a tu gusto

# Estados TCO (negocio)
COURSE_TCO_STATUSES = ["planned", "active", "finished", "cancelled"]

# Estados ITC (soporte)
COURSE_ITC_STATUSES = [
    "start",
    "cancel or error",
    "completed",
    "delivered",
    "end",
    "collected",
    "RT delivered",
    "loan",
    "MSN loaded",
    "MSN delivered",
]

# Lista combinada para filtros en el index
COURSE_STATUSES = sorted(set(COURSE_TCO_STATUSES + COURSE_ITC_STATUSES))


def normalize_field(value: str):
    v = (value or "").strip()
    if not v:
        return None
    if v.lower() == "none":
        return None
    return v


@bp.route("/")
@login_required
def index():
    q = (request.args.get("q") or "").strip()
    page = max(int(request.args.get("page", 1)), 1)
    per_page = int(request.args.get("per_page", PER_PAGE))

    # Column filters
    course_code = (request.args.get("course") or "").strip()
    name        = (request.args.get("name") or "").strip()
    client      = (request.args.get("client") or "").strip()
    status      = (request.args.get("status") or "").strip()
    trainees_s  = (request.args.get("trainees") or "").strip()
    notes       = (request.args.get("notes") or "").strip()
    start_str   = (request.args.get("start_date") or "").strip()
    end_str     = (request.args.get("end_date") or "").strip()

    db = SessionLocal()
    try:
        qry = db.query(models.Course)

        # Búsqueda global
        if q:
            like = f"%{q}%"
            qry = qry.filter(
                or_(
                    models.Course.course.ilike(like),
                    models.Course.name.ilike(like),
                    getattr(models.Course, "notes", models.Course.name).ilike(like),
                )
            )

        # Filtros por columna (AND)
        if course_code:
            qry = qry.filter(models.Course.course.ilike(f"%{course_code}%"))

        if name:
            qry = qry.filter(models.Course.name.ilike(f"%{name}%"))

        if client:
            qry = qry.filter(models.Course.client.ilike(f"%{client}%"))

        if status:
            # filtramos por estado TCO o ITC que coincidan con el valor
            qry = qry.filter(
                or_(
                    models.Course.status_tco == status,
                    models.Course.status_itc == status,
                )
            )

        if trainees_s:
            try:
                trainees_val = int(trainees_s)
                qry = qry.filter(models.Course.trainees == trainees_val)
            except ValueError:
                pass

        if notes:
            qry = qry.filter(models.Course.notes.ilike(f"%{notes}%"))

        if start_str:
            try:
                start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
                qry = qry.filter(models.Course.start_date == start_date)
            except ValueError:
                pass

        if end_str:
            try:
                end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
                qry = qry.filter(models.Course.end_date == end_date)
            except ValueError:
                pass

        total = qry.count()
        pages = max(ceil(total / per_page), 1)
        courses = (
            qry.order_by(models.Course.id.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        return render_template(
            "courses/index.html",
            page_title="TCO GUI",
            courses=courses,
            # búsqueda global
            q=q,
            # paginación
            page=page,
            pages=pages,
            total=total,
            per_page=per_page,
            has_prev=page > 1,
            has_next=page < pages,
            # filtros por columna (para los inputs)
            filter_course=course_code,
            filter_name=name,
            filter_client=client,
            filter_status=status,
            filter_trainees=trainees_s,
            filter_notes=notes,
            filter_start_date=start_str,
            filter_end_date=end_str,
            COURSE_STATUSES=COURSE_STATUSES,
        )
    finally:
        db.close()


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_course():
    from datetime import date

    def to_date(s):
        s = (s or "").strip()
        return date.fromisoformat(s) if s else None

    db = SessionLocal()
    try:
        if request.method == "POST":
            course = (request.form.get("course") or "").strip()
            name = (request.form.get("name") or "").strip()

            # estados separados
            status_tco = (request.form.get("status_tco") or "planned").strip() or "planned"
            status_itc = (request.form.get("status_itc") or "start").strip() or "start"

            # saneo contra listas
            if status_tco not in COURSE_TCO_STATUSES:
                status_tco = "planned"
            if status_itc not in COURSE_ITC_STATUSES:
                status_itc = "start"

            # ITC (no admin) no puede decidir el estado TCO
            actor_role = (getattr(current_user, "role", "") or "").lower()
            actor_dept = (getattr(current_user, "department", "") or "")
            is_itc_only = (actor_dept == "ITC support" and actor_role != "admin")
            if is_itc_only:
                status_tco = "planned"

            notes = (request.form.get("notes") or "").strip()
            client = (request.form.get("client") or "").strip()

            start_dt = to_date(request.form.get("start_date"))
            end_dt = to_date(request.form.get("end_date"))

            # responsable: combo limitado a TCO supervisor/employee,
            # pero por defecto el responsable será el que crea el curso
            resp_raw = (request.form.get("responsible_id") or "").strip()
            responsible_id = None

            if resp_raw:
                try:
                    candidate_id = int(resp_raw)
                except ValueError:
                    candidate_id = None

                if candidate_id:
                    resp_user = db.query(models.User).get(candidate_id)
                    if (
                        resp_user
                        and resp_user.active
                        and resp_user.department == "TCO"
                        and resp_user.role in ("supervisor", "employee")
                    ):
                        responsible_id = resp_user.id
                    else:
                        flash(
                            "Selected responsible is not a valid TCO supervisor/employee.",
                            "warning",
                        )

            # Si no se ha elegido un responsable válido, por defecto
            # responsable = usuario que crea el curso
            if not responsible_id and current_user.is_authenticated:
                responsible_id = current_user.id

            # trainees entero, NOT NULL
            t_raw = (request.form.get("trainees") or "").strip()
            try:
                trainees = int(t_raw)
                if trainees < 0:
                    trainees = 0
            except ValueError:
                trainees = 0

            # Comprobación mínima: course o name
            if not course and not name:
                flash("You must fill either 'Course' or 'Name'.", "warning")

                responsibles = (
                    db.query(models.User)
                    .filter(
                        models.User.department == "TCO",
                        models.User.active.is_(True),
                        models.User.role.in_(["supervisor", "employee"]),
                    )
                    .order_by(models.User.name.asc(), models.User.surname.asc())
                    .all()
                )

                return render_template(
                    "courses/form.html",
                    page_title="New course",
                    c=None,
                    COURSE_TCO_STATUSES=COURSE_TCO_STATUSES,
                    COURSE_ITC_STATUSES=COURSE_ITC_STATUSES,
                    responsibles=responsibles,
                )

            new_course = models.Course(
                course=course or None,
                name=name or None,
                status_tco=status_tco,
                status_itc=status_itc,
                notes=notes or None,
                trainees=trainees,
                start_date=start_dt,
                end_date=end_dt,
                responsible_id=responsible_id,
                client=client or None,
            )
            db.add(new_course)
            db.flush()

            log_movement(
                db,
                user_id=getattr(current_user, "id", None),
                entity_type="course",
                entity_id=new_course.id,
                action="create",
                before_data=None,
                after_data={
                    "id": new_course.id,
                    "course": new_course.course,
                    "name": new_course.name,
                    "start_date": new_course.start_date.isoformat()
                    if new_course.start_date
                    else None,
                    "end_date": new_course.end_date.isoformat()
                    if new_course.end_date
                    else None,
                    "trainees": new_course.trainees,
                    "status_tco": new_course.status_tco,
                    "status_itc": new_course.status_itc,
                    "notes": new_course.notes,
                    "responsible_id": new_course.responsible_id,
                    "client": new_course.client,
                },
                description=f"Course '{new_course.course or new_course.name}' created",
                success=True,
                user_agent=request.user_agent.string,
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash(
                    "Course could not be created. Check unique constraints.",
                    "danger",
                )

                responsibles = (
                    db.query(models.User)
                    .filter(
                        models.User.department == "TCO",
                        models.User.active.is_(True),
                        models.User.role.in_(["supervisor", "employee"]),
                    )
                    .order_by(models.User.name.asc(), models.User.surname.asc())
                    .all()
                )

                return render_template(
                    "courses/form.html",
                    page_title="New course",
                    c=None,
                    COURSE_TCO_STATUSES=COURSE_TCO_STATUSES,
                    COURSE_ITC_STATUSES=COURSE_ITC_STATUSES,
                    responsibles=responsibles,
                )

            flash("Course created.", "success")
            return redirect(url_for("courses.index"))

        # GET
        responsibles = (
            db.query(models.User)
            .filter(
                models.User.department == "TCO",
                models.User.active.is_(True),
                models.User.role.in_(["supervisor", "employee"]),
            )
            .order_by(models.User.name.asc(), models.User.surname.asc())
            .all()
        )

        return render_template(
            "courses/form.html",
            page_title="New course",
            c=None,
            COURSE_TCO_STATUSES=COURSE_TCO_STATUSES,
            COURSE_ITC_STATUSES=COURSE_ITC_STATUSES,
            responsibles=responsibles,
        )
    finally:
        db.close()


@bp.route("/<int:course_id>/edit", methods=["GET", "POST"])
@login_required
def edit_course(course_id):
    db = SessionLocal()
    try:
        c = db.query(models.Course).get(course_id)
        if not c:
            flash("Course not found.", "danger")
            return redirect(url_for("courses.index"))

        if request.method == "POST":
            # Snapshot ANTES de tocar nada
            before_data = {
                "id": c.id,
                "course": c.course,
                "name": c.name,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "trainees": c.trainees,
                "status_tco": c.status_tco,
                "status_itc": c.status_itc,
                "notes": c.notes,
                "responsible_id": c.responsible_id,
                "client": c.client,
            }

            course_code = normalize_field((request.form.get("course") or ""))
            name = normalize_field((request.form.get("name") or ""))
            client = normalize_field((request.form.get("client") or ""))

            start_str = (request.form.get("start_date") or "").strip()
            end_str = (request.form.get("end_date") or "").strip()
            trainees = (request.form.get("trainees") or "").strip()
            notes = (request.form.get("notes") or "").strip()

            # estados separados
            status_tco = (request.form.get("status_tco") or "").strip() or c.status_tco or "planned"
            status_itc = (request.form.get("status_itc") or "").strip() or c.status_itc or "start"

            if status_tco not in COURSE_TCO_STATUSES:
                flash("Invalid TCO status. 'planned' will be used.", "warning")
                status_tco = "planned"

            if status_itc not in COURSE_ITC_STATUSES:
                flash("Invalid ITC status. 'start' will be used.", "warning")
                status_itc = "start"

            # ITC (no admin) NO puede tocar el status_tco
            actor_role = (getattr(current_user, "role", "") or "").lower()
            actor_dept = (getattr(current_user, "department", "") or "")
            is_itc_only = (actor_dept == "ITC support" and actor_role != "admin")
            if is_itc_only:
                status_tco = c.status_tco or "planned"

            if not course_code and not name:
                flash("You must fill either 'Course' or 'Name'.", "warning")

                responsibles = (
                    db.query(models.User)
                    .filter(
                        models.User.department == "TCO",
                        models.User.active.is_(True),
                        models.User.role.in_(["supervisor", "employee"]),
                    )
                    .order_by(models.User.name.asc(), models.User.surname.asc())
                    .all()
                )

                return render_template(
                    "courses/form.html",
                    page_title="Edit course",
                    c=c,
                    COURSE_TCO_STATUSES=COURSE_TCO_STATUSES,
                    COURSE_ITC_STATUSES=COURSE_ITC_STATUSES,
                    responsibles=responsibles,
                )

            def parse_date(s):
                if not s:
                    return None
                try:
                    return datetime.strptime(s, "%Y-%m-%d").date()
                except ValueError:
                    return None

            start_date = parse_date(start_str)
            end_date = parse_date(end_str)

            try:
                trainees_val = int(trainees) if trainees else None
            except ValueError:
                trainees_val = None

            # Aplicar cambios
            c.course = course_code
            c.name = name or None
            c.client = client or None
            c.start_date = start_date
            c.end_date = end_date
            c.trainees = trainees_val
            c.status_tco = status_tco
            c.status_itc = status_itc
            c.notes = notes or None

            # responsable (solo TCO supervisor/employee si se cambia)
            resp_raw = (request.form.get("responsible_id") or "").strip()
            if resp_raw:
                try:
                    candidate_id = int(resp_raw)
                except ValueError:
                    candidate_id = None

                if candidate_id:
                    resp_user = db.query(models.User).get(candidate_id)
                    if (
                        resp_user
                        and resp_user.active
                        and resp_user.department == "TCO"
                        and resp_user.role in ("supervisor", "employee")
                    ):
                        c.responsible_id = resp_user.id
                    else:
                        flash(
                            "Selected responsible is not a valid TCO supervisor/employee.",
                            "warning",
                        )
            # Si va vacío, no tocamos c.responsible_id

            db.flush()

            after_data = {
                "id": c.id,
                "course": c.course,
                "name": c.name,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "trainees": c.trainees,
                "status_tco": c.status_tco,
                "status_itc": c.status_itc,
                "notes": c.notes,
                "responsible_id": c.responsible_id,
                "client": c.client,
            }

            log_movement(
                db,
                user_id=getattr(current_user, "id", None),
                entity_type="course",
                entity_id=c.id,
                action="update",
                before_data=before_data,
                after_data=after_data,
                description=f"Course '{c.course or c.name}' updated",
                success=True,
                user_agent=request.user_agent.string,
            )

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash(
                    "Course could not be updated. Check unique constraints.",
                    "danger",
                )

                responsibles = (
                    db.query(models.User)
                    .filter(
                        models.User.department == "TCO",
                        models.User.active.is_(True),
                        models.User.role.in_(["supervisor", "employee"]),
                    )
                    .order_by(models.User.name.asc(), models.User.surname.asc())
                    .all()
                )

                return render_template(
                    "courses/form.html",
                    page_title="Edit course",
                    c=c,
                    COURSE_TCO_STATUSES=COURSE_TCO_STATUSES,
                    COURSE_ITC_STATUSES=COURSE_ITC_STATUSES,
                    responsibles=responsibles,
                )

            flash("Course updated.", "success")
            return redirect(url_for("courses.index"))

        # GET
        responsibles = (
            db.query(models.User)
            .filter(
                models.User.department == "TCO",
                models.User.active.is_(True),
                models.User.role.in_(["supervisor", "employee"]),
            )
            .order_by(models.User.name.asc(), models.User.surname.asc())
            .all()
        )

        return render_template(
            "courses/form.html",
            page_title="Edit course",
            c=c,
            COURSE_TCO_STATUSES=COURSE_TCO_STATUSES,
            COURSE_ITC_STATUSES=COURSE_ITC_STATUSES,
            responsibles=responsibles,
        )
    finally:
        db.close()


@bp.route("/<int:course_id>/delete", methods=["POST"])
@login_required
def delete_course(course_id):
    db = SessionLocal()
    try:
        c = db.query(models.Course).get(course_id)
        if not c:
            flash("Course not found.", "danger")
            return redirect(url_for("courses.index"))

        before_data = {
            "id": c.id,
            "course": c.course,
            "name": c.name,
            "start_date": c.start_date.isoformat() if c.start_date else None,
            "end_date": c.end_date.isoformat() if c.end_date else None,
            "trainees": c.trainees,
            "status_tco": c.status_tco,
            "status_itc": c.status_itc,
            "notes": c.notes,
            "responsible_id": c.responsible_id,
        }

        db.delete(c)
        db.flush()

        log_movement(
            db,
            user_id=getattr(current_user, "id", None),
            entity_type="course",
            entity_id=course_id,
            action="delete",
            before_data=before_data,
            after_data=None,
            description=f"Course '{before_data['course']}' deleted",
            success=True,
            user_agent=request.user_agent.string,
        )

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash(
                "The course could not be deleted. It may be referenced in other records.",
                "danger",
            )
            return redirect(url_for("courses.index"))

        flash("Course deleted.", "success")
        return redirect(url_for("courses.index"))

    finally:
        db.close()


@bp.route("/calendar-data")
def calendar_data():
    """
    Devuelve los cursos cuyo rango [start_date, end_date] se solapa
    con el rango visible del calendario (from, to).
    """
    db = SessionLocal()
    try:
        start_str = request.args.get("from")
        end_str = request.args.get("to")

        if not start_str or not end_str:
            return jsonify([])

        start = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)

        courses = (
            db.query(models.Course)
            .filter(models.Course.start_date <= end)
            .filter(models.Course.end_date >= start)
            .all()
        )

        data = []
        for c in courses:
            if not c.start_date:
                continue
            data.append(
                {
                    "id": c.id,
                    "name": c.course or c.name,
                    "start_date": c.start_date.isoformat(),
                    "end_date": (c.end_date or c.start_date).isoformat(),
                    "status": c.auto_status,        # calculado
                    "status_tco": c.status_tco,    # raw
                    "status_itc": c.status_itc,    # raw
                    "trainees": c.trainees,
                    "detail_url": url_for("courses.detail_fragment", course_id=c.id),
                }
            )

        return jsonify(data)
    finally:
        db.close()


@bp.route("/<int:course_id>")
@login_required
def detail(course_id):
    db = SessionLocal()
    course = (
        db.query(Course)
        .options(
            joinedload(Course.assignments).joinedload(Assignment.device),
        )
        .get(course_id)
    )
    if not course:
        abort(404)

    update_assignment_overdue_status_for_course(db, course)

    active_assignments = [
        a
        for a in course.assignments
        if a.status in ("active", "overdue_1", "overdue_2")
        and a.device is not None
    ]

    return render_template(
        "courses/detail.html",
        course=course,
        active_assignments=active_assignments,
    )


@bp.route("/<int:course_id>/fragment")
@login_required
def detail_fragment(course_id):
    db = SessionLocal()
    course = (
        db.query(Course)
        .options(
            joinedload(Course.assignments).joinedload(Assignment.device),
        )
        .get(course_id)
    )
    if not course:
        abort(404)

    update_assignment_overdue_status_for_course(db, course)

    active_assignments = [
        a
        for a in course.assignments
        if a.status in ("active", "overdue_1", "overdue_2")
        and a.device is not None
    ]

    return render_template(
        "courses/_detail_fragment.html",
        course=course,
        active_assignments=active_assignments,
    )


# Umbral de días de retraso para overdue_1
OVERDUE_1_DAYS = 7  # 1..7 días -> overdue_1


def update_assignment_overdue_status_for_course(db, course):
    """
    Actualiza Assignment.status para las asignaciones 'vivas' de un curso
    según la fecha de fin del curso y la fecha actual.
    """
    print("Llamada funcion update fecha")
    today = date.today()

    if not course.end_date:
        for a in course.assignments:
            if a.status in ("active", "overdue_1", "overdue_2"):
                a.status = "active"
                a.days_late = 0
        return

    days_late = (today - course.end_date).days

    for a in course.assignments:
        if a.status not in ("active", "overdue_1", "overdue_2"):
            continue

        if days_late <= 0:
            new_status = "active"
            dl = 0
        elif days_late <= OVERDUE_1_DAYS:
            new_status = "overdue_1"
            dl = days_late
        else:
            new_status = "overdue_2"
            dl = days_late

        a.status = new_status
        print("status: " + new_status)
        a.days_late = dl


@bp.route("/api/calendar-events")
@login_required
def api_calendar_events():
    db = SessionLocal()
    try:
        courses = db.query(Course).all()

        events = []
        for c in courses:
            if not c.start_date and not c.end_date:
                continue

            title = (
                (c.name or "").strip()
                or (c.course or "").strip()
                or f"Course #{c.id}"
            )
            detail_url = url_for("courses.detail_fragment", course_id=c.id)

            # Evento de INICIO (verde)
            if c.start_date:
                events.append(
                    {
                        "id": f"{c.id}-start",
                        "title": title,
                        "start": c.start_date.isoformat(),
                        "allDay": True,
                        "classNames": ["fc-course-start"],
                        "extendedProps": {
                            "course_id": c.id,
                            "status": c.auto_status,
                            "status_tco": c.status_tco,
                            "status_itc": c.status_itc,
                            "trainees": c.trainees,
                            "client": c.client,
                            "course_code": c.course,
                            "course_url": f"/courses/{c.id}",
                            "detail_url": detail_url,
                            "kind": "start",
                        },
                    }
                )

            # Evento de FIN (azul)
            if c.end_date and (not c.start_date or c.end_date != c.start_date):
                events.append(
                    {
                        "id": f"{c.id}-end",
                        "title": title,
                        "start": c.end_date.isoformat(),
                        "allDay": True,
                        "classNames": ["fc-course-end"],
                        "extendedProps": {
                            "course_id": c.id,
                            "status": c.auto_status,
                            "status_tco": c.status_tco,
                            "status_itc": c.status_itc,
                            "trainees": c.trainees,
                            "client": c.client,
                            "course_code": c.course,
                            "course_url": f"/courses/{c.id}",
                            "detail_url": detail_url,
                            "kind": "end",
                        },
                    }
                )

        return jsonify(events)
    finally:
        db.close()
