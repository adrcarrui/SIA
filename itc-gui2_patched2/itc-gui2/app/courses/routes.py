# courses/routes.py

from math import ceil
from io import StringIO, BytesIO
import csv

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    abort,
    send_file,
    Response,
)
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload, aliased
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime, timezone

from . import bp
from app.db import SessionLocal
import app.models as models
from app.scripts import log_movement
from app.scripts.alerts_service import get_alerts_for_user
from app.scripts.alert_filters import reason_counts_for_calendar

from app.models import (
    Assignment,
    Course,
    Device,
    User,
    CourseAssetRequirement,
    AssetType,
)

from app.scripts.get_overdue_assignments import (
    get_cards_vs_trainees_alerts,
    get_overdue_course_alerts,
)

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from app.scripts.notification_severity import NOTIFICATION_SEVERITY_MAP
from app.scripts.notifications_rules import course_has_itc_assets
from app.scripts.notifications_rules import build_changes, format_changes, format_requirements_map


PER_PAGE = 20

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


# ============================================================
#   HELPERS: ITC asset types + requirements + render form
# ============================================================

def _get_itc_asset_types(db):
    roots = (
        db.query(models.AssetType)
        .filter(
            models.AssetType.parent_id.is_(None),
            models.AssetType.active.is_(True),
            models.AssetType.code.in_(["COMPUTER", "USB"]),
        )
        .order_by(models.AssetType.sort_order.asc(), models.AssetType.name.asc())
        .all()
    )
    if not roots:
        return []

    root_ids = [r.id for r in roots]

    children = (
        db.query(models.AssetType)
        .filter(
            models.AssetType.parent_id.in_(root_ids),
            models.AssetType.active.is_(True),
        )
        .order_by(models.AssetType.sort_order.asc(), models.AssetType.name.asc())
        .all()
    )

    # Qué roots tienen al menos un hijo
    roots_with_children = {ch.parent_id for ch in children if ch.parent_id is not None}

    # Roots sin hijos (ej: USB normalmente)
    roots_without_children = [r for r in roots if r.id not in roots_with_children]

    # Resultado final: hijos + roots "solitarios"
    result = children + roots_without_children

    # Orden final consistente
    result.sort(key=lambda x: ((x.sort_order or 0), (x.name or "")))
    return result


def _parse_requirements_from_form(db):
    """
    Acepta:
    - Subtipo (parent_id != None): OK
    - Root (parent_id == None): OK SOLO si NO tiene hijos activos (ej: USB)
    """
    ids = request.form.getlist("req_asset_type_id")
    qtys = request.form.getlist("req_qty")

    out = []
    seen = set()

    for i, raw_id in enumerate(ids):
        raw_id = (raw_id or "").strip()
        if not raw_id:
            continue

        try:
            at_id = int(raw_id)
        except ValueError:
            continue

        raw_qty = (qtys[i] if i < len(qtys) else "0")
        try:
            qty = int(raw_qty)
        except ValueError:
            qty = 0
        if qty < 0:
            qty = 0

        at = (
            db.query(AssetType)
            .filter(AssetType.id == at_id, AssetType.active.is_(True))
            .first()
        )
        if not at:
            continue

        # Root: permitir solo si NO tiene hijos
        if at.parent_id is None:
            has_children = (
                db.query(AssetType.id)
                  .filter(AssetType.parent_id == at.id, AssetType.active.is_(True))
                  .count() > 0
            )
            if has_children:
                continue

        if at_id in seen:
            continue
        seen.add(at_id)

        out.append((at_id, qty))

    return out


def _save_course_requirements(db, course, req_pairs):
    """
    Estrategia simple:
    - borra lo anterior
    - inserta lo nuevo (qty<=0 se omite)
    """
    db.query(CourseAssetRequirement).filter(
        CourseAssetRequirement.course_id == course.id
    ).delete(synchronize_session=False)

    for at_id, qty in req_pairs:
        if qty <= 0:
            continue
        db.add(
            CourseAssetRequirement(
                course_id=course.id,
                asset_type_id=at_id,
                quantity=qty,      # <-- confirma que tu modelo usa 'quantity'
                active=True,
            )
        )


def _load_req_map_for_course(db, course_id: int) -> dict:
    """
    {asset_type_id: qty} para pintar el form y para before/after.
    """
    rows = (
        db.query(CourseAssetRequirement)
        .filter(
            CourseAssetRequirement.course_id == course_id,
            CourseAssetRequirement.active.is_(True),
        )
        .all()
    )
    out = {}
    for r in rows:
        out[int(r.asset_type_id)] = int(getattr(r, "quantity", 0) or 0)
    return out

