from flask import render_template, request, redirect, url_for
from flask_login import login_required, current_user

from app.alerts import bp
from app.extensions import db
from app.scripts.alerts_service import get_alerts_for_user
from app.scripts.alert_filters import filter_alerts


@bp.route("/", methods=["GET"])
@login_required
def alerts_index():
    severity = request.args.get("severity") or ""
    type_q = request.args.get("type") or ""
    q = request.args.get("q") or ""
    responsible = request.args.get("responsible") or ""
    state = request.args.get("state") or ""
    filter_my = request.args.get("my") or ""

    course_q = (request.args.get("course") or "").strip()   # 👈 NUEVO
    show_hidden = request.args.get("show_hidden") == "1"    # 👈 NUEVO

    def is_tco_employee(user) -> bool:
        role = (getattr(user, "role", "") or "").strip().lower()
        dept = (getattr(user, "department", "") or "").strip().lower()
        return (dept == "tco") and (role == "employee")

    # paginación
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except Exception:
        page = 1

    try:
        per_page = int(request.args.get("per_page", 20))
        if per_page not in (10, 20, 50, 100):
            per_page = 20
    except Exception:
        per_page = 20

    alerts = get_alerts_for_user(db.session, current_user, include_hidden=show_hidden)

    if filter_my == "1":
        uid = current_user.id
        alerts = [
            a for a in alerts
            if a.get("course") and getattr(a["course"], "responsible_id", None) == uid
        ]

    alerts = filter_alerts(
        alerts,
        severity=severity,
        type_q=type_q,
        q=q,
        responsible=responsible,
        state=state,
        course_q=course_q,
        include_hidden=show_hidden,   # 👈 NUEVO (tienes que añadirlo abajo en filter_alerts)
    )

    total = len(alerts)
    start = (page - 1) * per_page
    end = start + per_page
    page_items = alerts[start:end]

    total_pages = max((total + per_page - 1) // per_page, 1)
    if page > total_pages:
        page = total_pages
        start = (page - 1) * per_page
        end = start + per_page
        page_items = alerts[start:end]

    tco_employee_flag = bool(is_tco_employee(current_user))

    return render_template(
        "alerts/index.html",
        alerts=page_items,
        severity=severity,
        type=type_q,
        q=q,
        responsible=responsible,
        state=state,
        course=course_q,  # 👈 NUEVO
        show_hidden="1" if show_hidden else "",
        filter_my=filter_my,

        # paginación
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        is_tco_employee = tco_employee_flag,
    )

def scope_for_user(user) -> str:
    role = (getattr(user, "role", "") or "").strip().lower()
    dept = (getattr(user, "department", "") or "").strip().lower()

    is_admin = ("admin" in role)
    is_tco = (dept == "tco") or dept.startswith("tco") or ("tco" in dept)
    is_itc = (dept == "itc support") or dept.startswith("itc") or ("itc" in dept)

    if is_admin:
        return "admin"
    if is_tco:
        return "tco"
    if is_itc:
        return "itc"
    return "other"

@bp.get("/index", endpoint="index")
@login_required
def index():
    # alias para url_for("alerts.index")
    return redirect(url_for("alerts.alerts_index"))