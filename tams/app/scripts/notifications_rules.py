from app.models import Assignment, Device, AssetType
from sqlalchemy.orm import aliased
from sqlalchemy import func,or_
import app.models as models

from datetime import date, datetime

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


def course_is_usb_only(db, course_id: int) -> bool:
    Parent = aliased(models.AssetType)

    base = (
        db.query(models.CourseAssetRequirement.id)
        .join(models.AssetType, models.CourseAssetRequirement.asset_type_id == models.AssetType.id)
        .outerjoin(Parent, models.AssetType.parent_id == Parent.id)
        .filter(
            models.CourseAssetRequirement.course_id == course_id,
            models.CourseAssetRequirement.active.is_(True),
            models.CourseAssetRequirement.quantity > 0,
            models.AssetType.active.is_(True),
        )
    )

    usb_count = base.filter(
        or_(
            models.AssetType.code == "USB",
            Parent.code == "USB",
        )
    ).count()

    computer_count = base.filter(
        or_(
            models.AssetType.code == "COMPUTER",
            Parent.code == "COMPUTER",
        )
    ).count()

    return usb_count > 0 and computer_count == 0


def build_changes(before: dict, after: dict, allow_fields=None):
    allow = set(allow_fields) if allow_fields else None
    changes = []

    for k in sorted(set(before.keys()) | set(after.keys())):
        if allow and k not in allow:
            continue
        if before.get(k) != after.get(k):
            changes.append((k, before.get(k), after.get(k)))

    return changes

def _pretty_value(v):
    if v is None:
        return "—"

    # Si ya viene como date/datetime
    if isinstance(v, date) and not isinstance(v, datetime):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y %H:%M")

    # Si viene como string ISO (lo típico en tu before_data/after_data)
    if isinstance(v, str):
        s = v.strip()

        # YYYY-MM-DD
        try:
            d = datetime.strptime(s, "%Y-%m-%d").date()
            return d.strftime("%d/%m/%Y")
        except ValueError:
            pass

        # YYYY-MM-DDTHH:MM:SS (por si alguna vez te llega así)
        try:
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            return dt.strftime("%d/%m/%Y %H:%M")
        except ValueError:
            pass

        # YYYY-MM-DD HH:MM:SS (por si alguna vez te llega así)
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%d/%m/%Y %H:%M")
        except ValueError:
            pass

        # fallback: tal cual, pero SIN comillas ridículas
        return s

    # fallback genérico
    return str(v)


def format_changes(changes, max_lines=12):
    if not changes:
        return "No relevant changes."

    lines = []
    for (k, b, a) in changes[:max_lines]:
        lines.append(f"- {k}: {_pretty_value(b)} -> {_pretty_value(a)}")

    if len(changes) > max_lines:
        lines.append(f"... (+{len(changes) - max_lines} more)")

    return "\n".join(lines)