@bp.route("/<int:course_id>/edit", methods=["GET","POST"])
@login_required
def edit_course(course_id):
    db = SessionLocal()
    try:
        c = db.query(models.Course).get(course_id)
        if not c:
            flash("Course not found.", "danger")
            return redirect(url_for("courses.index"))

        if request.method == "POST":
            before_data = {
                "id": c.id,
                "course": c.course,
                "name": c.name,
                "client": c.client,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "trainees": c.trainees,
                "status_tco": c.status_tco,
                "status_itc": c.status_itc,
                "notes": c.notes,
                "responsible_id": c.responsible_id,
            }

            # BEFORE requirements
            before_req_map = _load_req_map_for_course(db, c.id)

            # Leer form
            course_code = normalize_field((request.form.get("course") or ""))
            name = normalize_field((request.form.get("name") or ""))
            client = normalize_field((request.form.get("client") or ""))

            start_str = (request.form.get("start_date") or "").strip()
            end_str = (request.form.get("end_date") or "").strip()
            trainees = (request.form.get("trainees") or "").strip()
            notes = (request.form.get("notes") or "").strip()

            status_tco = (request.form.get("status_tco") or "").strip() or c.status_tco or "planned"
            status_itc = (request.form.get("status_itc") or "").strip() or c.status_itc or "start"

            if status_tco not in COURSE_TCO_STATUSES:
                flash("Invalid TCO status. 'planned' will be used.", "warning")
                status_tco = "planned"

            if status_itc not in COURSE_ITC_STATUSES:
                flash("Invalid ITC status. 'start' will be used.", "warning")
                status_itc = "start"

            actor_role = (getattr(current_user, "role", "") or "").lower()
            actor_dept = (getattr(current_user, "department", "") or "")
            is_itc_only = (actor_dept == "ITC support" and actor_role != "admin")
            if is_itc_only:
                status_tco = c.status_tco or "planned"

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

            # ✅ Validación "Course o Name" (UNA sola vez)
            if not course_code and not name:
                flash("You must fill either 'Course' or 'Name'.", "warning")

                # repoblar para no perder input del usuario
                c.course = course_code
                c.name = name
                c.client = client
                c.notes = notes or None
                c.status_itc = status_itc
                c.status_tco = status_tco
                c.start_date = start_date
                c.end_date = end_date
                c.trainees = trainees_val

                return _render_course_form(db, "Edit course", c)

            # Apply cambios al objeto
            c.course = course_code
            c.name = name or None
            c.client = client or None
            c.start_date = start_date
            c.end_date = end_date
            c.trainees = trainees_val
            c.status_tco = status_tco
            c.status_itc = status_itc
            c.notes = notes or None

            # Responsible
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
                        flash("Selected responsible is not a valid TCO supervisor/employee.", "warning")

            db.flush()

            # Requirements: guardar y comparar
            req_pairs = _parse_requirements_from_form(db)
            print("DEBUG req_pairs:", req_pairs)
            _save_course_requirements(db, c, req_pairs)
            print("DEBUG after_req_map:", _load_req_map_for_course(db, c.id))
            db.flush()

            after_data = {
                "id": c.id,
                "course": c.course,
                "name": c.name,
                "client": c.client,
                "start_date": c.start_date.isoformat() if c.start_date else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "trainees": c.trainees,
                "status_tco": c.status_tco,
                "status_itc": c.status_itc,
                "notes": c.notes,
                "responsible_id": c.responsible_id,
            }

            after_req_map = _load_req_map_for_course(db, c.id)
            req_changed = before_req_map != after_req_map

            itc_fields = {"course", "name", "client", "start_date", "end_date", "status_itc", "trainees", "notes"}
            changes = build_changes(before_data, after_data, allow_fields=itc_fields)

            # ✅ Notificación ITC: incluye BEFORE/AFTER legible
            actor_dept = (getattr(current_user, "department", "") or "").strip()
            actor_role = (getattr(current_user, "role", "") or "").strip().lower()
            is_tco_actor = (actor_dept.upper() == "TCO") and ("admin" not in actor_role)

            # ✅ Notificación ITC:
            # - Si lo edita TCO: notificar (si hay cambios/req_changed y el curso tiene ITC assets)
            # - Si lo edita ITC/Admin: mantener tu comportamiento actual (también notifica con cambios)
            should_notify_itc = (changes or req_changed) and course_has_itc_assets(db, c.id) and (is_tco_actor or True)

            if should_notify_itc:
                cname = (c.course or c.name or f"Course #{c.id}").strip()

                parts = []
                if changes:
                    parts.append("Changes:\n" + format_changes(changes))
                if req_changed:
                    parts.append("Requirements BEFORE:\n" + format_requirements_map(db, before_req_map))
                    parts.append("Requirements AFTER:\n" + format_requirements_map(db, after_req_map))

                who = f"{getattr(current_user, 'name', '')} {getattr(current_user, 'surname', '')}".strip() or "Unknown user"
                dept = actor_dept or "Unknown department"

                create_notification_for_itc(
                    db=db,
                    course=c,
                    created_by_user=current_user,
                    notif_type="course_updated_by_tco" if is_tco_actor else "course_updated",
                    title=f"Course updated: {cname}",
                    message=(f"Updated by: {who} ({dept})\n\n" + "\n\n".join(parts)),
                )

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
                flash("Course could not be updated. Check unique constraints.", "danger")
                return _render_course_form(db, "Edit course", c)

            flash("Course updated.", "success")
            return redirect(url_for("main.index"))

        return _render_course_form(db, "Edit course", c)

    finally:
        db.close()

def _course_form_context(db, c):
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

    itc_asset_types = _get_itc_asset_types(db)

    req_map = {}
    if c and getattr(c, "id", None):
        req_map = _load_req_map_for_course(db, c.id)

    return {
        "COURSE_TCO_STATUSES": COURSE_TCO_STATUSES,
        "COURSE_ITC_STATUSES": COURSE_ITC_STATUSES,
        "responsibles": responsibles,
        "itc_asset_types": itc_asset_types,
        "req_map": req_map,
    }


