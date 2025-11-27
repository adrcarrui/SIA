from math import ceil
from flask import render_template, request, redirect, url_for, flash,jsonify, abort
from flask_login import login_required, current_user
from . import bp
from app.db import SessionLocal
from sqlalchemy.orm import joinedload
import app.models as models
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime, timedelta
from app.scripts import log_movement
from app.models import Assignment, Course, Device

PER_PAGE = 20  # ajusta a tu gusto

COURSE_STATUSES = ["planned", "active", "finished", "cancelled"]

@bp.route("/")
@login_required
def index():
    q = (request.args.get("q") or "").strip()
    page = max(int(request.args.get("page", 1)), 1)

    db = SessionLocal()
    try:
        qry = db.query(models.Course)
        if q:
            like = f"%{q}%"
            qry = qry.filter(
                or_(
                    models.Course.course.ilike(like),
                    models.Course.name.ilike(like),
                    getattr(models.Course, "notes", models.Course.name).ilike(like),
                )
            )

        total = qry.count()
        pages = max(ceil(total / PER_PAGE), 1)
        courses = (qry.order_by(models.Course.id.asc())
                      .offset((page - 1) * PER_PAGE)
                      .limit(PER_PAGE)
                      .all())

        return render_template(
            "courses/index.html",
            page_title="TCO GUI",
            courses=courses,
            q=q,
            page=page, pages=pages, total=total,
            has_prev=page > 1, has_next=page < pages,
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

            course   = (request.form.get("course") or "").strip()
            name     = (request.form.get("name") or "").strip()
            status   = (request.form.get("status") or "planned").strip() or "planned"
            notes    = (request.form.get("notes") or "").strip()
            start_dt = to_date(request.form.get("start_date"))
            end_dt   = to_date(request.form.get("end_date"))

            # trainees entero, NOT NULL
            t_raw = (request.form.get("trainees") or "").strip()
            try:
                trainees = int(t_raw)
                if trainees < 0:
                    trainees = 0
            except ValueError:
                trainees = 0

            #if not course:
            #    flash("El campo 'course' es obligatorio.", "warning")
            #    return render_template("courses/form.html", page_title="New course", c=None)

            new_course = models.Course(
                course=course or None,
                name=name or None,
                status=status,          # evita None
                notes=notes or None,            # evita None
                trainees=trainees,      # evita None
                start_date=start_dt,    # nombre correcto
                end_date=end_dt,        # nombre correcto
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
                    "start_date": new_course.start_date.isoformat() if new_course.start_date else None,
                    "end_date": new_course.end_date.isoformat() if new_course.end_date else None,
                    "trainees": new_course.trainees,
                    "status": new_course.status,
                    "notes": new_course.notes,
                },
                description=f"Course '{new_course.course}' created",
                success=True,
                user_agent=request.user_agent.string,
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("No se pudo crear el curso. Revisa valores únicos.", "danger")
                return render_template(
                    "courses/form.html",
                    page_title="New course",
                    c=None,
                )
            flash("Curso creado.", "success")
            return redirect(url_for("courses.index"))

        return render_template("courses/form.html", page_title="New Course", c=None)
    except Exception as e:
        db.rollback()
        flash(f"❌ Error creando curso: {e}", "danger")
        return render_template("courses/form.html", page_title="New course", c=None)
    finally:
        db.close()

@bp.route("/<int:course_id>/edit", methods=["GET", "POST"])
@login_required
def edit_course(course_id):
    db = SessionLocal()
    try:
        c = db.query(models.Course).get(course_id)
        if not c:
            flash("Course no encontrado.", "danger")
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
                "status": c.status,
                "notes": c.notes,
            }

            course_code = (request.form.get("course") or "").strip()
            name        = (request.form.get("name") or "").strip()
            start_str   = (request.form.get("start_date") or "").strip()
            end_str     = (request.form.get("end_date") or "").strip()
            trainees    = (request.form.get("trainees") or "").strip()
            status      = (request.form.get("status") or "").strip() or "planned"
            notes       = (request.form.get("notes") or "").strip()

            if not course_code:
                flash("Course code es obligatorio.", "warning")
                return render_template(
                    "courses/form.html",
                    page_title="Edit course",
                    c=c,
                )

            if status not in COURSE_STATUSES:
                flash("Estado inválido. Se usará 'planned'.", "warning")
                status = "planned"

            def parse_date(s):
                if not s:
                    return None
                try:
                    return datetime.strptime(s, "%Y-%m-%d").date()
                except ValueError:
                    return None

            start_date = parse_date(start_str)
            end_date   = parse_date(end_str)

            try:
                trainees_val = int(trainees) if trainees else None
            except ValueError:
                trainees_val = None

            # Aplicar cambios
            c.course     = course_code
            c.name       = name or None
            c.start_date = start_date
            c.end_date   = end_date
            c.trainees   = trainees_val
            c.status     = status
            c.notes      = notes or None

            db.flush()

            after_data = {
                "id": c.id,
                "course": c.course,
                "name": c.name,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "trainees": c.trainees,
                "status": c.status,
                "notes": c.notes,
            }

            log_movement(
                db,
                user_id=getattr(current_user, "id", None),
                entity_type="course",
                entity_id=c.id,
                action="update",
                before_data=before_data,
                after_data=after_data,
                description=f"Course '{c.course}' updated",
                success=True,
                user_agent=request.user_agent.string,
            )

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("No se pudo actualizar el curso. Revisa valores únicos.", "danger")
                return render_template(
                    "courses/form.html",
                    page_title="Edit course",
                    c=c,
                )

            flash("Course actualizado.", "success")
            return redirect(url_for("courses.index"))

        # GET
        return render_template(
            "courses/form.html",
            page_title="Edit course",
            c=c,
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
            flash("Course no encontrado.", "danger")
            return redirect(url_for("courses.index"))

        before_data = {
            "id": c.id,
            "course": c.course,
            "name": c.name,
            "start_date": c.start_date.isoformat() if c.start_date else None,
            "end_date": c.end_date.isoformat() if c.end_date else None,
            "trainees": c.trainees,
            "status": c.status,
            "notes": c.notes,
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
            flash("No se pudo eliminar el curso. Puede estar referenciado en otros registros.", "danger")
            return redirect(url_for("courses.index"))

        flash("Course eliminado.", "success")
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
        end_str   = request.args.get("to")

        # Si no mandan rango, no hacemos nada
        if not start_str or not end_str:
            return jsonify([])

        # from/to vienen como 'YYYY-MM-DD' desde el JS
        start = date.fromisoformat(start_str)
        end   = date.fromisoformat(end_str)

        # Criterio: el curso se muestra si:
        # start_date <= end_visible  AND  end_date >= start_visible
        courses = (
            db.query(models.Course)
              .filter(models.Course.start_date <= end)
              .filter(models.Course.end_date   >= start)
              .all()
        )

        data = []
        for c in courses:
            if not c.start_date:
                continue
            data.append({
                "id": c.id,
                "name": c.course or c.name,
                "start_date": c.start_date.isoformat(),
                "end_date":   (c.end_date or c.start_date).isoformat(),
                "status": c.auto_status,
                "trainees": c.trainees,
                "detail_url": url_for("courses.detail_fragment", course_id=c.id),
            })

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

    # 🔹 recalcular estados de las asignaciones vivas antes de pintar
    update_assignment_overdue_status_for_course(db, course)

    active_assignments = [
        a for a in course.assignments
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

    # 🔹 igual aquí: el fragmento es lo que ves en la ventanita
    update_assignment_overdue_status_for_course(db, course)

    active_assignments = [
        a for a in course.assignments
        if a.status in ("active", "overdue_1", "overdue_2")
        and a.device is not None
    ]

    return render_template(
        "courses/_detail_fragment.html",
        course=course,
        active_assignments=active_assignments,
    )

PER_PAGE = 20  # ajusta a tu gusto

COURSE_STATUSES = ["planned", "active", "finished", "cancelled"]

# Umbral de días de retraso para overdue_1
OVERDUE_1_DAYS = 7


OVERDUE_1_DAYS = 7  # 1..7 días -> overdue_1

def update_assignment_overdue_status_for_course(db, course):
    """
    Actualiza Assignment.status para las asignaciones 'vivas' de un curso
    según la fecha de fin del curso y la fecha actual.

    Estados:
      - active
      - overdue_1  (1..OVERDUE_1_DAYS días tarde)
      - overdue_2  (> OVERDUE_1_DAYS días tarde)
    """
    print("Llamada funcion update fecha")
    today = date.today()

    # Si el curso no tiene fecha fin, todas las "vivas" se quedan en active
    if not course.end_date:
        for a in course.assignments:
            if a.status in ("active", "overdue_1", "overdue_2"):
                a.status = "active"
                # atributo dinámico para la plantilla, no es columna
                a.days_late = 0
        return

    days_late = (today - course.end_date).days

    for a in course.assignments:
        # Solo tocamos las asignaciones vivas
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
        # atributo ad-hoc para usar en la plantilla
        a.days_late = dl