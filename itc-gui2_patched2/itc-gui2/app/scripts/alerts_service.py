from flask import current_app
from app.scripts.alerts_itc import get_itc_upcoming_and_overdue_alerts
from app.scripts.alerts_tco import get_tco_alerts
from app.scripts.alert_state_service import upsert_seen_alert, apply_alert_states, resolve_missing_alerts
from app.models import AlertState, Course

SEV_RANK = {"notice": 1, "warning": 2, "critical": 3}

def _aggregate_alerts_by_course_and_severity(alerts: list[dict]) -> list[dict]:
    """
    Agrega alertas por curso.
    - Conserva reasons (key + text)
    - Deduplica por key
    - Calcula severidad máxima
    - Mantiene compatibilidad con UI antigua (count, types)
    """

    by_course = {}

    for a in alerts:
        # Determinar curso
        course = a.get("course")
        course_id = a.get("course_id") or (course.id if course else None)
        if not course_id:
            continue

        bucket = by_course.get(course_id)
        if not bucket:
            bucket = {
                "type": "course_agg",
                "code": a.get("code", "course_agg"),
                "course": course,
                "course_id": course_id,
                "severity": a.get("severity"),
                "reasons": [],
                "keys": [],
                "types": [],
                "count": 0,
                "extra": {},
            }
            by_course[course_id] = bucket

        # Severidad máxima
        cur_sev = bucket.get("severity")
        new_sev = a.get("severity")
        if new_sev and (
            not cur_sev or SEV_RANK.get(new_sev, 0) > SEV_RANK.get(cur_sev, 0)
        ):
            bucket["severity"] = new_sev

        # Reasons (preferente)
        reasons = a.get("reasons") or []
        for r in reasons:
            k = r.get("key")
            if not k:
                continue
            if k in bucket["keys"]:
                continue

            bucket["reasons"].append({
                "key": k,
                "text": r.get("text", ""),
                # para poder calcular severidad efectiva por reasons visibles
                "severity": (a.get("severity") or bucket.get("severity") or "notice"),
                # estos campos los rellenará apply_alert_states
                "state": r.get("state"),
                "note": r.get("note"),
                "snooze_until": r.get("snooze_until"),
            })
            bucket["keys"].append(k)
            bucket["types"].append(k)
            bucket["count"] += 1

        # Compatibilidad: si no había reasons pero sí type (legacy)
        if not reasons and a.get("type"):
            t = a.get("type")
            if t not in bucket["types"]:
                bucket["types"].append(t)
                bucket["count"] += 1

        # Extra: merge superficial (sin pisar lo existente)
        extra = a.get("extra") or {}
        for k, v in extra.items():
            bucket["extra"].setdefault(k, v)

    # Reconstruir message final
    out = []
    for b in by_course.values():
        if b["reasons"]:
            b["message"] = "\n".join(
                f"- {r['text']}" for r in b["reasons"]
            )
        else:
            b["message"] = b.get("message", "")

        out.append(b)

    return out


def get_alerts_for_user(db, user, include_hidden: bool = False):
    role = (getattr(user, "role", "") or "").strip().lower()
    dept_raw = (getattr(user, "department", "") or "").strip()
    dept = dept_raw.lower()

    is_admin = ("admin" in role)
    is_tco = (dept == "tco") or dept.startswith("tco") or ("tco" in dept)
    is_itc = (dept == "itc support") or dept.startswith("itc") or ("itc" in dept)

    if is_admin:
        scope = "admin"
    elif is_tco:
        scope = "tco"
    elif is_itc:
        scope = "itc"
    else:
        scope = "other"

    alerts_tco = []
    alerts_itc = []

    if is_admin or is_tco:
        try:
            alerts_tco = get_tco_alerts(db) or []
        except Exception:
            current_app.logger.exception("get_tco_alerts failed")
            alerts_tco = []

    if is_admin or is_itc:
        try:
            alerts_itc = get_itc_upcoming_and_overdue_alerts(db) or []
        except Exception:
            current_app.logger.exception("get_itc_upcoming_and_overdue_alerts failed")
            alerts_itc = []

    current_app.logger.warning(
        "GA: user=%s role=%r dept=%r admin=%s tco=%s itc=%s tco_n=%s itc_n=%s include_hidden=%s",
        getattr(user, "email", None),
        getattr(user, "role", None),
        dept_raw,
        is_admin, is_tco, is_itc,
        len(alerts_tco), len(alerts_itc),
        include_hidden,
    )

    if is_admin:
        alerts = alerts_tco + alerts_itc
    elif is_tco:
        alerts = alerts_tco
    elif is_itc:
        alerts = alerts_itc
    else:
        alerts = []

    # ---------------------------------------------------------------------
    # ✅ CLAVE: si include_hidden=True, inyectar alertas persistidas en DB
    # (snoozed/ignored/ack) aunque el motor ya no las genere ahora.
    # ---------------------------------------------------------------------
    if include_hidden and scope != "other":
        try:
            rows = (
                db.query(AlertState)
                .filter(AlertState.scope == scope)
                .filter(AlertState.status.in_(["snoozed", "ignored", "acked"]))
                .all()
            ) or []

            # Index de lo ya presente (course_id, alert_key)
            present = set()
            for a in alerts:
                cid = a.get("course_id") or getattr(a.get("course"), "id", None)
                if not cid:
                    continue
                for r in (a.get("reasons") or []):
                    k = (r or {}).get("key")
                    if k:
                        present.add((int(cid), str(k)))

            injected = 0

            for st in rows:
                cid = int(st.course_id)
                key = str(st.alert_key or "").strip()
                if not key:
                    continue

                if (cid, key) in present:
                    continue

                # cargar el curso (opcional, pero mejora la UX)
                course_obj = None
                try:
                    course_obj = db.query(Course).get(cid)
                except Exception:
                    course_obj = None

                alerts.append({
                    "course_id": cid,
                    "course": course_obj,
                    "severity": "notice",
                    "reasons": [{
                        "key": key,
                        "text": "Hidden alert (state stored)",
                    }],
                })

                present.add((cid, key))
                injected += 1

            current_app.logger.warning(
                "GA: injected_hidden=%s scope=%s include_hidden=%s rows=%s",
                injected, scope, include_hidden, len(rows)
            )

        except Exception:
            current_app.logger.exception("GA: inject hidden alert_states failed")

    # 1) Agregamos por curso/severidad
    alerts = _aggregate_alerts_by_course_and_severity(alerts)

    # 2.5) Auto-close: marcar como done las keys que ya no aparecen para ese curso/scope
