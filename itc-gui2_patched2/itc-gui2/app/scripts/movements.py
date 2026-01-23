# app/scripts/movements.py

from typing import Optional, Any
from sqlalchemy.orm import Session
from datetime import datetime

import app.models as models


def log_movement(
    db: Session,
    *,
    user_id: Optional[int],
    entity_type: str,
    entity_id: Optional[int],
    action: str,
    before_data: Optional[dict[str, Any]] = None,
    after_data: Optional[dict[str, Any]] = None,
    description: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: bool = True,
):
    movement = models.Movements(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        before_data=before_data,
        after_data=after_data,
        description=description or "",
        success=success,
        user_agent=user_agent or "",
        created_at=datetime.utcnow(),
    )

    db.add(movement)
    # OJO: aquí NO hace falta commit si lo vas a hacer en la vista
    # lo dejo sin commit y sin refresh
    return movement
