from datetime import date, timedelta
from sqlalchemy import func

from app.models import Course, Assignment, Device, AssetType, CourseAssetRequirement

ITC_DEPT = "ITC support"
ITC_CODES = {"LAPTOP", "PENDRIVE"}

ITC_TERMINAL = {
    "delivered", "rt delivered", "msn delivered",
    "completed", "end", "collected",
}

SEV_RANK = {"notice": 1, "warning": 2, "critical": 3}


def _severity_for_days_left(days_left: int) -> str | None:
    if days_left == 3:
        return "notice"
    if days_left in (2, 1):
        return "warning"
    if days_left == 0:
        return "critical"
    return None


def _required_itc_by_course(db, course_ids: list[int]) -> dict[int, dict]:
    """
    required_laptops, required_pendrives por curso (requirements activos).
    """
    if not course_ids:
        return {}

    rows = (
        db.query(
            CourseAssetRequirement.course_id,
            AssetType.code,
            func.coalesce(func.sum(CourseAssetRequirement.quantity), 0).label("qty"),
        )
        .join(AssetType, AssetType.id == CourseAssetRequirement.asset_type_id)
        .filter(
            CourseAssetRequirement.course_id.in_(course_ids),
            CourseAssetRequirement.active.is_(True),
            AssetType.active.is_(True),
            AssetType.managed_by_department == ITC_DEPT,
            AssetType.code.in_(ITC_CODES),
        )
        .group_by(CourseAssetRequirement.course_id, AssetType.code)
        .all()
    )

    out = {cid: {"LAPTOP": 0, "PENDRIVE": 0} for cid in course_ids}
    for cid, code, qty in rows:
        out[cid][code] = int(qty or 0)
    return out


def _assigned_laptops_by_course(db, course_ids: list[int]) -> dict[int, int]:
    if not course_ids:
        return {}

    rows = (
        db.query(
            Assignment.course_id,
            func.count(Assignment.id).label("cnt"),
        )
        .join(Device, Device.id == Assignment.device_id)
        .join(AssetType, AssetType.id == Device.asset_type_id)
        .filter(
            Assignment.course_id.in_(course_ids),
            Assignment.released_at.is_(None),
            func.lower(Assignment.status) == "active",
            AssetType.active.is_(True),
            AssetType.managed_by_department == ITC_DEPT,
            AssetType.code == "LAPTOP",
        )
        .group_by(Assignment.course_id)
        .all()
    )

    out = {cid: 0 for cid in course_ids}
    for cid, cnt in rows:
        out[cid] = int(cnt or 0)
    return out


def _bump_sev(cur: str | None, new: str) -> str:
    if not cur:
        return new
    return new if SEV_RANK.get(new, 0) > SEV_RANK.get(cur, 0) else cur