def _render_course_form(db, page_title, c):
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

    itc_asset_types = _get_itc_asset_types(db)

    req_map = {}
    if c and getattr(c, "id", None):
        req_map = _load_req_map_for_course(db, c.id)

    return render_template(
        "courses/form.html",
        page_title=page_title,
        c=c,
        COURSE_TCO_STATUSES=COURSE_TCO_STATUSES,
        COURSE_ITC_STATUSES=COURSE_ITC_STATUSES,
        responsibles=responsibles,
        itc_asset_types=itc_asset_types,
        req_map=req_map,
    )


# ============================================================
#   NOTIFICATIONS / NORMALIZE
# ============================================================

def create_notification_for_itc(db, course, created_by_user, notif_type, title, message, severity=None):
    sev = severity or NOTIFICATION_SEVERITY_MAP.get(notif_type, "notice")

    n = models.Notification(
        created_by_user_id=getattr(created_by_user, "id", None),
        department_target="ITC support",
        type=notif_type,
        severity=sev,
        status="open",
        title=title,
        message=message,
        course_id=getattr(course, "id", None),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        active=True,
    )
    db.add(n)
    return n


def normalize_field(value: str):
    v = (value or "").strip()
    if not v:
        return None
    if v.lower() == "none":
        return None
    return v


# ============================================================
#   QUERIES
# ============================================================

def build_courses_query(db, args):
    q = (args.get("q") or "").strip()

    course_code = (args.get("course") or "").strip()
    name = (args.get("name") or "").strip()
    client = (args.get("client") or "").strip()
    status = (args.get("status") or "").strip()
    trainees_s = (args.get("trainees") or "").strip()
    notes = (args.get("notes") or "").strip()
    start_str = (args.get("start_date") or "").strip()
    end_str = (args.get("end_date") or "").strip()

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

    if course_code:
        qry = qry.filter(models.Course.course.ilike(f"%{course_code}%"))
    if name:
        qry = qry.filter(models.Course.name.ilike(f"%{name}%"))
    if client:
        qry = qry.filter(models.Course.client.ilike(f"%{client}%"))

    if status:
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

    return qry


# ============================================================
#   ROUTES
# ============================================================

