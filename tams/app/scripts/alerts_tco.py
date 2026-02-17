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

    def active_missing_window_days(sd: date, ed: date | None) -> int:
        """
        Ventana (en días) durante la cual, con el curso activo, avisamos de faltan tarjetas.
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

    def linked_cards_for_course_split(course_id: int) -> tuple[int, int]:
        """
        Cuenta tarjetas enlazadas vivas (released_at IS NULL), separando:
        - permanentes (is_temporary = False)
        - temporales  (is_temporary = True)
        """
        if not card_ids:
            return (0, 0)

        try:
            base = (
                db.query(func.count(func.distinct(Assignment.device_id)))
                .join(Device, Device.id == Assignment.device_id)
                .filter(
                    Assignment.course_id == course_id,
                    Assignment.released_at.is_(None),
                    Device.asset_type_id.in_(card_ids),
                )
            )

            linked_perm = base.filter(Assignment.is_temporary.is_(False)).scalar() or 0
            linked_temp = base.filter(Assignment.is_temporary.is_(True)).scalar() or 0

            return (int(linked_perm), int(linked_temp))
        except Exception:
            current_app.logger.exception(
                "linked_cards_for_course_split failed (course_id=%s)", course_id
            )
            return (0, 0)

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

        linked_perm, linked_temp = linked_cards_for_course_split(c.id)
        linked = linked_perm                  # <- IMPORTANT: planned/active usan SOLO permanentes
        linked_total = linked_perm + linked_temp  # <- finished usa total

        days_to_start = (sd - today).days

        # Estados lógicos por fechas
        course_finished = (ed is not None) and (ed < today)
        course_active = (sd <= today) and (ed is None or ed >= today)
        course_planned = sd > today
        planned_within_3_days = course_planned and (0 <= days_to_start <= 3)

        # Días desde inicio (0 = día de inicio)
        days_since_start = (today - sd).days

        # Ventana 25% inicial (floor, min 1)
        miss_window = active_missing_window_days(sd, ed)
        missing_window_open = course_active and (0 <= days_since_start < miss_window)

        reasons = []
        severity = None

        # ------------------------------------------------------------------
        # 1) Faltan tarjetas requeridas
        #    - Planned (0..3): SOLO missing (contra permanentes)
        #    - Active: SOLO missing y SOLO en el 25% inicial (contra permanentes)
        # ------------------------------------------------------------------
        if req > 0 and not course_finished:

            # PLANNED: faltan (solo permanentes vs requeridas)
            if planned_within_3_days and linked < req:
                diff = linked - req  # negativo
                size_sev = "warning" if abs(diff) <= 2 else "critical"

                '''time_sev = (
                    "notice"
                    if days_to_start == 3
                    else ("warning" if days_to_start == 2 else "critical")
                )
                sev = (
                    time_sev
                    if SEV_RANK.get(time_sev, 0) >= SEV_RANK.get(size_sev, 0)
                    else size_sev
                )'''
                sev = (
                    "notice"
                    if days_to_start == 3
                    else ("warning" if days_to_start == 2 else "critical")
                )

                if linked == 0:
                    text = (
                        f"Course starts in {days_to_start} day(s) "
                        f"and has 0 permanent cards linked (required {req}). "
                        f"(temp linked: {linked_temp})"
                    )
                    legacy_keys = ["tco_start_soon_no_cards"]
                else:
                    text = (
                        f"Course starts in {days_to_start} day(s) "
                        f"and is missing permanent cards ({linked}/{req}). "
                        f"(temp linked: {linked_temp})"
                    )
                    legacy_keys = ["tco_start_soon_missing_cards"]

                severity = bump_severity(severity, sev)
                reasons.append(
                    {
                        "key": "tco_cards_mismatch",
                        "text": text,
                        "legacy_keys": legacy_keys,
                        "extra": {
                            "diff": diff,
                            "required": req,
                            "linked": linked,  # permanentes
                            "linked_permanent": linked_perm,
                            "linked_temporary": linked_temp,
                            "linked_total": linked_total,
                            "days_to_start": days_to_start,
                        },
                    }
                )

            # ACTIVE: faltan (solo permanentes vs requeridas) SOLO en ventana 25%
            elif missing_window_open and linked < req:
                diff = linked - req  # negativo
                sev = "warning" if abs(diff) <= 2 else "critical"

                text = (
                    f"Missing permanent cards: linked {linked}/{req}. "
                    f"(temp linked: {linked_temp}). "
                    f"(Day {days_since_start + 1}, window {miss_window} day(s))."
                )

                severity = bump_severity(severity, sev)
                reasons.append(
                    {
                        "key": "tco_cards_mismatch",
                        "text": text,
                        "legacy_keys": [],
                        "extra": {
                            "diff": diff,
                            "required": req,
                            "linked": linked,  # permanentes
                            "linked_permanent": linked_perm,
                            "linked_temporary": linked_temp,
                            "linked_total": linked_total,
                            "days_since_start": days_since_start,
                            "missing_window_days": miss_window,
                        },
                    }
                )

        # ------------------------------------------------------------------
        # 2) Curso finalizado con tarjetas aún enlazadas (permanentes y/o temporales)
        # ------------------------------------------------------------------
        if ed and ed < today and linked_total > 0:
            days_since_end = (today - ed).days
            if 1 <= days_since_end <= 7:
                severity = bump_severity(severity, "warning")
                reasons.append(
                    {
                        "key": "tco_course_ended_recent",
                        "text": (
                            f"Course ended {days_since_end} day(s) ago "
                            f"and still has {linked_total} cards linked "
                            f"({linked_perm} permanent, {linked_temp} temporary)."
                        ),
                        "extra": {
                            "linked_total": linked_total,
                            "linked_permanent": linked_perm,
                            "linked_temporary": linked_temp,
                            "days_since_end": days_since_end,
                        },
                    }
                )
            elif days_since_end > 7:
                severity = bump_severity(severity, "critical")
                reasons.append(
                    {
                        "key": "tco_course_ended_old",
                        "text": (
                            f"Course ended {days_since_end} day(s) ago "
                            f"and still has {linked_total} cards linked "
                            f"({linked_perm} permanent, {linked_temp} temporary)."
                        ),
                        "extra": {
                            "linked_total": linked_total,
                            "linked_permanent": linked_perm,
                            "linked_temporary": linked_temp,
                            "days_since_end": days_since_end,
                        },
                    }
                )

        if reasons:
            keys = []
            for r in reasons:
                if r.get("key"):
                    keys.append(r["key"])
                for lk in (r.get("legacy_keys") or []):
                    keys.append(lk)
            keys = list(dict.fromkeys(keys))

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
                        "linked": linked,  # permanentes (planned/active)
                        "linked_permanent": linked_perm,
                        "linked_temporary": linked_temp,
                        "linked_total": linked_total,
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