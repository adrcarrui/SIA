# app/scripts/auto_lost_cards.py

from datetime import date, datetime, timedelta
from sqlalchemy.orm import aliased

from app.db import SessionLocal
from app.models import Assignment, Course, Device, AssetType
from app.scripts.movements import log_movement


AUTO_LOST_DAYS = 14


def run(days: int = AUTO_LOST_DAYS) -> dict:
    db = SessionLocal()
    try:
        today = date.today()
        cutoff = today - timedelta(days=days)

        ParentAT = aliased(AssetType)

        # SOLO:
        # - assignments vivos (released_at NULL)
        # - status 'active' (en BD)
        # - cursos terminados hace > days
        # - assets visibles en calendario
        # - CARD o hijos de CARD (AssetType.code == CARD o parent.code == CARD)
        rows = (
            db.query(Assignment, Course, Device, AssetType, ParentAT)
              .join(Course, Assignment.course_id == Course.id)
              .join(Device, Assignment.device_id == Device.id)
              .join(AssetType, Device.asset_type_id == AssetType.id)
              .outerjoin(ParentAT, AssetType.parent_id == ParentAT.id)
              .filter(
                  Assignment.released_at.is_(None),
                  Assignment.status == "active",
                  Course.end_date.isnot(None),
                  Course.end_date < cutoff,
                  AssetType.show_in_calendar.is_(True),
                  ((AssetType.code == "CARD") | (ParentAT.code == "CARD")),
              )
              .all()
        )

        now = datetime.utcnow()
        processed = 0

        for a, c, d, at, pat in rows:
            before = {
                "assignment": {
                    "id": a.id,
                    "device_id": a.device_id,
                    "course_id": a.course_id,
                    "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
                    "status": a.status,
                    "created_by": a.created_by,
                },
                "device": {
                    "id": d.id,
                    "uid": d.uid,
                    "name": d.name,
                    "status": d.status,
                    "asset_type_id": d.asset_type_id,
                    "asset_type_code": at.code if at else None,
                    "asset_parent_code": pat.code if pat else None,
                },
                "course": {
                    "id": c.id,
                    "course": c.course,
                    "start_date": c.start_date.isoformat() if c.start_date else None,
                    "end_date": c.end_date.isoformat() if c.end_date else None,
                },
                "policy": {"auto_lost_days": days},
            }

            # 1) Marcar device como LOST (si no lo está ya)
            d.status = "lost"

            after = {
                "device": {"id": d.id, "status": d.status},
                "course": {"id": c.id, "course": c.course},
                "policy": {"auto_lost_days": days},
            }

            # 2) Log (course asociado dentro del movement)
            log_movement(
                db,
                user_id=None,
                entity_type="assignment",
                entity_id=a.id,
                action="auto_lost",
                before_data=before,
                after_data=after,
                description=(
                    f"AUTO: marked device LOST and deleted assignment "
                    f"(assignment_id={a.id}, device_id={d.id}, course_id={c.id}, course={c.course})"
                ),
                user_agent="system/auto_lost_cards_job",
                success=True,
            )

            # 3) Borrar assignment (tabla viva)
            db.delete(a)
            processed += 1

        db.commit()
        return {"ok": True, "processed": processed}

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
