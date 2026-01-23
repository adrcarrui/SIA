from datetime import datetime, timedelta, timezone
from sqlalchemy.dialects.postgresql import insert

from app.models import AlertState  # donde lo hayas metido

TERMINAL = {"ignored", "resolved"}

def now_utc():
    return datetime.now(timezone.utc)

def scope_for_user(user) -> str:
    role = (getattr(user, "role", "") or "").strip().lower()
    dept = (getattr(user, "department", "") or "").strip().lower()
    if "admin" in role:
        return "admin"
    if dept == "tco":
        return "tco"
    if dept == "itc support":
        return "itc"
    return "other"

def upsert_seen_alert(db, scope: str, course_id: int, alert_key: str, user_id: int | None = None):
    """
    Postgres UPSERT: marca que la alerta existe en este cálculo (seen).
    No cambia status si ya está ack/snoozed/ignored.
    """
    now = now_utc()
    stmt = insert(AlertState).values(
        scope=scope,
        course_id=course_id,
        alert_key=alert_key,
        status="open",
        first_seen_at=now,
        last_seen_at=now,
        occurrences=1,
        updated_by_user_id=user_id,
        updated_at=now,
    ).on_conflict_do_update(
        constraint="uq_alert_states_scope_course_key",
        set_={
            "last_seen_at": now,
            "occurrences": AlertState.occurrences + 1,
            # no tocamos status / snooze / note
        }
    )
    db.execute(stmt)

def load_state_map(db, scope: str, course_ids: list[int]):
    if not course_ids:
        return {}
    rows = (
        db.query(AlertState)
        .filter(AlertState.scope == scope, AlertState.course_id.in_(course_ids))
        .all()
    )
    return {(r.course_id, r.alert_key): r for r in rows}

def apply_alert_states(db, scope: str, alerts: list[dict]):
    """
    Filtra reasons por estado:
      - ignored/resolved => ocultar
      - snoozed (ahora < snooze_until) => ocultar
      - ack => visible pero marcado
    Si un curso se queda sin reasons visibles => desaparece el alert.
    """
    now = now_utc()
    course_ids = sorted({
        a.get("course_id") or getattr(a.get("course"), "id", None)
        for a in alerts
        if (a.get("course_id") or getattr(a.get("course"), "id", None))
    })

    state_map = load_state_map(db, scope, course_ids)

    out = []
    for a in alerts:
        cid = a.get("course_id") or getattr(a.get("course"), "id", None)
        reasons = a.get("reasons") or []
        if not cid or not reasons:
            out.append(a)
            continue

        visible = []
        hidden = 0

        for r in reasons:
            k = r.get("key")
            txt = r.get("text", "")
            st = state_map.get((cid, k))

            if st:
                if st.status in TERMINAL:
                    hidden += 1
                    continue

                if st.status == "snoozed" and st.snooze_until and now < st.snooze_until:
                    hidden += 1
                    continue

                if st.status == "ack":
                    visible.append({
                        "key": k,
                        "text": txt,
                        "state": "ack",
                        "note": st.note,
                        "snooze_until": st.snooze_until.isoformat() if st.snooze_until else None,
                    })
                    continue

            visible.append({"key": k, "text": txt, "state": None, "note": None, "snooze_until": None})

        if not visible:
            continue

        # reconstruye mensaje con ACK visual
        lines = []
        for r in visible:
            suffix = " [ACK]" if r["state"] == "ack" else ""
            lines.append(f"- {r['text']}{suffix}")

        a2 = dict(a)
        a2["reasons"] = visible
        a2["keys"] = [r["key"] for r in visible]
        a2["message"] = "\n".join(lines)
        a2["hidden_reasons"] = hidden
        out.append(a2)

    return out
