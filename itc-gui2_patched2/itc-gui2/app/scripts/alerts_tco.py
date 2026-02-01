from datetime import date, timedelta
from flask import current_app
from sqlalchemy import func
from app.models import Device, Course, Assignment, AssetType, CourseAssetRequirement

SEV_RANK = {"notice": 1, "warning": 2, "critical": 3}


def card_asset_type_ids(db) -> list[int]:
    """
    Devuelve IDs de AssetType que representan tarjetas:
    - el padre CARD
    - sus hijos directos (AssetType.parent_id == CARD.id)

    Si tienes nietos (más niveles), habrá que hacerlo recursivo.
    """
    parent = (
        db.query(AssetType)
        .filter(func.upper(AssetType.code) == "CARD", AssetType.active.is_(True))
        .first()
    )
    if not parent:
        current_app.logger.warning("card_asset_type_ids: no AssetType with code=CARD found")
        return []

    ids = [parent.id]

    child_ids = (
        db.query(AssetType.id)
        .filter(AssetType.active.is_(True), AssetType.parent_id == parent.id)
        .all()
    )
    ids.extend([cid for (cid,) in child_ids])

    return ids


def get_tco_alerts(db):
    today = date.today()

    window_start = today - timedelta(days=30)
    window_end = today + timedelta(days=30)

    courses = (
        db.query(Course)
        .filter(
            Course.start_date.isnot(None),
            Course.start_date <= window_end,
            func.coalesce(Course.end_date, Course.start_date) >= window_start,
        )
        .all()
    )

    # Tipos de tarjeta válidos
    card_ids = card_asset_type_ids(db)

    def required_cards_for_course(course: Course) -> int:
        """
        Requeridas = suma de requirements cuyo asset_type_id está en card_ids.
        Si no hay requirements válidos, fallback a course.trainees.
        """
        req = 0
        if card_ids:
            try:
                req = (
                    db.query(func.coalesce(func.sum(CourseAssetRequirement.quantity), 0))
                    .filter(
                        CourseAssetRequirement.course_id == course.id,
                        CourseAssetRequirement.active.is_(True),
                        CourseAssetRequirement.asset_type_id.in_(card_ids),
                    )
                    .scalar()
                )
                req = int(req or 0)
            except Exception:
                current_app.logger.exception(
                    "required_cards_for_course failed (course_id=%s)", course.id
                )
                req = 0

        trainees = int(getattr(course, "trainees", 0) or 0)
        return req if req > 0 else trainees

    def linked_cards_for_course(course_id: int) -> int:
        """
        Cuenta tarjetas enlazadas vivas (released_at IS NULL).
        """
        if not card_ids:
            return 0

        try:
            n = (
                db.query(func.count(func.distinct(Assignment.device_id)))
                .join(Device, Device.id == Assignment.device_id)
                .filter(
                    Assignment.course_id == course_id,
                    Assignment.released_at.is_(None),
                    Device.asset_type_id.in_(card_ids),
                )
                .scalar()
            )
            return int(n or 0)
        except Exception:
            current_app.logger.exception(
                "linked_cards_for_course failed (course_id=%s)", course_id
            )
            return 0

    def bump_severity(cur: str | None, new: str) -> str:
        if not cur:
            return new
        return new if SEV_RANK.get(new, 0) > SEV_RANK.get(cur, 0) else cur

    alerts = []

    for c in courses:
        sd = c.start_date
        ed = c.end_date
        if not sd:
            continue

        req = required_cards_for_course(c)
        linked = linked_cards_for_course(c.id)

        days_to_start = (sd - today).days

        # Estados lógicos por fechas
        course_finished = (ed is not None) and (ed < today)
        course_active = (sd <= today) and (ed is None or ed >= today)
        course_planned = sd > today
        planned_within_3_days = course_planned and (0 <= days_to_start <= 3)

        reasons = []
        severity = None

        # ------------------------------------------------------------------
        # 1) Cards mismatch UNIFICADO
        # ------------------------------------------------------------------
        should_alert_mismatch = (not course_finished) and (
            course_active or planned_within_3_days
        )

        if should_alert_mismatch and req > 0 and linked != req:
            diff = linked - req

            # Severidad por tamaño del desajuste
            size_sev = "warning" if abs(diff) <= 2 else "critical"

            if planned_within_3_days:
                # Severidad por proximidad al inicio
                time_sev = (
                    "notice"
                    if days_to_start == 3
                    else ("warning" if days_to_start == 2 else "critical")
                )
                sev = (
                    time_sev
                    if SEV_RANK.get(time_sev, 0) >= SEV_RANK.get(size_sev, 0)
                    else size_sev
                )

                if linked == 0:
                    text = (
                        f"Course starts in {days_to_start} day(s) "
                        f"and has 0 cards linked (required {req})."
                    )
                    legacy_keys = ["tco_start_soon_no_cards"]
                elif linked < req:
                    text = (
                        f"Course starts in {days_to_start} day(s) "
                        f"and is missing cards ({linked}/{req})."
                    )
                    legacy_keys = ["tco_start_soon_missing_cards"]
                else:
                    text = (
                        f"Course starts in {days_to_start} day(s) "
                        f"and has extra cards linked ({linked}/{req})."
                    )
                    legacy_keys = []
            else:
                sev = size_sev
                if linked < req:
                    text = f"Missing cards: linked {linked}/{req}. Diff={diff}."
                else:
                    text = f"Extra cards: linked {linked}/{req}. Diff={diff}."
                legacy_keys = []

            severity = bump_severity(severity, sev)
            reasons.append(
                {
                    "key": "tco_cards_mismatch",
                    "text": text,
                    "legacy_keys": legacy_keys,
                    "extra": {
                        "diff": diff,
                        "required": req,
                        "linked": linked,
                        "days_to_start": days_to_start,
                    },
                }
            )

        # ------------------------------------------------------------------
        # 2) Curso finalizado con tarjetas aún enlazadas
        # ------------------------------------------------------------------
        if ed and linked > 0:
            days_since_end = (today - ed).days
            if 1 <= days_since_end <= 7:
                severity = bump_severity(severity, "warning")
                reasons.append(
                    {
                        "key": "tco_course_ended_recent",
                        "text": (
                            f"Course ended {days_since_end} day(s) ago "
                            f"and still has {linked} cards linked."
                        ),
                    }
                )
            elif days_since_end > 7:
                severity = bump_severity(severity, "critical")
                reasons.append(
                    {
                        "key": "tco_course_ended_old",
                        "text": (
                            f"Course ended {days_since_end} day(s) ago "
                            f"and still has {linked} cards linked."
                        ),
                    }
                )

        if reasons:
            # keys = key principal + legacy_keys (compatibilidad)
            keys = []
            for r in reasons:
                if r.get("key"):
                    keys.append(r["key"])
                for lk in (r.get("legacy_keys") or []):
                    keys.append(lk)
            keys = list(dict.fromkeys(keys))  # únicos, mantiene orden

            message = "\n".join(f"- {r['text']}" for r in reasons)

            alerts.append(
                {
                    "type": "course_agg",
                    "severity": severity or "notice",
                    "code": "tco_course_summary",
                    "message": message,
                    "course": c,
                    "course_id": c.id,
                    "reasons": reasons,
                    "keys": keys,
                    "extra": {
                        "required": req,
                        "linked": linked,
                        "days_to_start": days_to_start,
                    },
                }
            )

    return alerts


