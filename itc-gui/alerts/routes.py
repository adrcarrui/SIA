from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models import AlertState

alerts_api = Blueprint("alerts_api", __name__, url_prefix="/api/alerts")

def _now():
    return datetime.now(timezone.utc)

def _normalize_scope(scope: str) -> str:
    scope = (scope or "").strip().lower()
    if scope in ("tco", "itc", "admin"):
        return scope
    return ""

def _user_scope():
    role = (getattr(current_user, "role", "") or "").strip().lower()
    dept = (getattr(current_user, "department", "") or "").strip().lower()
    if "admin" in role:
        return "admin"
    if dept == "tco" or dept.startswith("tco") or "tco" in dept:
        return "tco"
    if dept == "itc support" or dept.startswith("itc") or "itc" in dept:
        return "itc"
    return "other"

def _forbidden():
    return jsonify({"ok": False, "error": "forbidden"}), 403

def _bad(msg):
    return jsonify({"ok": False, "error": msg}), 400

def _get_or_create(scope: str, course_id: int, alert_key: str) -> AlertState:
    row = AlertState.query.filter_by(scope=scope, course_id=course_id, alert_key=alert_key).first()
    if not row:
        row = AlertState(scope=scope, course_id=course_id, alert_key=alert_key, status="open")
        db.session.add(row)
    return row


@alerts_api.post("/ack")
@login_required
def api_alert_ack():
    data = request.get_json(silent=True) or {}

    scope = _normalize_scope(data.get("scope"))
    course_id = int(data.get("course_id") or 0)
    alert_key = (data.get("alert_key") or "").strip()
    note = (data.get("note") or "").strip() or None

    if not scope or not course_id or not alert_key:
        return _bad("missing scope/course_id/alert_key")

    # Seguridad simple: el usuario solo puede tocar su propio scope
    # (admin puede tocar todo)
    us = _user_scope()
    if us != "admin" and scope != us:
        return _forbidden()

    row = _get_or_create(scope, course_id, alert_key)
    row.status = "ack"
    row.note = note
    row.snooze_until = None
    row.updated_by_user_id = getattr(current_user, "id", None)
    row.updated_at = _now()
    row.last_seen_at = _now()

    db.session.commit()
    return jsonify({"ok": True})


@alerts_api.post("/snooze")
@login_required
def api_alert_snooze():
    data = request.get_json(silent=True) or {}

    scope = _normalize_scope(data.get("scope"))
    course_id = int(data.get("course_id") or 0)
    alert_key = (data.get("alert_key") or "").strip()
    minutes = int(data.get("minutes") or 0)

    if not scope or not course_id or not alert_key:
        return _bad("missing scope/course_id/alert_key")
    if minutes <= 0:
        return _bad("minutes must be > 0")

    us = _user_scope()
    if us != "admin" and scope != us:
        return _forbidden()

    until = _now() + timedelta(minutes=minutes)

    row = _get_or_create(scope, course_id, alert_key)
    row.status = "snoozed"
    row.snooze_until = until
    row.updated_by_user_id = getattr(current_user, "id", None)
    row.updated_at = _now()
    row.last_seen_at = _now()

    db.session.commit()
    return jsonify({"ok": True, "snooze_until": until.isoformat()})


@alerts_api.post("/ignore")
@login_required
def api_alert_ignore():
    data = request.get_json(silent=True) or {}

    scope = _normalize_scope(data.get("scope"))
    course_id = int(data.get("course_id") or 0)
    alert_key = (data.get("alert_key") or "").strip()

    if not scope or not course_id or not alert_key:
        return _bad("missing scope/course_id/alert_key")

    us = _user_scope()
    if us != "admin" and scope != us:
        return _forbidden()

    row = _get_or_create(scope, course_id, alert_key)
    row.status = "ignored"
    row.snooze_until = None
    row.updated_by_user_id = getattr(current_user, "id", None)
    row.updated_at = _now()
    row.last_seen_at = _now()

    db.session.commit()
    return jsonify({"ok": True})