@bp.route("/")
@login_required
def index():
    q = (request.args.get("q") or "").strip()
    page = max(int(request.args.get("page", 1)), 1)
    per_page = int(request.args.get("per_page", PER_PAGE))

    my = request.args.get("my")  # "1" => solo mis cursos

    db = SessionLocal()
    try:
        qry = build_courses_query(db, request.args)

        if my == "1" and current_user.is_authenticated:
            qry = qry.filter(models.Course.responsible_id == current_user.id)

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
            q=q,
            page=page,
            pages=pages,
            total=total,
            per_page=per_page,
            has_prev=page > 1,
            has_next=page < pages,
            filter_course=(request.args.get("course") or "").strip(),
            filter_name=(request.args.get("name") or "").strip(),
            filter_client=(request.args.get("client") or "").strip(),
            filter_status=(request.args.get("status") or "").strip(),
            filter_trainees=(request.args.get("trainees") or "").strip(),
            filter_notes=(request.args.get("notes") or "").strip(),
            filter_start_date=(request.args.get("start_date") or "").strip(),
            filter_end_date=(request.args.get("end_date") or "").strip(),
            COURSE_STATUSES=COURSE_STATUSES,
            COURSE_ITC_STATUSES=COURSE_ITC_STATUSES,
            filter_my=my,
        )
    finally:
        db.close()


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_course():
    from datetime import date as _date

    def to_date(s):
        s = (s or "").strip()
        return _date.fromisoformat(s) if s else None

    db = SessionLocal()
    try:
        if request.method == "POST":
            course = (request.form.get("course") or "").strip()
            name = (request.form.get("name") or "").strip()

            status_tco = (request.form.get("status_tco") or "planned").strip() or "planned"
            status_itc = (request.form.get("status_itc") or "start").strip() or "start"

            if status_tco not in COURSE_TCO_STATUSES:
                status_tco = "planned"
            if status_itc not in COURSE_ITC_STATUSES:
                status_itc = "start"

            actor_role = (getattr(current_user, "role", "") or "").lower()
            actor_dept = (getattr(current_user, "department", "") or "")
            is_itc_only = (actor_dept == "ITC support" and actor_role != "admin")
            if is_itc_only:
                status_tco = "planned"

            notes = (request.form.get("notes") or "").strip()
            client = (request.form.get("client") or "").strip()

            start_dt = to_date(request.form.get("start_date"))
            end_dt = to_date(request.form.get("end_date"))

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
                        flash("Selected responsible is not a valid TCO supervisor/employee.", "warning")

            if not responsible_id and current_user.is_authenticated:
                responsible_id = current_user.id

            t_raw = (request.form.get("trainees") or "").strip()
            try:
                trainees = int(t_raw)
                if trainees < 0:
                    trainees = 0
            except ValueError:
                trainees = 0

            if not course and not name:
                flash("You must fill either 'Course' or 'Name'.", "warning")
                return _render_course_form(db, "New course", None)

            new_c = models.Course(
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
            db.add(new_c)
            db.flush()

            req_pairs = _parse_requirements_from_form(db)
            _save_course_requirements(db, new_c, req_pairs)
            db.flush()
            cname = (new_c.course or new_c.name or f"Course #{new_c.id}").strip()

            req_map = _load_req_map_for_course(db, new_c.id)

            if course_has_itc_assets(db, new_c.id):
                create_notification_for_itc(
                    db=db,
                    course=new_c,
                    created_by_user=current_user,
                    notif_type="course_created",
                    title=f"New course created: {cname}",
                    message=(
                        f"Course created: {cname}\n"
                        f"Client: {new_c.client or '-'} | Trainees: {new_c.trainees}\n"
                        f"Dates: {new_c.start_date or '-'} → {new_c.end_date or '-'}\n\n"
                        f"Requirements:\n{format_requirements_map(db, req_map)}"
                    ),
                )

            log_movement(
                db,
                user_id=getattr(current_user, "id", None),
                entity_type="course",
                entity_id=new_c.id,
                action="create",
                before_data=None,
                after_data={
                    "id": new_c.id,
                    "course": new_c.course,
                    "name": new_c.name,
                    "start_date": new_c.start_date.isoformat() if new_c.start_date else None,
                    "end_date": new_c.end_date.isoformat() if new_c.end_date else None,
                    "trainees": new_c.trainees,
                    "status_tco": new_c.status_tco,
                    "status_itc": new_c.status_itc,
                    "notes": new_c.notes,
                    "responsible_id": new_c.responsible_id,
                    "client": new_c.client,
                },
                description=f"Course '{new_c.course or new_c.name}' created",
                success=True,
                user_agent=request.user_agent.string,
            )

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Course could not be created. Check unique constraints.", "danger")
                return _render_course_form(db, "New course", None)

            flash("Course created.", "success")
            return redirect(url_for("courses.index"))

        return _render_course_form(db, "New course", None)

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

        # Capturar info ANTES de borrar
        cname = (c.course or c.name or f"Course #{c.id}").strip()
        before_req_map = _load_req_map_for_course(db, c.id)
        had_itc_assets = course_has_itc_assets(db, c.id)

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

        # ✅ Notificar a ITC si el curso tenía assets ITC
        if had_itc_assets:
            create_notification_for_itc(
                db=db,
                course=c,  # aún existe aquí
                created_by_user=current_user,
                notif_type="course_deleted",
                title=f"Course deleted: {cname}",
                message=(
                    f"The course was deleted.\n"
                    f"Course: {cname}\n"
                    f"Dates: {c.start_date or '-'} → {c.end_date or '-'} | Trainees: {c.trainees}\n\n"
                    f"Requirements BEFORE deletion:\n{format_requirements_map(db, before_req_map)}"
                ),
                severity="warning",
            )

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
            flash("The course could not be deleted. It may be referenced in other records.", "danger")
            return redirect(url_for("courses.index"))

        flash("Course deleted.", "success")
        return redirect(url_for("courses.index"))

    finally:
        db.close()


@bp.route("/calendar-data")
def calendar_data():
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
                    "status": c.auto_status,
                    "status_tco": c.status_tco,
                    "status_itc": c.status_itc,
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
        .options(joinedload(Course.assignments).joinedload(Assignment.device))
        .get(course_id)
    )
    if not course:
        abort(404)

    update_assignment_overdue_status_for_course(db, course)

    active_assignments = [
        a for a in course.assignments
        if a.status in ("active", "overdue_1", "overdue_2") and a.device is not None
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
        .options(joinedload(Course.assignments).joinedload(Assignment.device))
        .get(course_id)
    )
    if not course:
        abort(404)

    update_assignment_overdue_status_for_course(db, course)

    active_assignments = [
        a for a in course.assignments
        if a.status in ("active", "overdue_1", "overdue_2") and a.device is not None
    ]

    return render_template(
        "courses/_detail_fragment.html",
        course=course,
        active_assignments=active_assignments,
    )


OVERDUE_1_DAYS = 7


def update_assignment_overdue_status_for_course(db, course):
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
        a.days_late = dl

def _now_utc():
    return datetime.now(timezone.utc)

def _as_aware_utc(dt):
    """
    Asegura datetime aware en UTC.
    Si viene naive, lo tratamos como UTC (mejor que romper).
    """
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)



def should_count_reason_for_calendar(reason: dict, now_utc: datetime) -> bool:
    """
    Regla:
      - open -> cuenta
      - snoozed -> solo cuenta si snooze_until ya venció
      - acked / ignored -> no cuenta
    """
    # Compat wrapper: la lógica real vive en app/scripts/alert_filters.py
    return reason_counts_for_calendar(reason, now_utc)

