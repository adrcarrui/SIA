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


def _active_missing_window_days(sd: date, ed: date | None) -> int:
    """
    Ventana (en días) durante la cual, con el curso activo, avisamos de faltan laptops.
    Es el 25% de la duración (floor). Forzamos mínimo 1 para que cursos cortos no queden mudos.
    Si ed es None (curso sin fecha fin), usamos 1 día por defecto.
    """
    if not sd or not ed:
        return 1
    duration = (ed - sd).days + 1  # inclusivo
    if duration <= 0:
        return 1
    w = int(duration * 0.25)  # floor
    return max(1, w)


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

    # --- ACTIVE (curso activo hoy)
    active = (
        db.query(Course)
        .filter(
            Course.start_date.isnot(None),
            Course.start_date <= today,
            func.coalesce(Course.end_date, today) >= today,  # incluye end_date None
        )
        .all()
    )
    active_ids = [c.id for c in active]
    required_active = _required_itc_by_course(db, active_ids)
    assigned_active_laptops = _assigned_laptops_by_course(db, active_ids)

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

    # UNA alerta por curso con reasons
    by_course: dict[int, dict] = {}

    def ensure_course_bucket(c: Course):
        if c.id not in by_course:
            by_course[c.id] = {
                "course": c,
                "course_id": c.id,
                "reasons": [],       # list[{"key","text","extra","legacy_keys"}]
                "keys_set": set(),   # dedup por key principal (no por legacy)
                "severity": None,
                "extra": {},
            }
        return by_course[c.id]

    def add_reason(
        bucket: dict,
        key: str,
        text: str,
        sev: str | None = None,
        extra: dict | None = None,
        legacy_keys: list[str] | None = None,
    ):
        # dedup SOLO por key principal
        if key in bucket["keys_set"]:
            return
        bucket["keys_set"].add(key)

        if sev:
            bucket["severity"] = _bump_sev(bucket["severity"], sev)

        bucket["reasons"].append({
            "key": key,
            "text": text,
            "extra": extra or {},
            "legacy_keys": legacy_keys or [],
        })

    # -------------------------
    # UPCOMING rules
    # -------------------------
    for c in upcoming:
        req_l = required.get(c.id, {}).get("LAPTOP", 0)
        req_p = required.get(c.id, {}).get("PENDRIVE", 0)

        if req_l <= 0 and req_p <= 0:
            continue  # no relevante ITC

        days_left = (c.start_date - today).days
        sev = _severity_for_days_left(days_left)
        if sev is None:
            continue  # fuera de ventana (por si acaso)

        cname = c.name or c.course or f"Course #{c.id}"
        status_itc = (c.status_itc or "").strip().lower()
        is_terminal = status_itc in ITC_TERMINAL

        bucket = ensure_course_bucket(c)

        # 2) laptops mismatch (unificado)
        if req_l > 0:
            asg_l = assigned_laptops.get(c.id, 0)

            if asg_l != req_l and days_left in (3, 2, 1, 0):
                sev_m = "critical" if days_left == 0 else sev

                if days_left == 0:
                    text = f"{cname} starts today: laptops assigned {asg_l}/{req_l}."
                    legacy = ["itc_laptops_mismatch_today"]
                else:
                    text = f"{cname} starts in {days_left} day(s): laptops assigned {asg_l}/{req_l}."
                    legacy = ["itc_laptops_mismatch_start_soon"]

                add_reason(
                    bucket,
                    "itc_laptops_mismatch",
                    text,
                    sev=sev_m,
                    extra={"days_left": days_left, "assigned": asg_l, "required": req_l},
                    legacy_keys=legacy
                )

            bucket["extra"]["required_laptops"] = req_l
            bucket["extra"]["assigned_laptops"] = asg_l

        # 3) Día 0: status ITC no terminal
        if days_left == 0 and not is_terminal and (req_l > 0 or req_p > 0):
            parts = []
            legacy = []

            if req_l > 0:
                parts.append(f"laptops required ({req_l})")
                legacy.append("itc_laptops_not_terminal_today")
            if req_p > 0:
                parts.append(f"pendrives required ({req_p})")
                legacy.append("itc_pendrives_not_terminal_today")

            need_txt = " and ".join(parts)

            add_reason(
                bucket,
                "itc_assets_not_terminal_today",
                f"{cname} starts today: {need_txt} but ITC status is '{status_itc}' (expected terminal).",
                sev="critical",
                extra={"required_laptops": req_l, "required_pendrives": req_p, "status_itc": status_itc},
                legacy_keys=legacy
            )

        if req_p > 0:
            bucket["extra"]["required_pendrives"] = req_p

        bucket["extra"]["days_left"] = days_left
        bucket["extra"]["status_itc"] = status_itc

    # -------------------------
    # ACTIVE rules (primer 25% del curso) - EXCLUYE día 0
    # -------------------------
    for c in active:
        req_l = required_active.get(c.id, {}).get("LAPTOP", 0)
        req_p = required_active.get(c.id, {}).get("PENDRIVE", 0)

        if req_l <= 0 and req_p <= 0:
            continue  # no relevante ITC

        if not c.start_date:
            continue

        days_since_start = (today - c.start_date).days

        # EXCLUIMOS el día 0 para no solapar con UPCOMING days_left == 0
        if days_since_start == 0:
            continue

        miss_window = _active_missing_window_days(c.start_date, c.end_date)

        # Solo durante el 25% inicial (floor, min 1)
        if not (0 <= days_since_start < miss_window):
            continue

        cname = c.name or c.course or f"Course #{c.id}"
        bucket = ensure_course_bucket(c)

        # Laptops: solo missing (no extra)
        if req_l > 0:
            asg_l = assigned_active_laptops.get(c.id, 0)

            if asg_l < req_l:
                # Severidad progresiva dentro de la ventana
                progress = (days_since_start + 1) / miss_window  # 0..1+
                if progress <= 0.34:
                    sev = "notice"
                elif progress <= 0.67:
                    sev = "warning"
                else:
                    sev = "critical"

                add_reason(
                    bucket,
                    "itc_laptops_mismatch",
                    (
                        f"{cname} is active: laptops assigned {asg_l}/{req_l}. "
                        f"(Day {days_since_start + 1}, window {miss_window} day(s))."
                    ),
                    sev=sev,
                    extra={
                        "days_since_start": days_since_start,
                        "missing_window_days": miss_window,
                        "assigned": asg_l,
                        "required": req_l,
                    },
                    legacy_keys=[],
                )

            bucket["extra"]["required_laptops"] = req_l
            bucket["extra"]["assigned_laptops"] = asg_l

        if req_p > 0:
            bucket["extra"]["required_pendrives"] = req_p

        bucket["extra"]["days_since_start"] = days_since_start
        bucket["extra"]["missing_window_days"] = miss_window

    # -------------------------
    # OVERDUE laptops (curso acabado y assignments vivos)
    # -------------------------
    for c in laptop_courses:
        alive_cnt = alive.get(c.id, 0)
        if alive_cnt <= 0:
            continue

        days_late = (today - c.end_date).days
        sev_overdue = "warning" if days_late < 3 else "critical"
        cname = c.name or c.course or f"Course #{c.id}"

        bucket = ensure_course_bucket(c)
        add_reason(
            bucket,
            "itc_laptops_overdue_return",
            f"{cname} ended {days_late} day(s) ago: {alive_cnt} laptops still assigned (not returned).",
            sev=sev_overdue,
            extra={"days_late": days_late, "alive_laptops": alive_cnt}
        )
        bucket["extra"]["days_late"] = days_late
        bucket["extra"]["alive_laptops"] = alive_cnt

    # -------------------------
    # Emitimos lista final
    # -------------------------
    alerts: list[dict] = []
    for cid, b in by_course.items():
        if not b["reasons"]:
            continue

        message = "\n".join([f"- {r['text']}" for r in b["reasons"]])

        # keys = key principal + legacy_keys (compatibilidad con alert_states antiguos)
        keys = []
        for r in b["reasons"]:
            k = r.get("key")
            if k:
                keys.append(k)
            for lk in (r.get("legacy_keys") or []):
                keys.append(lk)
        keys = list(dict.fromkeys(keys))

        alerts.append({
            "type": "course_agg",
            "severity": b["severity"] or "notice",
            "code": "itc_course_summary",
            "message": message,
            "course": b["course"],
            "course_id": b["course_id"],
            "reasons": b["reasons"],
            "keys": keys,
            "extra": b["extra"],
        })

    return alerts
