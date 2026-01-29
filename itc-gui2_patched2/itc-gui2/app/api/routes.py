from . import bp
from flask import jsonify
from flask_login import login_required
from app.db import SessionLocal
from app.models import AlertState, Notification


@bp.route("/counters",methods=["GET"])
@login_required
def counters():
    db = SessionLocal()
    try:
        return jsonify({
            "alerts": db.query(AlertState).filter(AlertState.status == "open").count(),
            "notifications": db.query(Notification).filter(Notification.status == "open").count()
        })
    finally:
        db.close()