def get_cards_vs_trainees_alerts(db, managed_by: str | None = None):
    """
    Cursos actuales/futuros donde:
      assigned_cards != trainees

    Retorna lista de alerts:
      {
        "type": "cards_missing" | "cards_extra",
        "severity": "notice",
        "course": <Course>,
        "message": "...",
        "diff": int,
        "assigned": int,
        "required": int
      }

    managed_by: filtra por AssetType.managed_by_department (ej "TCO", "ITC support")
    """
    # Importes locales para evitar circular imports si aplica

    # Trainees requeridos
    # assigned_cards = número de devices tipo CARDS asignados al curso
    # required_cards = trainees del curso (si trainees es None => 0)
    # diff = required - assigned

    # Subquery: contar devices asignados (CARDS) por curso
    # Nota: depende de tu modelo (Assignment / Device / AssetType). Ajusta si tu esquema difiere.
    q = (
        db.query(
            Course,
            func.coalesce(Course.trainees, 0).label("required_cards"),
            func.count(Device.id).label("assigned_cards"),
        )
        .outerjoin(Assignment, Assignment.course_id == Course.id)
        .outerjoin(Device, Device.id == Assignment.device_id)
        .outerjoin(AssetType, AssetType.id == Device.asset_type_id)
    )

    # Solo CARDS (por código del AssetType o por root/parent dependiendo de tu diseño)
    # Aquí se usa AssetType.code == "CARDS" (si en tu DB es distinto, cambia este filtro).
    q = q.filter(AssetType.code == "CARDS")

    # Filtrar por departamento que gestiona el tipo, si se pide
    if managed_by:
        q = q.filter(AssetType.managed_by_department == managed_by)

    # Agrupar por curso
    q = q.group_by(Course.id)

    # Traemos todo y generamos alerts en Python (más simple y legible)
    rows = q.all()

    alerts = []
    for course, required, assigned in rows:
        required = int(required or 0)
        assigned = int(assigned or 0)
        diff = required - assigned

        if diff == 0:
            continue

        # Mensaje “técnico” (si no lo quieres en UI, perfecto: lo puedes ignorar en el template)
        msg = f"Cards not linked ({assigned}) do not match required ({required}). Diff={diff}."

        alerts.append({
            "type": "cards_missing" if diff > 0 else "cards_extra",
            "severity": "notice",
            "course": course,
            "course_id": getattr(course, "id", None),
            "message": msg,
            "diff": diff,
            "assigned": assigned,
            "required": required,
            "responsible": getattr(course, "responsible", None),
        })

    return alerts