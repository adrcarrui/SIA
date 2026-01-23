from flask import render_template, session, request
from flask_login import login_required, current_user
from . import bp
from app.db import SessionLocal
from app.models import (
    User, Device, Course, Assignment, Movements, AssetType
)
from sqlalchemy import func, case
import app.models as models
from app.scripts.alerts_service import get_alerts_for_user

# ---------------------------------------------------------------------
# NOTIFICATIONS / ALERTS (SIN CAMBIOS FUNCIONALES)
# ---------------------------------------------------------------------

def _notif_scope_for_user():
    role = (getattr(current_user, "role", "") or "").strip().lower()
    dept = (getattr(current_user, "department", "") or "").strip()

    if "admin" in role:
        return None
    if dept.lower() == "itc support":
        return "ITC support"
    if dept.upper() == "TCO":
        return "TCO"
    return "__NONE__"


@bp.app_context_processor
def inject_notifications_badge():
    if not current_user.is_authenticated:
        return dict(notifications_unread_count=0)

    db = SessionLocal()
    try:
        scope = _notif_scope_for_user()
        if scope == "__NONE__":
            return dict(notifications_unread_count=0)

        q = db.query(func.count(models.Notification.id)).filter(
            models.Notification.active.is_(True),
            models.Notification.read_at.is_(None),
            models.Notification.status.notin_(["done", "dismissed"]),
        )

        if scope is not None:
            q = q.filter(models.Notification.department_target == scope)

        return dict(notifications_unread_count=q.scalar() or 0)
    finally:
        db.close()


@bp.app_context_processor
def inject_alerts_summary():
    if not current_user.is_authenticated:
        return dict(alerts_summary={"notice": 0, "warning": 0, "critical": 0})

    db = SessionLocal()
    try:
        alerts = get_alerts_for_user(db, current_user)
        return dict(alerts_summary={
            "notice":   sum(1 for a in alerts if a.get("severity") == "notice"),
            "warning":  sum(1 for a in alerts if a.get("severity") == "warning"),
            "critical": sum(1 for a in alerts if a.get("severity") == "critical"),
        })
    finally:
        db.close()

# ---------------------------------------------------------------------
# HELPERS ASSET TYPE
# ---------------------------------------------------------------------

def _card_parent_and_children_ids(db) -> list[int]:
    parent = (
        db.query(AssetType)
        .filter(func.upper(AssetType.code) == "CARD", AssetType.active.is_(True))
        .first()
    )
    if not parent:
        return []

    ids = [parent.id]
    rows = (
        db.query(AssetType.id)
        .filter(AssetType.active.is_(True), AssetType.parent_id == parent.id)
        .all()
    )
    ids.extend([rid for (rid,) in rows])
    return ids


def itc_non_card_children_ids(db) -> list[int]:
    card_tree = set(_card_parent_and_children_ids(db))

    q = (
        db.query(AssetType.id)
        .filter(
            AssetType.active.is_(True),
            AssetType.parent_id.isnot(None)
        )
    )

    if card_tree:
        q = q.filter(~AssetType.id.in_(card_tree))

    return [rid for (rid,) in q.all()]

# ---------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------