@bp.route("/api/calendar-events")
@login_required
def api_calendar_events():
    db = SessionLocal()
    try:
        severity_order = {"notice": 1, "warning": 2, "critical": 3}
        severity_by_course = {}

        def bump_severity(course_id, sev):
            if sev not in severity_order:
                return
            current = severity_by_course.get(course_id)
            if current is None or severity_order[sev] > severity_order[current]:
                severity_by_course[course_id] = sev

        # ------------------------------------------------------------
        # NUEVO: severidad basada en alertas + estados (solo OPEN cuenta)
        # ------------------------------------------------------------
        now_utc = _now_utc()

        # Pedimos include_hidden=True para tener TODO y decidir nosotros qué cuenta para calendario
        alerts = get_alerts_for_user(db, current_user, include_hidden=True) or []

        for a in alerts:
            course_obj = a.get("course")
            cid = a.get("course_id") or (getattr(course_obj, "id", None) if course_obj else None)
            if not cid:
                continue

            reasons = a.get("reasons") or []

            # Si hay reasons, calculamos la severidad efectiva SOLO con las reasons que cuentan.
            if reasons:
                visible_max = None
                for r in reasons:
                    if not should_count_reason_for_calendar(r, now_utc):
                        continue
                    sev_r = (r.get("severity") or a.get("severity") or "notice").strip().lower()
                    if sev_r not in severity_order:
                        sev_r = "notice"
                    if (visible_max is None) or (severity_order[sev_r] > severity_order[visible_max]):
                        visible_max = sev_r

                if not visible_max:
                    continue  # todo ack/snooze/ignore => no pinta severidad en calendario

                bump_severity(cid, visible_max)
            else:
                # Alertas sin reasons: las contamos como visibles
                sev = (a.get("severity") or "notice").strip().lower()
                if sev not in severity_order:
                    sev = "notice"
                bump_severity(cid, sev)

        # ------------------------------------------------------------
        # Eventos de cursos (igual que antes) pero con sev filtrada
        # ------------------------------------------------------------
        courses = db.query(Course).all()

        events = []
        for c in courses:
            if not c.start_date and not c.end_date:
                continue

            title = ((c.name or "").strip() or (c.course or "").strip() or f"Course #{c.id}")
            detail_url = url_for("courses.detail_fragment", course_id=c.id)

            sev = severity_by_course.get(c.id)  # <- ahora solo si hay OPEN

            base_extended = {
                "course_id": c.id,
                "status": getattr(c, "auto_status", None),
                "status_tco": c.status_tco,
                "status_itc": getattr(c, "status_itc", None),
                "trainees": c.trainees,
                "client": c.client,
                "course_code": c.course,
                "course_url": f"/courses/{c.id}",
                "detail_url": detail_url,
                "severity": sev,  # None si no hay OPEN => curso se ve “normal”
            }

            if c.start_date:
                class_names = ["fc-course-start"]
                if sev:
                    class_names.append(f"fc-sev-{sev}")
                events.append({
                    "id": f"{c.id}-start",
                    "title": title,
                    "start": c.start_date.isoformat(),
                    "allDay": True,
                    "classNames": class_names,
                    "extendedProps": {**base_extended, "kind": "start"},
                })

            if c.end_date and (not c.start_date or c.end_date != c.start_date):
                class_names = ["fc-course-end"]
                if sev:
                    class_names.append(f"fc-sev-{sev}")
                events.append({
                    "id": f"{c.id}-end",
                    "title": title,
                    "start": c.end_date.isoformat(),
                    "allDay": True,
                    "classNames": class_names,
                    "extendedProps": {**base_extended, "kind": "end"},
                })

        return jsonify(events)
    finally:
        db.close()


# ===========================
#   EXPORT: CSV / EXCEL / PDF
# ===========================

def _course_rows(courses):
    rows = []
    rows.append([
        "ID",
        "Course code",
        "Name",
        "Client",
        "Trainees",
        "Start date",
        "End date",
    ])

    for c in courses:
        start = c.start_date
        end = c.end_date

        start_str = start.strftime("%Y-%m-%d") if start else ""
        end_str = end.strftime("%Y-%m-%d") if end else ""

        rows.append([
            c.id,
            c.course or "",
            c.name or "",
            c.client or "",
            c.trainees if c.trainees is not None else "",
            start_str,
            end_str,
        ])

    return rows


def _export_courses_csv(courses):
    output = StringIO()
    writer = csv.writer(output)

    for row in _course_rows(courses):
        writer.writerow(row)

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=courses.csv"},
    )


def _export_courses_excel(courses):
    wb = Workbook()
    ws = wb.active
    ws.title = "Courses"

    for row in _course_rows(courses):
        ws.append(row)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="courses.xlsx",
    )


def _export_courses_pdf(courses):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=40,
        bottomMargin=30,
    )

    styles = getSampleStyleSheet()
    elements = []

    title = Paragraph("Courses report", styles["Heading1"])
    elements.append(title)
    elements.append(Spacer(1, 12))

    data = _course_rows(courses)
    table = Table(data, repeatRows=1)

    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00205d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),

        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

        ("ALIGN", (0, 1), (0, -1), "RIGHT"),
        ("ALIGN", (1, 1), (-1, -1), "LEFT"),

        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),

        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ])

    table.setStyle(table_style)
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="courses.pdf",
    )


