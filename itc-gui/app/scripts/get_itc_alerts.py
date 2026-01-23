from datetime import date, timedelta
from sqlalchemy import func
from app.models import Course, Assignment, Device, AssetType
from app.scripts.itc_rules import get_itc_requirements_by_course  # tu helper
def get_itc_course_prep_alerts(db, days_before=3):
    """
    Alertas para ITC support:
    - Cursos que empiezan en `days_before` días
    """

    target_date = date.today() + timedelta(days=days_before)

    courses = (
        db.query(Course)
        .filter(Course.start_date == target_date)
        .all()
    )

    alerts = []

    for c in courses:
        cname = c.name or c.course or f"Course #{c.id}"

        alerts.append({
            "type": "itc_course_prep",
            "severity": "notice",
            "scope": "ITC",
            "course": c,
            "message": f"{cname} starts in {days_before} days. Preparation required.",
        })

    return alerts

ITC_TERMINAL = {
    "delivered", "rt delivered", "msn delivered",
    "completed", "end", "collected",
}

def _sev_for_days_left(days_left: int) -> str | None:
    # 3 días -> notice, 2 -> warning, 1 -> warning, 0 -> critical
    if days_left == 3:
        return "notice"
    if days_left in (2, 1):
        return "warning"
    if days_left == 0:
        return "critical"
    return None

def count_assigned_laptops_by_course(db, course_ids):
    if not course_ids:
        return {}

    rows = (
        db.query(
            Assignment.course_id.label("course_id"),
            func.count(Assignment.id).label("cnt"),
        )
        .join(Device, Device.id == Assignment.device_id)
        .join(AssetType, AssetType.id == Device.asset_type_id)
        .filter(
            Assignment.course_id.in_(course_ids),
            Assignment.released_at.is_(None),
            Assignment.status == "active",
            AssetType.code == "LAPTOP",
        )
        .group_by(Assignment.course_id)
        .all()
    )

    out = {cid: 0 for cid in course_ids}
    for r in rows:
        out[r.course_id] = int(r.cnt or 0)
    return out

def get_itc_upcoming_and_overdue_alerts(db):
    alerts = []
    today = date.today()

    # -------------------------
    # A) UPCOMING: hoy..+3 días
    # -------------------------
    max_date = today + timedelta(days=3)
    upcoming = (
        db.query(Course)
        .filter(
            Course.start_date.isnot(None),
            Course.start_date >= today,
            Course.start_date <= max_date,
        )
        .all()
    )
    ids = [c.id for c in upcoming]
    reqs = get_itc_requirements_by_course(db, ids)
    assigned_laptops = count_assigned_laptops_by_course(db, ids)

    for c in upcoming:
        required_laptops = reqs.get(c.id, {}).get("pcs", 0)          # pcs == LAPTOP
        required_pendrives = reqs.get(c.id, {}).get("pendrives", 0)

        itc_relevant = (required_laptops > 0) or (required_pendrives > 0)
        if not itc_relevant:
            continue

        days_left = (c.start_date - today).days
        sev = _sev_for_days_left(days_left)
        if sev is None:
            continue

        status_itc = (c.status_itc or "").strip().lower()
        is_terminal = status_itc in ITC_TERMINAL

        cname = c.name or c.course or f"Course #{c.id}"
        laptops_now = assigned_laptops.get(c.id, 0)

        # 1) Aviso genérico de “curso se acerca” (solo ITC relevant)
        alerts.append({
            "type": f"itc_course_start_{days_left}d",
            "severity": sev,
            "course": c,
            "message": f"{cname} starts in {days_left} day(s).",
        })

        # 2) Pendrives: crítico el día de inicio si no terminal
        if required_pendrives > 0 and days_left == 0 and not is_terminal:
            alerts.append({
                "type": "itc_pendrives_not_terminal_today",
                "severity": "critical",
                "course": c,
                "message": f"{cname} starts today: pendrives required ({required_pendrives}) but ITC status is '{status_itc}'.",
            })

        # 3) PCs/Laptops: crítico el día de inicio si asignados != requeridos, o si estado no terminal
        if required_laptops > 0:
            if days_left == 0 and laptops_now != required_laptops:
                alerts.append({
                    "type": "itc_laptops_count_mismatch_today",
                    "severity": "critical",
                    "course": c,
                    "message": f"{cname} starts today: laptops assigned {laptops_now}/{required_laptops}.",
                })

            if days_left == 0 and not is_terminal:
                alerts.append({
                    "type": "itc_laptops_not_terminal_today",
                    "severity": "critical",
                    "course": c,
                    "message": f"{cname} starts today: laptops required ({required_laptops}) but ITC status is '{status_itc}'.",
                })

            # escalado antes del inicio si faltan laptops asignados
            if days_left in (3, 2, 1) and laptops_now != required_laptops:
                sev2 = _sev_for_days_left(days_left)  # notice/warning
                alerts.append({
                    "type": f"itc_laptops_count_mismatch_{days_left}d",
                    "severity": sev2,
                    "course": c,
                    "message": f"{cname} starts in {days_left} day(s): laptops assigned {laptops_now}/{required_laptops}.",
                })

    # ---------------------------------------
    # B) OVERDUE: curso acabado y laptops vivos
    # ---------------------------------------
    finished = (
        db.query(Course)
        .filter(
            Course.end_date.isnot(None),
            Course.end_date < today,
        )
        .all()
    )
    finished_ids = [c.id for c in finished]
    reqs_finished = get_itc_requirements_by_course(db, finished_ids)

    # Solo cursos con laptops requeridos
    laptop_courses = [c for c in finished if reqs_finished.get(c.id, {}).get("pcs", 0) > 0]
    laptop_course_ids = [c.id for c in laptop_courses]

    # Cuenta assignments LAPTOP todavía activos por curso
    alive = count_assigned_laptops_by_course(db, laptop_course_ids)

    for c in laptop_courses:
        alive_cnt = alive.get(c.id, 0)
        if alive_cnt <= 0:
            continue

        days_late = (today - c.end_date).days
        cname = c.name or c.course or f"Course #{c.id}"

        # escalado: 1-2 días warning, 3+ critical (ajusta si quieres)
        sev = "warning" if days_late < 3 else "critical"

        alerts.append({
            "type": "itc_laptops_overdue_return",
            "severity": sev,
            "course": c,
            "message": f"{cname} ended {days_late} day(s) ago: {alive_cnt} laptops still assigned (not returned).",
        })

    return alerts