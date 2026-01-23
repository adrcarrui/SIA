from app.scripts.alerts_itc import get_itc_upcoming_and_overdue_alerts
from app.scripts.alerts_tco import get_tco_alerts
from datetime import date
from flask import current_app
from app.scripts.alert_state_service import (
    upsert_seen_alert,
    apply_alert_states,
)


def _aggregate_alerts_by_course_and_severity(alerts: list[dict]) -> list[dict]:
    """
    Agrupa alertas por (course_id, severity). Devuelve 1 alerta por curso y severidad.
    Une mensajes, elimina duplicados manteniendo orden.
    """
    buckets: dict[tuple[int, str], dict] = {}

    for a in alerts:
        c = a.get("course")
        cid = getattr(c, "id", None)
        sev = (a.get("severity") or "").strip().lower()

        # Si no hay curso o severidad, lo dejamos pasar sin tocar
        if not cid or not sev:
            # clave única para que no se pierda
            key = (id(a), sev or "notice")
            buckets[key] = a
            continue

        key = (cid, sev)

        if key not in buckets:
            buckets[key] = {
                "type": "course_agg",
                "severity": sev,
                "course": c,
                "messages": [],
                "types": [],
            }

        msg = (a.get("message") or "").strip()
        if msg and msg not in buckets[key]["messages"]:
            buckets[key]["messages"].append(msg)

        t = (a.get("type") or "").strip()
        if t and t not in buckets[key]["types"]:
            buckets[key]["types"].append(t)

    # Construimos salida final
    out: list[dict] = []
    for key, item in buckets.items():
        # Si ya era una alerta "raw" sin curso/sev válida
        if "messages" not in item:
            out.append(item)
            continue

        msgs = item["messages"]
        if len(msgs) == 0:
            merged_message = ""
        elif len(msgs) == 1:
            merged_message = msgs[0]
        else:
            merged_message = "\n".join(f"- {m}" for m in msgs)

        out.append({
            "type": "course_agg",
            "severity": item["severity"],
            "course": item["course"],
            "message": merged_message,
            # opcional, por si quieres debug o tooltips
            "types": item["types"],
            "count": len(msgs),
        })

    # Orden sugerido: primero critical, luego warning, luego notice, y dentro por fecha de inicio si existe
    sev_rank = {"critical": 0, "warning": 1, "notice": 2}
    def sort_key(a):
        sev = (a.get("severity") or "notice").lower()
        c = a.get("course")
        start = getattr(c, "start_date", None) if c else None
        return (sev_rank.get(sev, 9), start or date.max, getattr(c, "id", 0) if c else 0)

    out.sort(key=sort_key)
    return out

def get_alerts_for_user(db, user):
    role = (getattr(user, "role", "") or "").strip().lower()
    dept_raw = (getattr(user, "department", "") or "").strip()
    dept = dept_raw.lower()

    # Roles/dept robustos
    is_admin = ("admin" in role)
    is_tco = (dept == "tco") or dept.startswith("tco") or ("tco" in dept)
    is_itc = (dept == "itc support") or dept.startswith("itc") or ("itc" in dept)

    # Scope para AlertState
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
        "GA: user=%s role=%r dept=%r admin=%s tco=%s itc=%s tco_n=%s itc_n=%s",
        getattr(user, "email", None),
        getattr(user, "role", None),
        dept_raw,
        is_admin, is_tco, is_itc,
        len(alerts_tco), len(alerts_itc),
    )

    # Selección por perfil
    if is_admin:
        alerts = alerts_tco + alerts_itc
    elif is_tco:
        alerts = alerts_tco
    elif is_itc:
        alerts = alerts_itc
    else:
        alerts = []

    # 1) Agregamos por curso/severidad (como ya hacías)
    alerts = _aggregate_alerts_by_course_and_severity(alerts)

    # 2) UPSERT "seen" en alert_states por cada reason key
    #    (esto permite first_seen/last_seen/occurrences)
    user_id = getattr(user, "id", None)

    try:
        for a in alerts:
            cid = a.get("course_id") or getattr(a.get("course"), "id", None)
            if not cid:
                continue

            # Preferimos reasons con key; fallback a keys si viniera
            reasons = a.get("reasons") or []
            if reasons:
                for r in reasons:
                    k = r.get("key")
                    if k:
                        upsert_seen_alert(db, scope, int(cid), str(k), user_id=user_id)
            else:
                for k in (a.get("keys") or []):
                    upsert_seen_alert(db, scope, int(cid), str(k), user_id=user_id)

        db.commit()
    except Exception:
        # Si esto falla no queremos romper el dashboard
        current_app.logger.exception("AlertState upsert_seen_alert failed")
        try:
            db.rollback()
        except Exception:
            pass

    # 3) Aplicar estados (oculta snoozed/ignored, marca ack)
    try:
        alerts = apply_alert_states(db, scope, alerts)
    except Exception:
        current_app.logger.exception("apply_alert_states failed")

    return alerts