@bp.route("/export", methods=["GET"])
@login_required
def export_courses():
    fmt = (request.args.get("format") or "pdf").lower()

    page = max(int(request.args.get("page", 1)), 1)
    per_page = int(request.args.get("per_page", PER_PAGE))

    db = SessionLocal()
    try:
        qry = build_courses_query(db, request.args)

        courses = (
            qry.order_by(models.Course.id.asc())
               .offset((page - 1) * per_page)
               .limit(per_page)
               .all()
        )
    finally:
        db.close()

    if fmt == "pdf":
        return _export_courses_pdf(courses)
    elif fmt == "csv":
        return _export_courses_csv(courses)
    elif fmt in ("xlsx", "excel"):
        return _export_courses_excel(courses)
    else:
        return Response("Unsupported format", status=400)

@bp.route("/notify-itc-pickup", methods=["POST"])
@login_required
def notify_itc_pickup():
    db = SessionLocal()
    try:
        role = (getattr(current_user, "role", "") or "").strip().lower()
        dept = (getattr(current_user, "department", "") or "").strip()

        # Solo TCO o admin
        if ("admin" not in role) and (dept.upper() != "TCO"):
            abort(403)

        note = (request.form.get("pickup_note") or "").strip()

        who = f"{getattr(current_user, 'name', '')} {getattr(current_user, 'surname', '')}".strip() or "Unknown user"
        now = datetime.now(timezone.utc)

        title = "Pickup needed (ITC)"
        message = (
            f"TCO requests ITC pickup.\n"
            f"Requested by: {who} (TCO)\n"
            f"When: {now.isoformat()}\n"
        )
        if note:
            message += f"\nNote:\n{note}"

        # Buscar notificación global abierta existente
        existing = (
            db.query(models.Notification)
              .filter(
                  models.Notification.active.is_(True),
                  models.Notification.department_target == "ITC support",
                  models.Notification.type == "pickup_needed",
                  models.Notification.status.notin_(["done", "dismissed"]),
              )
              .order_by(models.Notification.id.desc())
              .first()
        )

        if existing:
            # Actualiza y “reanuda”
            existing.title = title
            existing.message = message
            existing.severity = "notice"
            existing.status = "open"
            existing.updated_at = now
            existing.read_at = None  # para que vuelva a contar como unread (si usas unread_count)
        else:
            n = models.Notification(
                created_by_user_id=getattr(current_user, "id", None),
                department_target="ITC support",
                type="pickup_needed",
                severity="notice",
                status="open",
                title=title,
                message=message,
                course_id=None,  # ✅ global
                created_at=now,
                updated_at=now,
                active=True,
            )
            db.add(n)

        db.flush()

        log_movement(
            db,
            user_id=getattr(current_user, "id", None),
            entity_type="notification",
            entity_id=getattr(existing, "id", None),
            action="pickup_notify",
            before_data=None,
            after_data={"note": note},
            description="TCO notified ITC about pickup needed",
            success=True,
            user_agent=request.user_agent.string,
        )

        db.commit()
        flash("ITC notified for pickup.", "success")
        return redirect(url_for("main.index"))
    finally:
        db.close()

def _is_itc_or_admin():
    role = (getattr(current_user, "role", "") or "").strip().lower()
    dept = (getattr(current_user, "department", "") or "").strip().lower()
    return ("admin" in role) or (dept == "itc support") or role.startswith("itc")


