# app/utils.py (por ejemplo)
from datetime import datetime
from flask_login import current_user
from app import db
import app.models as models


def log_movement(*, entity: str, entity_id: int, action: str, details: str | None = None):
    user_id = None
    try:
        if current_user.is_authenticated:
            user_id = current_user.id
    except Exception:
        pass

    mov = models.Movement(
        user_id=user_id,
        entity=entity,
        entity_id=entity_id,
        action=action,
        created_at=datetime.utcnow(),
        details=details,
    )
    db.session.add(mov)
    # NO hacemos commit aquí, se hace en la vista
