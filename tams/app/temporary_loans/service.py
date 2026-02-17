from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import TemporaryCardLoan, Device, Course


ACTIVE_STATUSES = ("active", "overdue")


class LoanError(Exception):
    pass


class NotFound(LoanError):
    pass


class Conflict(LoanError):
    pass


class InvalidState(LoanError):
    pass


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def refresh_overdues(db: Session) -> int:
    now = _now_utc()
    q = (
        db.query(TemporaryCardLoan)
        .filter(TemporaryCardLoan.status == "active")
        .filter(TemporaryCardLoan.due_at < now)
    )
    n = 0
    for loan in q.all():
        loan.status = "overdue"
        n += 1
    return n


def create_temporary_loan(
    db: Session,
    *,
    course_id: int,
    borrower_type: str,
    card_scope: str,
    temp_card_device_id: int,
    due_at: datetime,
    borrower_name: Optional[str] = None,
    borrower_ref: Optional[str] = None,
    original_card_device_id: Optional[int] = None,
    reason: Optional[str] = None,
    notes: Optional[str] = None,
    created_by_user_id: Optional[int] = None,
) -> TemporaryCardLoan:
    borrower_type = (borrower_type or "").strip().lower()
    card_scope = (card_scope or "").strip().lower()
    borrower_name = (borrower_name or "").strip() or None
    borrower_ref = (borrower_ref or "").strip() or None
    reason = (reason or "").strip() or None

    if not isinstance(course_id, int) or course_id <= 0:
        raise InvalidState("course_id must be a positive integer")

    if borrower_type not in ("student", "instructor"):
        raise InvalidState("borrower_type must be 'student' or 'instructor'")

    if card_scope not in ("vending", "canteen", "instructor", "other"):
        raise InvalidState("card_scope must be vending/canteen/instructor/other")

    if not isinstance(due_at, datetime):
        raise InvalidState("due_at must be a datetime")

    if due_at.tzinfo is None:
        raise InvalidState("due_at must be timezone-aware (TIMESTAMPTZ)")

    refresh_overdues(db)

    course = db.query(Course).get(course_id)
    if not course:
        raise NotFound("Course not found")

    temp_card = db.query(Device).get(temp_card_device_id)
    if not temp_card:
        raise NotFound("Temp card device not found")

    if original_card_device_id is not None:
        orig = db.query(Device).get(original_card_device_id)
        if not orig:
            raise NotFound("Original card device not found")

    loan = TemporaryCardLoan(
        course_id=course_id,
        borrower_type=borrower_type,
        borrower_name=borrower_name,
        borrower_ref=borrower_ref,
        card_scope=card_scope,
        temp_card_device_id=temp_card_device_id,
        original_card_device_id=original_card_device_id,
        start_at=_now_utc(),
        due_at=due_at,
        status="active",
        reason=reason,
        notes=notes,
        created_by_user_id=created_by_user_id,
    )

    db.add(loan)

    if hasattr(temp_card, "status"):
        temp_card.status = "assigned"

    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise Conflict("Duplicate active loan (card already loaned or borrower+scope already active)") from e

    return loan


def mark_returned(
    db: Session,
    *,
    loan_id: int,
    returned_at: Optional[datetime] = None,
) -> TemporaryCardLoan:
    refresh_overdues(db)

    loan = db.query(TemporaryCardLoan).get(loan_id)
    if not loan:
        raise NotFound("Loan not found")

    if loan.status not in ACTIVE_STATUSES and loan.status != "lost":
        raise InvalidState(f"Cannot return a loan in status={loan.status}")

    loan.status = "returned"
    loan.returned_at = returned_at or _now_utc()

    if loan.temp_card and hasattr(loan.temp_card, "status"):
        loan.temp_card.status = "available"

    return loan


def mark_lost(
    db: Session,
    *,
    loan_id: int,
    lost_at: Optional[datetime] = None,
    device_mark_lost: bool = True,
) -> TemporaryCardLoan:
    refresh_overdues(db)

    loan = db.query(TemporaryCardLoan).get(loan_id)
    if not loan:
        raise NotFound("Loan not found")

    if loan.status not in ACTIVE_STATUSES:
        raise InvalidState(f"Cannot mark lost a loan in status={loan.status}")

    loan.status = "lost"
    loan.lost_at = lost_at or _now_utc()

    if device_mark_lost and loan.temp_card and hasattr(loan.temp_card, "status"):
        loan.temp_card.status = "lost"

    return loan


def replace_lost_with_new(
    db: Session,
    *,
    lost_loan_id: int,
    new_temp_card_device_id: int,
    new_due_at: datetime,
    created_by_user_id: Optional[int] = None,
) -> TemporaryCardLoan:
    lost_loan = db.query(TemporaryCardLoan).get(lost_loan_id)
    if not lost_loan:
        raise NotFound("Lost loan not found")

    if lost_loan.status in ACTIVE_STATUSES:
        mark_lost(db, loan_id=lost_loan_id)

    new_loan = create_temporary_loan(
        db,
        course_id=lost_loan.course_id,
        borrower_type=lost_loan.borrower_type,
        borrower_name=lost_loan.borrower_name,
        borrower_ref=lost_loan.borrower_ref,
        card_scope=lost_loan.card_scope,
        temp_card_device_id=new_temp_card_device_id,
        original_card_device_id=lost_loan.original_card_device_id,
        due_at=new_due_at,
        reason=lost_loan.reason,
        notes=lost_loan.notes,
        created_by_user_id=created_by_user_id,
    )

    lost_loan.replaced_by_loan_id = new_loan.id
    return new_loan
