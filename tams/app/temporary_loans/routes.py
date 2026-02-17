from datetime import datetime, timezone
from flask import request, jsonify
from flask_login import login_required, current_user

from app.db import SessionLocal
from app.models import TemporaryCardLoan
from app.temporary_loans import bp
from app.temporary_loans.service import (
    create_temporary_loan,
    mark_returned,
    mark_lost,
    refresh_overdues,
    LoanError,
)


def _parse_due_at(value: str):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@bp.route("/create", methods=["POST"])
@login_required
def create():
    db = SessionLocal()
    try:
        data = request.json or request.form

        due_at = _parse_due_at(data["due_at"])

        loan = create_temporary_loan(
            db,
            course_id=int(data["course_id"]),
            borrower_type=data["borrower_type"],
            borrower_name=data.get("borrower_name"),
            borrower_ref=data.get("borrower_ref"),
            card_scope=data["card_scope"],
            temp_card_device_id=int(data["temp_card_device_id"]),
            original_card_device_id=(
                int(data["original_card_device_id"])
                if data.get("original_card_device_id")
                else None
            ),
            due_at=due_at,
            reason=data.get("reason"),
            notes=data.get("notes"),
            created_by_user_id=current_user.id,
        )

        db.commit()

        return jsonify({"ok": True, "loan_id": loan.id}), 201

    except LoanError as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 409

    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400

    finally:
        db.close()


@bp.route("/<int:loan_id>/return", methods=["POST"])
@login_required
def return_loan(loan_id):
    db = SessionLocal()
    try:
        loan = mark_returned(db, loan_id=loan_id)
        db.commit()
        return jsonify({"ok": True, "loan_id": loan.id})

    except LoanError as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 409

    finally:
        db.close()


@bp.route("/<int:loan_id>/lost", methods=["POST"])
@login_required
def lost(loan_id):
    db = SessionLocal()
    try:
        loan = mark_lost(db, loan_id=loan_id)
        db.commit()
        return jsonify({"ok": True, "loan_id": loan.id})

    except LoanError as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 409

    finally:
        db.close()


@bp.route("/course/<int:course_id>", methods=["GET"])
@login_required
def list_by_course(course_id):
    db = SessionLocal()
    try:
        refresh_overdues(db)
        db.commit()

        loans = (
            db.query(TemporaryCardLoan)
            .filter(TemporaryCardLoan.course_id == course_id)
            .order_by(TemporaryCardLoan.start_at.desc())
            .all()
        )

        result = [
            {
                "id": l.id,
                "borrower_type": l.borrower_type,
                "borrower_name": l.borrower_name,
                "borrower_ref": l.borrower_ref,
                "card_scope": l.card_scope,
                "status": l.status,
                "due_at": l.due_at.isoformat(),
                "temp_card_device_id": l.temp_card_device_id,
            }
            for l in loans
        ]

        return jsonify(result)

    finally:
        db.close()
