from app.models import Assignment, Device, AssetType
from sqlalchemy.orm import aliased
from sqlalchemy import func,or_
import app.models as models

ITC_ROOT_CODES = ["COMPUTER", "USB"]

def format_requirements_map(db, req_map):
    """
    Convierte {asset_type_id: qty} en texto legible.
    """
    if not req_map:
        return "-"

    rows = (
        db.query(AssetType.id, AssetType.name)
        .filter(AssetType.id.in_(req_map.keys()))
        .all()
    )
    name_by_id = {r.id: r.name for r in rows}

    lines = []
    for at_id, qty in req_map.items():
        name = name_by_id.get(at_id, f"AssetType #{at_id}")
        lines.append(f"- {name}: {qty}")

    return "\n".join(lines)

def course_has_itc_assets(db, course_id: int) -> bool:
    Parent = aliased(models.AssetType)

    q = (
        db.query(func.count(models.CourseAssetRequirement.id))
        .join(models.AssetType, models.CourseAssetRequirement.asset_type_id == models.AssetType.id)
        .outerjoin(Parent, models.AssetType.parent_id == Parent.id)
        .filter(
            models.CourseAssetRequirement.course_id == course_id,
            models.CourseAssetRequirement.active.is_(True),
            models.CourseAssetRequirement.quantity > 0,
            models.AssetType.active.is_(True),
            or_(
                models.AssetType.code.in_(ITC_ROOT_CODES),   # root directo (USB típico)
                Parent.code.in_(ITC_ROOT_CODES),             # hijo de COMPUTER/USB
            )
        )
    )

    return (q.scalar() or 0) > 0


def build_changes(before: dict, after: dict, allow_fields=None):
    allow = set(allow_fields) if allow_fields else None
    changes = []

    for k in sorted(set(before.keys()) | set(after.keys())):
        if allow and k not in allow:
            continue
        if before.get(k) != after.get(k):
            changes.append((k, before.get(k), after.get(k)))

    return changes


def format_changes(changes, max_lines=12):
    if not changes:
        return "No relevant changes."
    lines = [f"- {k}: {b!r} -> {a!r}" for (k, b, a) in changes[:max_lines]]
    if len(changes) > max_lines:
        lines.append(f"... (+{len(changes) - max_lines} more)")
    return "\n".join(lines)