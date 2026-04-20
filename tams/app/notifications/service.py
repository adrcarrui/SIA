from app.models import Notification
from sqlalchemy import and_

PICKUP_NOTIFICATION_TYPES = (
    "pickup_needed",
    "pickup_needed_devices",
    "pickup_needed_forms",
)


def get_itc_pickup_notifications(db, user):
    """
    Devuelve las notificaciones ITC pick up visibles para el usuario.
    """
    role = (getattr(user, "role", "") or "").lower()
    dept = (getattr(user, "department", "") or "").strip()

    if "admin" in role:
        q = db.query(Notification)
    elif dept == "ITC support":
        q = db.query(Notification).filter(
            Notification.department_target == "ITC support"
        )
    else:
        return []

    return (
        q.filter(
            Notification.active.is_(True),
            Notification.status == "open",
            Notification.type.in_(PICKUP_NOTIFICATION_TYPES),
        )
        .order_by(Notification.created_at.desc())
        .all()
    )
