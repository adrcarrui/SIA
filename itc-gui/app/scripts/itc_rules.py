from sqlalchemy import func
from app.models import CourseAssetRequirement, AssetType, Assignment,Device

ITC_DEPT = "ITC support"
PC_CODE = "LAPTOP"
PENDRIVE_CODE = "PENDRIVE"

def get_itc_requirements_by_course(db, course_ids):
    """
    requirements ITC por curso, usando CourseAssetRequirement + AssetType.

    Devuelve:
      out[course_id] = {
        "itc_total": int,        # total unidades ITC requeridas (para cruz: == 0)
        "pcs": int,              # LAPTOP requeridos
        "pendrives": int,        # PENDRIVE requeridos
        "by_code": {code: qty},  # por si luego quieres más reglas
      }
    """
    if not course_ids:
        return {}

    rows = (
        db.query(
            CourseAssetRequirement.course_id.label("course_id"),
            AssetType.code.label("code"),
            func.sum(CourseAssetRequirement.quantity).label("qty"),
        )
        .join(AssetType, AssetType.id == CourseAssetRequirement.asset_type_id)
        .filter(
            CourseAssetRequirement.course_id.in_(course_ids),
            CourseAssetRequirement.active.is_(True),
            AssetType.active.is_(True),
            AssetType.managed_by_department == ITC_DEPT,
        )
        .group_by(CourseAssetRequirement.course_id, AssetType.code)
        .all()
    )

    out = {
        cid: {"itc_total": 0, "pcs": 0, "pendrives": 0, "by_code": {}}
        for cid in course_ids
    }

    for r in rows:
        cid = r.course_id
        code = (r.code or "").strip().upper()
        qty = int(r.qty or 0)

        out[cid]["itc_total"] += qty
        out[cid]["by_code"][code] = out[cid]["by_code"].get(code, 0) + qty

        if code == PC_CODE:
            out[cid]["pcs"] += qty
        elif code == PENDRIVE_CODE:
            out[cid]["pendrives"] += qty

    return out

def count_assigned_laptops_by_course(db, course_ids):
    if not course_ids:
        return {}

    rows = (
        db.query(
            Assignment.course_id.label("course_id"),
            func.count(Assignment.id).label("cnt"),
        )
        .join(Device, Device.id == Assignment.device_id)
        .join(AssetType, AssetType.id == Device.asset_type_id)
        .filter(
            Assignment.course_id.in_(course_ids),
            Assignment.released_at.is_(None),
            Assignment.status == "active",
            AssetType.code == "LAPTOP",
        )
        .group_by(Assignment.course_id)
        .all()
    )

    out = {cid: 0 for cid in course_ids}
    for r in rows:
        out[r.course_id] = int(r.cnt or 0)
    return out