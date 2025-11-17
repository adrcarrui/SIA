from math import ceil
from flask import render_template, request, redirect, url_for, flash,jsonify
from flask_login import login_required
from . import bp
from app.db import SessionLocal
import app.models as models
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime, timedelta

PER_PAGE = 20  # ajusta a tu gusto

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
            page_title="Courses",
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

            if not course:
                flash("El campo 'course' es obligatorio.", "warning")
                return render_template("courses/form.html", page_title="New course", c=None)

            new_course = models.Course(
                course=course,
                name=name,
                status=status,          # evita None
                notes=notes,            # evita None
                trainees=trainees,      # evita None
                start_date=start_dt,    # nombre correcto
                end_date=end_dt,        # nombre correcto
            )
            db.add(new_course)
            db.commit()
            flash("Curso creado.", "success")
            return redirect(url_for("courses.index"))

        return render_template("courses/form.html", page_title="New course", c=None)
    except Exception as e:
        db.rollback()
        flash(f"❌ Error creando curso: {e}", "danger")
        return render_template("courses/form.html", page_title="New course", c=None)
    finally:
        db.close()

@bp.route("/<int:course_id>/edit", methods=["GET","POST"])
@login_required
def edit_course(course_id):
    db = SessionLocal()
    try:
        c = db.query(models.Course).get(course_id)
        if not c:
            flash("Curso no encontrado", "warning")
            return redirect(url_for("courses.index"))

        if request.method == "POST":
            c.course = (request.form.get("course") or "").strip()
            c.name   = (request.form.get("name") or "").strip()
            c.notes  = (request.form.get("notes") or "").strip()
            c.trainees = (request.form.get("trainees") or "").strip()
            c.status = (request.form.get("status") or "").strip()
            # si usas Date en el modelo:
            from datetime import date
            sd = request.form.get("start_date") or ""
            ed = request.form.get("end_date") or ""
            c.start_date = date.fromisoformat(sd) if sd else None
            c.end_date   = date.fromisoformat(ed) if ed else None
            db.commit()
            flash("Curso actualizado.", "success")
            return redirect(url_for("courses.index"))

        return render_template("courses/form.html", page_title=f"Edit course", c=c)
    finally:
        db.close()


@bp.route("/<int:course_id>/delete", methods=["POST"])
@login_required
def delete_course(course_id):
    db = SessionLocal()
    try:
        c = db.query(models.Course).get(course_id)
        if not c:
            flash("Curso no encontrado", "warning")
        else:
            db.delete(c)

            db.commit()
            flash("Curso eliminado.", "info")
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
            })

        return jsonify(data)
    finally:
        db.close()