@bp.route("/")
@login_required
def index():
    db = SessionLocal()
    try:
        # -------------------------------------------------
        # USUARIO ACTUAL
        # -------------------------------------------------
        role = (getattr(current_user, "role", "") or "").strip().lower()
        dept = (getattr(current_user, "department", "") or "").strip().lower()

        is_admin = ("admin" in role)
        is_tco   = (dept == "tco")
        is_itc   = (dept == "itc support")

        # -------------------------------------------------
        # HELPERS ASSET TYPE
        # -------------------------------------------------
        def _card_parent_and_children_ids(db) -> list[int]:
            parent = (
                db.query(AssetType)
                .filter(func.upper(AssetType.code) == "CARD", AssetType.active.is_(True))
                .first()
            )
            if not parent:
                return []

            ids = [parent.id]
            rows = (
                db.query(AssetType.id)
                .filter(
                    AssetType.active.is_(True),
                    AssetType.parent_id == parent.id
                )
                .all()
            )
            ids.extend([rid for (rid,) in rows])
            return ids

        def _itc_non_card_children_ids(db) -> list[int]:
            card_tree = set(_card_parent_and_children_ids(db))

            q = (
                db.query(AssetType.id)
                .filter(
                    AssetType.active.is_(True),
                    AssetType.parent_id.isnot(None)  # solo hijos
                )
            )

            if card_tree:
                q = q.filter(~AssetType.id.in_(card_tree))

            return [rid for (rid,) in q.all()]

        # -------------------------------------------------
        # ASSET TYPES VISIBLES SEGÚN DEPARTAMENTO
        # -------------------------------------------------
        asset_type_filter_ids = None  # None = sin filtro (admin)

        if is_tco:
            ids = _card_parent_and_children_ids(db)
            asset_type_filter_ids = ids[1:] if len(ids) > 1 else []  # SOLO hijos de CARD
        elif is_itc:
            asset_type_filter_ids = _itc_non_card_children_ids(db)   # hijos no-CARD
        elif not is_admin:
            asset_type_filter_ids = []  # otros dept: nada

        # -------------------------------------------------
        # DEBUG (TEMPORAL)
        # -------------------------------------------------
        print("---- DASHBOARD DEBUG ----")
        print("role:", role, "dept:", dept)
        print("is_admin:", is_admin, "is_tco:", is_tco, "is_itc:", is_itc)
        print("asset_type_filter_ids:", None if asset_type_filter_ids is None else len(asset_type_filter_ids))
        print("sample ids:", (asset_type_filter_ids or [])[:10])

        children_active = db.query(func.count(AssetType.id)).filter(
            AssetType.active.is_(True),
            AssetType.parent_id.isnot(None)
        ).scalar() or 0
        print("ACTIVE CHILD ASSET TYPES:", children_active)

        devices_total = db.query(func.count(Device.id)).scalar() or 0
        devices_with_type = db.query(func.count(Device.id)).filter(Device.asset_type_id.isnot(None)).scalar() or 0
        print("DEVICES total:", devices_total, "with asset_type_id:", devices_with_type)

        if asset_type_filter_ids is None:
            devices_in_scope = devices_total
        else:
            devices_in_scope = db.query(func.count(Device.id)).filter(
                Device.asset_type_id.in_(asset_type_filter_ids)
            ).scalar() or 0
        print("DEVICES IN SCOPE:", devices_in_scope)
        print("-------------------------")

        # -------------------------------------------------
        # MÉTRICAS RÁPIDAS
        # -------------------------------------------------
        total_users = db.query(func.count(User.id)).scalar() or 0
        total_courses = db.query(func.count(Course.id)).scalar() or 0
        total_assignments = db.query(func.count(Assignment.id)).scalar() or 0
        total_movements = db.query(func.count(Movements.id)).scalar() or 0

        q_total_devices = db.query(func.count(Device.id))
        if asset_type_filter_ids is not None:
            q_total_devices = q_total_devices.filter(Device.asset_type_id.in_(asset_type_filter_ids))
        total_devices = q_total_devices.scalar() or 0

        # -------------------------------------------------
        # ACTIVE ASSIGNMENTS (RESPETA FILTRO)
        # -------------------------------------------------
        q_active = (
            db.query(func.count(Assignment.id))
            .join(Device, Device.id == Assignment.device_id)
            .filter(Assignment.released_at.is_(None))
        )
        if asset_type_filter_ids is not None:
            q_active = q_active.filter(Device.asset_type_id.in_(asset_type_filter_ids))
        total_active_cards = q_active.scalar() or 0

        # -------------------------------------------------
        # DEVICES POR ASSET TYPE HIJO (OUTER JOIN)
        # -------------------------------------------------
        q = (
            db.query(
                AssetType.id.label("id"),
                AssetType.name.label("name"),
                AssetType.code.label("code"),
                func.count(Device.id).label("total"),
                func.sum(case((Device.status == "assigned", 1), else_=0)).label("assigned"),
            )
            .outerjoin(Device, Device.asset_type_id == AssetType.id)
            .filter(
                AssetType.active.is_(True),
                AssetType.parent_id.isnot(None)  # SOLO HIJOS
            )
        )

        if asset_type_filter_ids is not None:
            q = q.filter(AssetType.id.in_(asset_type_filter_ids))

        rows = (
            q.group_by(AssetType.id, AssetType.name, AssetType.code)
            .order_by(AssetType.name)
            .all()
        )

        print("ROWS returned for table:", len(rows))

        asset_children_stats = []
        for r in rows:
            total = r.total or 0
            assigned = r.assigned or 0
            ratio = (assigned / total * 100) if total else 0

            asset_children_stats.append({
                "id": r.id,
                "name": r.name or "Unknown",
                "code": r.code or "",
                "total": total,
                "assigned": assigned,
                "ratio": ratio,
            })

        # -------------------------------------------------
        # ALERTAS
        # -------------------------------------------------
        alerts = get_alerts_for_user(db, current_user)
        alerts_summary = {
            "notice":   sum(1 for a in alerts if a.get("severity") == "notice"),
            "warning":  sum(1 for a in alerts if a.get("severity") == "warning"),
            "critical": sum(1 for a in alerts if a.get("severity") == "critical"),
        }

        # -------------------------------------------------
        # RENDER
        # -------------------------------------------------
        return render_template(
            "index.html",
            total_users=total_users,
            total_devices=total_devices,
            total_courses=total_courses,
            total_assignments=total_assignments,
            total_movements=total_movements,
            total_active_cards=total_active_cards,
            asset_children_stats=asset_children_stats,
            alerts=alerts,
            alerts_summary=alerts_summary,
        )

    finally:
        db.close()


# ---------------------------------------------------------------------
# OTROS ENDPOINTS (SIN CAMBIOS)
# ---------------------------------------------------------------------

@bp.route("/test-calendar")
@login_required
def test_calendar():
    return render_template("test_calendar.html")


@bp.route("/alerts")
@login_required
def alerts_index():
    db = SessionLocal()
    try:
        alerts = get_alerts_for_user(db, current_user)
        return render_template(
            "alerts_index.html",
            alerts=alerts,
            alerts_summary={
                "notice":   sum(1 for a in alerts if a.get("severity") == "notice"),
                "warning":  sum(1 for a in alerts if a.get("severity") == "warning"),
                "critical": sum(1 for a in alerts if a.get("severity") == "critical"),
            },
        )
    finally:
        db.close()


@bp.app_context_processor
def inject_notifications_summary():
    db = SessionLocal()
    try:
        if not current_user.is_authenticated:
            return dict(notifications_summary={"unread": 0})

        q = (
            db.query(models.Notification.id)
            .filter(
                models.Notification.active.is_(True),
                models.Notification.read_at.is_(None),
                models.Notification.status == "open"
            )
        )

        scope = _notif_scope_for_user()
        if scope == "__NONE__":
            return dict(notifications_summary={"unread": 0})
        if scope is not None:
            q = q.filter(models.Notification.department_target == scope)

        return dict(notifications_summary={"unread": q.count()})
    finally:
        db.close()
