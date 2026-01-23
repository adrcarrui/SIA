from datetime import datetime
from flask import request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db as sqla_db
from app.alerts import bp  # el blueprint
from app.scripts.alert_state_service import set_alert_state, clear_alert_state


def _json_error(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


def _scope_for_user(user) -> str:
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


def _get_payload():
    data = request.get_json(silent=True) or {}
    # scope YA NO se lee del payload (cliente manipulable)
    course_id = data.get("course_id")
    alert_key = (data.get("alert_key") or "").strip()
    note = data.get("note")
    until = (data.get("until") or "").strip()
    return data, course_id, alert_key, note, until


def _parse_until(until_str: str | None):
    if not until_str:
        return None
    # Espera ISO 8601 con timezone, ej: 2026-01-20T09:00:00+01:00
    try:
        dt = datetime.fromisoformat(until_str)
        # aseguramos tz-aware
        if dt.tzinfo is None:
            return None
        return dt
    except Exception:
        return None


def _updated_by():
    return getattr(current_user, "email", None) or getattr(current_user, "username", None)


@bp.post("/api/alerts/ack")
@login_required
def api_alert_ack():
    data, course_id, alert_key, note, _until = _get_payload()
    scope = _scope_for_user(current_user)

    if course_id is None or not alert_key:
        return _json_error("Missing course_id/alert_key")

    try:
        set_alert_state(
            sqla_db.session,
            scope=scope,
            course_id=int(course_id),
            alert_key=alert_key,
            status="acked",
            snooze_until=None,
            note=note,
            updated_by=_updated_by(),
        )
        sqla_db.session.commit()
        return jsonify({"ok": True, "scope": scope})
    except SQLAlchemyError:
        current_app.logger.exception("api_alert_ack failed")
        try:
            sqla_db.session.rollback()
        except Exception:
            pass
        return _json_error("DB error", 500)


@bp.post("/api/alerts/ignore")
@login_required
def api_alert_ignore():
    data, course_id, alert_key, note, _until = _get_payload()
    scope = _scope_for_user(current_user)

    if course_id is None or not alert_key:
        return _json_error("Missing course_id/alert_key")

    try:
        set_alert_state(
            sqla_db.session,
            scope=scope,
            course_id=int(course_id),
            alert_key=alert_key,
            status="ignored",
            snooze_until=None,
            note=note,
            updated_by=_updated_by(),
        )
        sqla_db.session.commit()
        return jsonify({"ok": True, "scope": scope})
    except SQLAlchemyError:
        current_app.logger.exception("api_alert_ignore failed")
        try:
            sqla_db.session.rollback()
        except Exception:
            pass
        return _json_error("DB error", 500)


@bp.post("/api/alerts/snooze")
@login_required
def api_alert_snooze():
    data, course_id, alert_key, note, until_str = _get_payload()
    scope = _scope_for_user(current_user)

    if course_id is None or not alert_key:
        return _json_error("Missing course_id/alert_key")

    until_dt = _parse_until(until_str)
    if not until_dt:
        return _json_error(
            "Invalid until datetime (ISO8601 with timezone required). "
            "Example: 2026-01-20T09:00:00+01:00"
        )

    try:
        set_alert_state(
            sqla_db.session,
            scope=scope,
            course_id=int(course_id),
            alert_key=alert_key,
            status="snoozed",
            snooze_until=until_dt,
            note=note,
            updated_by=_updated_by(),
        )
        sqla_db.session.commit()
        return jsonify({"ok": True, "scope": scope})
    except SQLAlchemyError:
        current_app.logger.exception("api_alert_snooze failed")
        try:
            sqla_db.session.rollback()
        except Exception:
            pass
        return _json_error("DB error", 500)


@bp.post("/api/alerts/open")
@login_required
def api_alert_open():
    """
    Resetea a open (sirve como unignore/unsnooze/unack).
    """
    data, course_id, alert_key, note, _until = _get_payload()
    scope = _scope_for_user(current_user)

    if course_id is None or not alert_key:
        return _json_error("Missing course_id/alert_key")

    try:
        clear_alert_state(
            sqla_db.session,
            scope=scope,
            course_id=int(course_id),
            alert_key=alert_key,
            updated_by=_updated_by(),
        )
        sqla_db.session.commit()
        return jsonify({"ok": True, "scope": scope})
    except SQLAlchemyError:
        current_app.logger.exception("api_alert_open failed")
        try:
            sqla_db.session.rollback()
        except Exception:
            pass
        return _json_error("DB error", 500)