def get_itc_upcoming_and_overdue_alerts(db) -> list[dict]:
    today = date.today()
    max_date = today + timedelta(days=3)

    # --- UPCOMING
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
    required = _required_itc_by_course(db, ids)
    assigned_laptops = _assigned_laptops_by_course(db, ids)

    # --- OVERDUE base (curso acabado)
    finished = (
        db.query(Course)
        .filter(Course.end_date.isnot(None), Course.end_date < today)
        .all()
    )
    finished_ids = [c.id for c in finished]
    required_finished = _required_itc_by_course(db, finished_ids)

    # Solo cursos que requerían laptops
    laptop_courses = [
        c for c in finished
        if required_finished.get(c.id, {}).get("LAPTOP", 0) > 0
    ]
    laptop_ids = [c.id for c in laptop_courses]
    alive = _assigned_laptops_by_course(db, laptop_ids)

    # Vamos a construir UNA alerta por curso (course_agg) con reasons keyed
    by_course: dict[int, dict] = {}

    def ensure_course_bucket(c: Course):
        if c.id not in by_course:
            by_course[c.id] = {
                "course": c,
                "course_id": c.id,
                "reasons": [],   # list[{"key","text"}]
                "severity": None,
                "extra": {},
            }
        return by_course[c.id]

    # UPCOMING rules
    for c in upcoming:
        req_l = required.get(c.id, {}).get("LAPTOP", 0)
        req_p = required.get(c.id, {}).get("PENDRIVE", 0)

        if req_l <= 0 and req_p <= 0:
            continue  # no relevante ITC

        days_left = (c.start_date - today).days
        sev = _severity_for_days_left(days_left)
        if sev is None:
            continue

        cname = c.name or c.course or f"Course #{c.id}"
        status_itc = (c.status_itc or "").strip().lower()
        is_terminal = status_itc in ITC_TERMINAL

        bucket = ensure_course_bucket(c)

        # 1) aviso proximidad
        bucket["severity"] = _bump_sev(bucket["severity"], sev)
        bucket["reasons"].append({
            "key": f"itc_start_{days_left}d",
            "text": f"{cname} starts in {days_left} day(s)."
        })

        # 2) laptops
        if req_l > 0:
            asg_l = assigned_laptops.get(c.id, 0)

            # Escalado antes del inicio si mismatch
            if days_left in (3, 2, 1) and asg_l != req_l:
                bucket["severity"] = _bump_sev(bucket["severity"], sev)
                bucket["reasons"].append({
                    "key": f"itc_laptops_mismatch_{days_left}d",
                    "text": f"{cname} starts in {days_left} day(s): laptops assigned {asg_l}/{req_l}."
                })

            # Día 0: mismatch siempre crítico
            if days_left == 0 and asg_l != req_l:
                bucket["severity"] = _bump_sev(bucket["severity"], "critical")
                bucket["reasons"].append({
                    "key": "itc_laptops_mismatch_today",
                    "text": f"{cname} starts today: laptops assigned {asg_l}/{req_l}."
                })

            # Día 0: crítico si no terminal aunque estén asignados OK
            if days_left == 0 and not is_terminal:
                bucket["severity"] = _bump_sev(bucket["severity"], "critical")
                bucket["reasons"].append({
                    "key": "itc_laptops_not_terminal_today",
                    "text": f"{cname} starts today: laptops required ({req_l}) but ITC status is '{status_itc}' (expected terminal)."
                })

            bucket["extra"]["required_laptops"] = req_l
            bucket["extra"]["assigned_laptops"] = asg_l

        # 3) pendrives: día 0 crítico si no terminal
        if req_p > 0:
            if days_left == 0 and not is_terminal:
                bucket["severity"] = _bump_sev(bucket["severity"], "critical")
                bucket["reasons"].append({
                    "key": "itc_pendrives_not_terminal_today",
                    "text": f"{cname} starts today: pendrives required ({req_p}) but ITC status is '{status_itc}' (expected terminal)."
                })
            bucket["extra"]["required_pendrives"] = req_p

        bucket["extra"]["days_left"] = days_left
        bucket["extra"]["status_itc"] = status_itc

    # OVERDUE laptops (curso acabado y assignments vivos)
    for c in laptop_courses:
        alive_cnt = alive.get(c.id, 0)
        if alive_cnt <= 0:
            continue

        days_late = (today - c.end_date).days
        sev_overdue = "warning" if days_late < 3 else "critical"
        cname = c.name or c.course or f"Course #{c.id}"

        bucket = ensure_course_bucket(c)
        bucket["severity"] = _bump_sev(bucket["severity"], sev_overdue)
        bucket["reasons"].append({
            "key": "itc_laptops_overdue_return",
            "text": f"{cname} ended {days_late} day(s) ago: {alive_cnt} laptops still assigned (not returned)."
        })
        bucket["extra"]["days_late"] = days_late
        bucket["extra"]["alive_laptops"] = alive_cnt

    # Emitimos lista final
    alerts: list[dict] = []
    for cid, b in by_course.items():
        if not b["reasons"]:
            continue

        message = "\n".join([f"- {r['text']}" for r in b["reasons"]])

        alerts.append({
            "type": "course_agg",
            "severity": b["severity"] or "notice",
            "code": "itc_course_summary",
            "message": message,
            "course": b["course"],
            "course_id": b["course_id"],
            "reasons": b["reasons"],
            "keys": [r["key"] for r in b["reasons"]],
            "extra": b["extra"],
        })

    return alerts
