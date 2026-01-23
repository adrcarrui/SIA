from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.models import AlertState  # donde lo hayas metido

TERMINAL = {"ignored", "resolved"}

VALID_STATUS = {"open", "acked", "snoozed", "ignored"}

def now_utc():
    return datetime.now(timezone.utc)

def _norm_scope(scope: str) -> str:
    return (scope or "").strip().lower()


def _norm_key(k: str) -> str:
    return (k or "").strip()

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

def clear_alert_state(db, scope: str, course_id: int, alert_key: str, updated_by: str | None = None):
    """
    Resetea a OPEN (y limpia snooze_until/note) sin borrar fila.
    """
    scope = _norm_scope(scope)
    alert_key = _norm_key(alert_key)
    ts = now_utc()

    upsert_seen_alert(db, scope, course_id, alert_key, updated_by=updated_by)

    stmt = text("""
        UPDATE alert_states
        SET
            status = 'open',
            snooze_until = NULL,
            note = NULL,
            updated_by = :updated_by,
            updated_at = :ts
        WHERE scope = :scope AND course_id = :course_id AND alert_key = :alert_key
    """)
    db.execute(stmt, {
        "scope": scope,
        "course_id": int(course_id),
        "alert_key": alert_key,
        "updated_by": updated_by,
        "ts": ts,
    })


def upsert_seen_alert(db, scope: str, course_id: int, alert_key: str, updated_by: str | None = None):
    """
    Registra que la alerta (scope, course_id, alert_key) ha sido "vista" en este render:
    - si no existe: INSERT status=open, occurrences=1
    - si existe: UPDATE last_seen_at=now, occurrences += 1
    """
    scope = _norm_scope(scope)
    alert_key = _norm_key(alert_key)
    if not scope or not course_id or not alert_key:
        return

    ts = now_utc()

    stmt = text("""
        INSERT INTO alert_states (
            scope, course_id, alert_key,
            status,
            first_seen_at, last_seen_at,
            occurrences,
            updated_by, updated_at
        )
        VALUES (
            :scope, :course_id, :alert_key,
            'open',
            :ts, :ts,
            1,
            :updated_by, :ts
        )
        ON CONFLICT ON CONSTRAINT uq_alert_states_scope_course_key
        DO UPDATE SET
            last_seen_at = :ts,
            occurrences = alert_states.occurrences + 1
        RETURNING id
    """)

    db.execute(stmt, {
        "scope": scope,
        "course_id": int(course_id),
        "alert_key": alert_key,
        "ts": ts,
        "updated_by": updated_by,
    })


def set_alert_state(
    db,
    scope: str,
    course_id: int,
    alert_key: str,
    status: str,
    snooze_until=None,
    note: str | None = None,
    updated_by: str | None = None,
):
    """
    Cambia estado de una alerta:
      - acked / ignored / open / snoozed
    Si snoozed -> requiere snooze_until
    """
    scope = _norm_scope(scope)
    alert_key = _norm_key(alert_key)
    status = (status or "").strip().lower()

    if status not in VALID_STATUS:
        raise ValueError(f"Invalid status: {status}")

    if status == "snoozed" and not snooze_until:
        raise ValueError("snooze_until is required for snoozed status")

    ts = now_utc()

    # Aseguramos que exista fila
    upsert_seen_alert(db, scope, course_id, alert_key, updated_by=updated_by)

    stmt = text("""
        UPDATE alert_states
        SET
            status = :status,
            snooze_until = :snooze_until,
            note = :note,
            updated_by = :updated_by,
            updated_at = :ts
        WHERE scope = :scope AND course_id = :course_id AND alert_key = :alert_key
    """)

    db.execute(stmt, {
        "scope": scope,
        "course_id": int(course_id),
        "alert_key": alert_key,
        "status": status,
        "snooze_until": snooze_until,
        "note": note,
        "updated_by": updated_by,
        "ts": ts,
    })


def load_states_for_alerts(db, scope: str, alerts: list[dict]) -> Dict[Tuple[int, str], dict]:
    """
    Devuelve un mapa (course_id, alert_key) -> state dict
    Sólo consulta alert_states (sin join a users, porque tu tabla no tiene updated_by_user_id).
    """
    scope = _norm_scope(scope)
    pairs: List[Tuple[int, str]] = []

    for a in alerts:
        cid = a.get("course_id")
        if not cid:
            course = a.get("course")
            cid = getattr(course, "id", None)
        if not cid:
            continue

        for k in (a.get("keys") or []):
            kk = _norm_key(k)
            if kk:
                pairs.append((int(cid), kk))

        for r in (a.get("reasons") or []):
            kk = _norm_key((r or {}).get("key") or "")
            if kk:
                pairs.append((int(cid), kk))

    # dedup
    pairs = list(set(pairs))
    if not pairs:
        return {}

    # Construimos IN con tuples (Postgres soporta IN ((a,b),(c,d)) )
    # SQLAlchemy text() no expande tuples automáticamente, así que hacemos placeholders manuales
    binds = {"scope": scope}
    values_sql = []
    for i, (cid, k) in enumerate(pairs):
        binds[f"cid_{i}"] = cid
        binds[f"key_{i}"] = k
        values_sql.append(f"(:cid_{i}, :key_{i})")

    stmt = text(f"""
        SELECT
            course_id, alert_key, status, snooze_until, note, updated_by, updated_at
        FROM alert_states
        WHERE scope = :scope
          AND (course_id, alert_key) IN ({",".join(values_sql)})
    """)

    rows = db.execute(stmt, binds).fetchall()

    out: Dict[Tuple[int, str], dict] = {}
    for row in rows:
        # row mapping depende del driver; soportamos tuple-style
        course_id = row[0]
        alert_key = row[1]
        out[(int(course_id), str(alert_key))] = {
            "status": row[2],
            "snooze_until": row[3],
            "note": row[4],
            "updated_by": row[5],
            "updated_at": row[6],
        }
    return out


def apply_alert_states(db, scope: str, alerts: list[dict], include_hidden: bool = False) -> list[dict]:
    """
    Rellena r.state/r.note/r.snooze_until desde DB.
    Oculta snoozed/ignored si include_hidden=False.
    """
    state_map = load_states_for_alerts(db, scope, alerts)

    now = now_utc()
    out = []

    for a in alerts:
        cid = a.get("course_id") or getattr(a.get("course"), "id", None)

        reasons = a.get("reasons") or []
        new_reasons = []

        for r in reasons:
            k = _norm_key((r or {}).get("key") or "")
            st = state_map.get((int(cid), k)) if cid and k else None

            status = (st or {}).get("status") or "open"
            snooze_until = (st or {}).get("snooze_until")
            note = (st or {}).get("note")

            # snooze vencido -> tratar como open
            if status == "snoozed" and snooze_until and snooze_until <= now:
                status = "open"

            # esconder si no include_hidden
            if not include_hidden and status in ("ignored", "snoozed"):
                continue

            rr = dict(r)
            rr["state"] = status
            rr["status"] = status
            rr["note"] = note
            rr["snooze_until"] = snooze_until
            new_reasons.append(rr)

        # si no quedan reasons, no mostramos la alerta
        if not new_reasons:
            continue

        aa = dict(a)
        aa["reasons"] = new_reasons
        aa["keys"] = [rr.get("key") for rr in new_reasons if rr.get("key")]
        out.append(aa)

    return out