# 2.5) Auto-close: marcar como done las keys que ya no aparecen para ese curso/scope
    if scope != "other":
        try:
            # Mapa curso -> keys activas actuales (lo que el motor genera ahora)
            active_by_course: dict[int, set[str]] = {}
            for a in alerts:
                cid = a.get("course_id") or getattr(a.get("course"), "id", None)
                if not cid:
                    continue
                cid = int(cid)
                ks = set()
                for k in (a.get("keys") or []):
                    if k:
                        ks.add(str(k))
                active_by_course[cid] = ks

            # Cursos a barrer:
            # - los que tienen alertas ahora (active_by_course)
            # - + los que tienen estados no terminales en BD (aunque ya no salgan en UI)
            rows = (
                db.query(AlertState.course_id)
                .filter(AlertState.scope == scope)
                .filter(AlertState.status.in_(["open", "acked", "snoozed"]))
                .distinct()
                .all()
            )
            course_ids_to_sweep = set(active_by_course.keys()) | {int(r[0]) for r in rows}

            for cid in course_ids_to_sweep:
                resolve_missing_alerts(
                    db,
                    scope=scope,
                    course_id=cid,
                    active_keys=active_by_course.get(cid, set()),
                )

            db.commit()
        except Exception:
            current_app.logger.exception("GA: resolve_missing_alerts failed")
            try:
                db.rollback()
            except Exception:
                pass

            db.commit()
        except Exception:
            current_app.logger.exception("GA: resolve_missing_alerts failed")
            try:
                db.rollback()
            except Exception:
                pass


    # En tu DB existe updated_by (varchar)
    updated_by = getattr(user, "email", None) or getattr(user, "username", None)

    # 2) UPSERT "seen" en alert_states por cada reason key
    try:
        for a in alerts:
            cid = a.get("course_id") or getattr(a.get("course"), "id", None)
            if not cid:
                continue

            reasons = a.get("reasons") or []
            if reasons:
                for r in reasons:
                    k = (r or {}).get("key")
                    if k:
                        upsert_seen_alert(
                            db,
                            scope,
                            int(cid),
                            str(k),
                            updated_by=updated_by
                        )
            else:
                for k in (a.get("keys") or []):
                    if k:
                        upsert_seen_alert(
                            db,
                            scope,
                            int(cid),
                            str(k),
                            updated_by=updated_by
                        )

        db.commit()
    except Exception:
        current_app.logger.exception("AlertState upsert_seen_alert failed")
        try:
            db.rollback()
        except Exception:
            pass

    # 3) Aplicar estados (oculta snoozed/ignored si include_hidden=False)
    try:
        alerts = apply_alert_states(db, scope, alerts, include_hidden=include_hidden)
        current_app.logger.warning(
            "GA: after_apply n=%s scope=%s include_hidden=%s",
            len(alerts), scope, include_hidden
        )
    except Exception:
        current_app.logger.exception("apply_alert_states failed")

    # 4) Scope para frontend
    for a in alerts:
        a["scope"] = scope

    return alerts

def build_alerts_summary(db, user, include_hidden=False):
    alerts = get_alerts_for_user(db, user, include_hidden=include_hidden) or []

    summary = {
        "notice": 0,
        "warning": 0,
        "critical": 0,
    }

    for a in alerts:
        sev = (a.get("severity") or "").lower()
        if sev in summary:
            summary[sev] += 1

    return summary