@bp.route("/<int:course_id>/assign-pcs", methods=["GET", "POST"])
@login_required
def assign_pcs(course_id):
    if not _is_itc_or_admin():
        abort(403)

    db = SessionLocal()
    try:
        c = db.query(models.Course).get(course_id)
        if not c:
            flash("Course not found.", "danger")
            return redirect(url_for("courses.index"))

        if request.method == "POST":
            device_ids = request.form.getlist("device_ids[]")
            device_ids = [int(x) for x in device_ids if (x or "").isdigit()]

            if not device_ids:
                flash("Select at least one PC.", "warning")
                return redirect(url_for("courses.assign_pcs", course_id=course_id))

            now = datetime.now(timezone.utc)

            # Solo asignamos devices available
            devices = (
                db.query(models.Device)
                .filter(
                    models.Device.id.in_(device_ids),
                    #models.Device.active.is_(True),
                    models.Device.status == "available",
                )
                .all()
            )

            if not devices:
                flash("No available PCs found in selection.", "danger")
                return redirect(url_for("courses.assign_pcs", course_id=course_id))

            for d in devices:
                # evitar duplicados (si ya tiene assignment activo)
                existing = (
                    db.query(models.Assignment.id)
                    .filter(
                        models.Assignment.device_id == d.id,
                        models.Assignment.status.in_(["active", "overdue_1", "overdue_2"]),
                    )
                    .first()
                )
                if existing:
                    continue

                db.add(models.Assignment(
                    device_id=d.id,
                    course_id=c.id,
                    status="active",
                    assigned_at=now,
                    created_at=now,
                    updated_at=now,
                    created_by=getattr(current_user, "id", None),
                ))

                d.status = "assigned"
                d.updated_at = now

            db.flush()
            # devices ya lo tienes (lista de Device)
            device_ids = [d.id for d in devices]

            # intenta mostrar algo humano: name (barcode) si existe
            device_labels = []
            for d in devices:
                name = (getattr(d, "name", None) or "").strip()
                barcode = (getattr(d, "barcode", None) or "").strip()

                if name and barcode:
                    device_labels.append(f"{name} ({barcode})")
                elif name:
                    device_labels.append(name)
                elif barcode:
                    device_labels.append(barcode)
                else:
                    # último recurso (si NO quieres IDs nunca, pon "Unknown device")
                    device_labels.append("Unknown device")

            # evita descriptions kilométricas
            MAX_SHOW = 8
            shown = device_labels[:MAX_SHOW]
            extra_n = max(len(device_labels) - MAX_SHOW, 0)

            description = (
                f"Assigned PCs to course '{(c.course or c.name or f'Course #{c.id}')}'"
                + (": " + ", ".join(shown) if shown else "")
                + (f" (+{extra_n} more)" if extra_n else "")
            )

            log_movement(
                db,
                user_id=getattr(current_user, "id", None),
                entity_type="course",
                entity_id=c.id,
                action="assign_pcs",
                before_data=None,
                after_data={
                    # SOLO labels humanos
                    "devices": shown,
                    "devices_total": len(device_labels),
                    "devices_extra": extra_n,  # opcional, por si quieres pintar algo en UI
                },
                description=description,
                success=True,
                user_agent=request.user_agent.string,
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("Could not assign PCs. Check constraints.", "danger")
                return redirect(url_for("courses.assign_pcs", course_id=course_id))

            flash("PC(s) assigned.", "success")
            return redirect(url_for("main.index"))
            #return redirect(url_for("courses.detail", course_id=c.id))

        return render_template(
            "courses/assign_pcs.html",
            page_title="Assign PCs",
            course=c,
        )

    finally:
        db.close()

@bp.route("/api/pc-by-barcode", methods=["POST"])
@login_required
def api_pc_by_barcode():
    if not _is_itc_or_admin():
        return jsonify({"success": False, "error": "Forbidden"}), 403

    data = request.get_json(silent=True) or {}
    barcode = (data.get("barcode") or "").strip()

    print("\n=== api_pc_by_barcode DEBUG ===")
    print("payload:", data)
    print("barcode:", repr(barcode))

    if not barcode:
        print("ERROR: Missing barcode in payload")
        return jsonify({"success": False, "error": "Missing barcode"}), 400

    db = SessionLocal()
    try:
        # 1) Comprobar device raw (SIN FILTROS de COMPUTER)
        raw = (
            db.query(models.Device)
            .options(joinedload(models.Device.asset_type).joinedload(models.AssetType.parent))
            .filter(models.Device.barcode == barcode)
            .first()
        )

        if not raw:
            print("RAW: No device found for barcode at all")
        else:
            print("RAW: device found")
            print("  raw.id:", raw.id)
            print("  raw.name:", raw.name)
            print("  raw.uid:", raw.uid)
            print("  raw.barcode:", raw.barcode)
            print("  raw.active:", getattr(raw, "active", None))
            print("  raw.asset_type_id:", getattr(raw, "asset_type_id", None))
            print("  raw.status:", getattr(raw, "status", None))

            if raw.asset_type:
                print("  asset_type.id:", raw.asset_type.id)
                print("  asset_type.code:", raw.asset_type.code)
                print("  asset_type.name:", raw.asset_type.name)
                print("  asset_type.active:", getattr(raw.asset_type, "active", None))
                if raw.asset_type.parent:
                    print("  parent.id:", raw.asset_type.parent.id)
                    print("  parent.code:", raw.asset_type.parent.code)
                    print("  parent.name:", raw.asset_type.parent.name)
                    print("  parent.active:", getattr(raw.asset_type.parent, "active", None))
                else:
                    print("  parent: None")
            else:
                print("  asset_type: None (asset_type_id might be NULL or FK mismatch)")

        # 2) Query final: COMPUTER root o hijo de COMPUTER (robusto)
        Parent = aliased(models.AssetType)

        d = (
            db.query(models.Device)
            .join(models.AssetType, models.Device.asset_type_id == models.AssetType.id)
            .outerjoin(Parent, models.AssetType.parent_id == Parent.id)
            .options(joinedload(models.Device.asset_type).joinedload(models.AssetType.parent))
            .filter(
                models.Device.barcode == barcode,
                models.AssetType.active.is_(True),
                or_(
                    models.AssetType.code == "COMPUTER",
                    Parent.code == "COMPUTER",
                ),
            )
            .first()
        )

        if not d:
            print("FINAL: Not found with COMPUTER filters.")
            # check: device exists and active?
            active_only = (
                db.query(models.Device.id, models.Device.asset_type_id)
                .filter(models.Device.barcode == barcode)
                .first()
            )
            print("CHECK device by barcode (id, active, asset_type_id):", active_only)

            # check: asset type active?
            if raw and raw.asset_type:
                at_row = (
                    db.query(models.AssetType.id, models.AssetType.code, models.AssetType.active, models.AssetType.parent_id)
                    .filter(models.AssetType.id == raw.asset_type.id)
                    .first()
                )
                print("CHECK asset_type row:", at_row)

            return jsonify({
                "success": False,
                "reason": "not_found",
                "error": "PC not found for this barcode (see server logs DEBUG)."
            }), 404

        print("FINAL: Found device under COMPUTER filters.")
        print("  d.id:", d.id, "d.uid:", d.uid, "d.barcode:", d.barcode)

        # 3) Assignment activo más reciente
        a = (
            db.query(models.Assignment)
            .options(joinedload(models.Assignment.course))
            .filter(
                models.Assignment.device_id == d.id,
                models.Assignment.status.in_(["active", "overdue_1", "overdue_2"]),
            )
            .order_by(models.Assignment.assigned_at.desc())
            .first()
        )

        assigned_course = None
        if a and a.course:
            assigned_course = {
                "id": a.course.id,
                "label": (a.course.course or a.course.name or f"Course #{a.course.id}"),
            }

        return jsonify({
            "success": True,
            "device": {
                "id": d.id,
                "name": d.name,
                "barcode": d.barcode,
                "uid": d.uid,
                "status": d.status,
                "asset_type_code": d.asset_type.code if d.asset_type else None,
                "asset_parent_code": d.asset_type.parent.code if d.asset_type and d.asset_type.parent else None,
            },
            "assigned_course": assigned_course,
        })
    finally:
        db.close()

@bp.route("/pcs/return", methods=["GET", "POST"])
@login_required
def return_pcs():
    if not _is_itc_or_admin():
        flash("Forbidden", "danger")
        return redirect(url_for("main.index"))

    db = SessionLocal()
    try:
        if request.method == "POST":
            device_ids = request.form.getlist("device_ids[]")
            # También aceptamos barcodes[] por si quieres auditar (opcional)
            barcodes = request.form.getlist("barcodes[]")

            if not device_ids:
                flash("No PCs selected.", "warning")
                return redirect(url_for("courses.return_pcs"))

            now = datetime.now(timezone.utc)

            returned = 0
            skipped = 0

            for raw_id in device_ids:
                try:
                    did = int(raw_id)
                except ValueError:
                    skipped += 1
                    continue

                d = (
                    db.query(models.Device)
                    .options(joinedload(models.Device.asset_type).joinedload(models.AssetType.parent))
                    .filter(models.Device.id == did)
                    .first()
                )
                if not d:
                    skipped += 1
                    continue

                # Siempre dejamos el PC como available (esté o no asignado)
                d.status = "available"
                d.updated_at = now

                # Encontrar assignment "vivo" para ese device
                # (tu tabla assignments = estado actual)
                a = (
                    db.query(models.Assignment)
                    .filter(
                        models.Assignment.device_id == d.id,
                        models.Assignment.status.in_(["active", "overdue_1", "overdue_2"]),
                    )
                    .order_by(models.Assignment.assigned_at.desc())
                    .first()
                )

                if not a:
                    skipped += 1
                    continue

                # BORRAR la asignación (tabla viva)
                db.delete(a)
                returned += 1

            db.flush()

            # Log (si lo usas)
            log_movement(
                db,
                user_id=getattr(current_user, "id", None),
                entity_type="pc_return",
                entity_id=None,
                action="bulk_return",
                before_data=None,
                after_data={
                    "returned_count": returned,
                    "skipped_count": skipped,
                    "device_ids": device_ids,
                    "barcodes": barcodes,
                },
                description=f"ITC returned PCs (returned={returned}, skipped={skipped})",
                success=True,
                user_agent=request.user_agent.string,
            )

            db.commit()
            flash(f"Returned PCs: {returned}. Skipped: {skipped}.", "success")
            return redirect(url_for("main.index"))

        # GET
        return render_template("courses/return_pcs.html", page_title="Return PCs")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

@bp.route("/api/course/<int:course_id>/itc-status", methods=["POST"])
@login_required
def api_update_itc_status(course_id):
    # Solo ITC o admin
    if not _is_itc_or_admin():
        return jsonify({"success": False, "error": "Forbidden"}), 403

    # --- Opción B: defensa básica anti-CSRF (Origin + XHR)
    origin = (request.headers.get("Origin") or "").strip()
    host = request.host_url.rstrip("/")

    # Si hay Origin y no coincide con tu host, fuera
    if origin and not origin.startswith(host):
        return jsonify({"success": False, "error": "Bad origin"}), 403

    # Exigir que venga de XHR/fetch (no perfecto, pero filtra basura)
    if (request.headers.get("X-Requested-With") or "") != "XMLHttpRequest":
        return jsonify({"success": False, "error": "Invalid request"}), 400

    data = request.get_json(silent=True) or {}
    new_status = (data.get("status_itc") or "").strip()

    if not new_status:
        return jsonify({"success": False, "error": "Missing status_itc"}), 400

    if new_status not in COURSE_ITC_STATUSES:
        return jsonify({"success": False, "error": "Invalid status_itc"}), 400

    db = SessionLocal()
    try:
        c = db.query(models.Course).get(course_id)
        if not c:
            return jsonify({"success": False, "error": "Course not found"}), 404

        before_data = {
            "id": c.id,
            "status_itc": c.status_itc,
        }

        c.status_itc = new_status
        db.flush()

        after_data = {
            "id": c.id,
            "status_itc": c.status_itc,
        }

        log_movement(
            db,
            user_id=getattr(current_user, "id", None),
            entity_type="course",
            entity_id=c.id,
            action="update_itc_status",
            before_data=before_data,
            after_data=after_data,
            description=f"Course '{c.course or c.name or f'#{c.id}'}' ITC status updated",
            success=True,
            user_agent=request.user_agent.string,
        )

        db.commit()
        return jsonify({"success": True, "status_itc": c.status_itc})

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()