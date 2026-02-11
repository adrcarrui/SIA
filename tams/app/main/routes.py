from flask import render_template, session, request, redirect, url_for, flash
from flask_login import login_required, current_user
from . import bp
from app.extensions import db
from app.db import SessionLocal
from app.scripts.get_overdue_assignments import (
    get_overdue_course_alerts,
    get_cards_vs_trainees_alerts,
)
from app.models import User, Device, Course, Assignment, Movements, Notification
from sqlalchemy import func, case
import app.models as models
from app.scripts.alerts_service import get_alerts_for_user, build_alerts_summary
from app.scripts.alert_filters import reason_counts_for_calendar
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.notifications.service import get_itc_pickup_notifications

def _notif_scope_for_user():
    role = (getattr(current_user, "role", "") or "").strip().lower()
    dept = (getattr(current_user, "department", "") or "").strip()

    # Admin ve todo
    if "admin" in role:
        return None

    # Dept scope
    if dept.lower() == "itc support":
        return "ITC support"
    if dept.upper() == "TCO":
        return "TCO"

    # Si no tiene dept válido: no enseñes nada
    return "__NONE__"


@bp.app_context_processor
def inject_notifications_badge():
    """
    Inyecta notifications_unread_count en TODOS los templates.
    Unread = status NO cerrado (no done/dismissed) y read_at IS NULL.
    """
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

        count = q.scalar() or 0
        return dict(notifications_unread_count=count)
    finally:
        db.close()

def _alerts_scope_for_user():
    dept = (getattr(current_user, "department", "") or "").strip()
    role = (getattr(current_user, "role", "") or "").strip().lower()

    # Admin ve todo
    if "admin" in role:
        return None

    # ITC support ve solo ITC
    if dept.lower() == "itc support":
        return "ITC support"

    # TCO ve solo TCO
    if dept.upper() == "TCO":
        return "TCO"

    # fallback: nada (o todo). Mejor nada para no mezclar departamentos.
    return None


@bp.app_context_processor
def inject_alerts_summary():
    """
    Hace que 'alerts_summary' esté disponible en TODOS los templates,
    para que el badge del sidebar funcione siempre.
    """
    db = SessionLocal()
    try:
        now_utc = datetime.now(timezone.utc)

        alerts = get_alerts_for_user(db, current_user, include_hidden=True) or []

        # Summary para pintar "hoy": SOLO cuenta reasons open (o snooze vencido)
        summary = {"notice": 0, "warning": 0, "critical": 0}

        for a in alerts:
            a_sev = (a.get("severity") or "notice").strip().lower()
            reasons = a.get("reasons") or []

            if reasons:
                for r in reasons:
                    if not reason_counts_for_calendar(r, now_utc):
                        continue
                    sev = (r.get("severity") or a_sev or "notice").strip().lower()
                    if sev not in summary:
                        sev = "notice"
                    summary[sev] += 1
            else:
                # alertas sin reasons: cuentan como 1
                sev = a_sev if a_sev in summary else "notice"
                summary[sev] += 1

        return dict(alerts_summary=summary)
    finally:
        db.close()

@bp.route("/")
@login_required
def index():
    db = SessionLocal()
    try:
        # =====================================================
        # Métricas rápidas
        # =====================================================
        total_users = db.query(func.count(User.id)).scalar() or 0
        total_devices = db.query(func.count(Device.id)).scalar() or 0
        total_courses = db.query(func.count(Course.id)).scalar() or 0
        total_assignments = db.query(func.count(Assignment.id)).scalar() or 0
        total_movements = db.query(func.count(Movements.id)).scalar() or 0

        total_active_cards = (
            db.query(func.count(Assignment.id))
              .filter(Assignment.released_at.is_(None))
              .scalar()
        ) or 0

        # =====================================================
        # Contexto usuario
        # =====================================================
        actor_role = (getattr(current_user, "role", "") or "").strip().lower()
        actor_dept = (getattr(current_user, "department", "") or "").strip().lower()

        is_admin = ("admin" in actor_role)
        is_itc = (actor_dept == "itc support") or actor_role.startswith("itc")
        is_tco = (actor_dept == "tco")

        # =====================================================
        # Devices stats (basados en AssetTypes)
        # =====================================================
        from app.models import AssetType

        # Cargar todos los asset types activos
        all_types = (
            db.query(AssetType)
              .filter(AssetType.active.is_(True))
              .order_by(AssetType.sort_order.asc(), AssetType.code.asc())
              .all()
        )

        by_id = {t.id: t for t in all_types}

        # -----------------------------------------------------
        # Utilidades de jerarquía
        # -----------------------------------------------------
        def descendants_ids(root: AssetType) -> set[int]:
            if not root:
                return set()
            out = set()
            queue = [root]
            while queue:
                cur = queue.pop(0)
                if cur.id in out:
                    continue
                out.add(cur.id)
                for ch in getattr(cur, "children", []) or []:
                    if getattr(ch, "active", True):
                        queue.append(ch)
            return out

        def has_ancestor_code(asset_type_id: int | None, code_upper: str) -> bool:
            if not asset_type_id:
                return False
            seen = set()
            cur = by_id.get(asset_type_id)
            target = code_upper.upper()
            while cur and cur.id not in seen:
                seen.add(cur.id)
                if (cur.code or "").upper() == target:
                    return True
                pid = cur.parent_id
                cur = by_id.get(pid) if pid else None
            return False

        # -----------------------------------------------------
        # Familia CARD
        # -----------------------------------------------------
        card_root = next(
            (t for t in all_types if (t.code or "").upper() == "CARD"),
            None
        )
        card_family_ids = descendants_ids(card_root)

        # =====================================================
        # Tipos visibles según perfil
        # =====================================================
        if is_admin:
            # Admin: SOLO hijos (todos los árboles)
            visible_types = [t for t in all_types if t.parent_id is not None]

        elif is_tco:
            # TCO: SOLO hijos de CARD
            visible_types = [
                t for t in all_types
                if t.parent_id is not None and t.id in card_family_ids
            ]

        elif is_itc:
            # ITC: SOLO hijos que NO sean de CARD
            visible_types = [
                t for t in all_types
                if t.parent_id is not None and t.id not in card_family_ids
            ]

        else:
            # Otros: solo hijos
            visible_types = [t for t in all_types if t.parent_id is not None]

        # -----------------------------------------------------
        # Regla extra: excluir TODO lo que cuelgue de USB
        # -----------------------------------------------------
        visible_types = [
            t for t in visible_types
            if not has_ancestor_code(t.id, "USB")
        ]

        # =====================================================
        # Conteo de devices por asset_type_id
        # =====================================================
        counts_by_asset_type_id = {
            r.asset_type_id: {
                "total": int(r.total or 0),
                "assigned": int(r.assigned or 0),
            }
            for r in (
                db.query(
                    Device.asset_type_id.label("asset_type_id"),
                    func.count(Device.id).label("total"),
                    func.sum(case((Device.status == "assigned", 1), else_=0)).label("assigned"),
                )
                .filter(Device.active.is_(True))
                .group_by(Device.asset_type_id)
                .all()
            )
        }

        # =====================================================
        # Legacy devices (sin asset_type_id)
        # =====================================================
        legacy_to_asset_code = {
            "vending": "CARD_VENDING",
            "canteen": "CARD_CANTEEN",
            "instructor": "CARD_INSTRUCTOR",
            "guest": "CARD_GUEST",
        }

        asset_id_by_code = {
            (t.code or "").upper(): t.id for t in all_types
        }

        legacy_counts = (
            db.query(
                func.lower(Device.type).label("legacy_type"),
                func.count(Device.id).label("total"),
                func.sum(case((Device.status == "assigned", 1), else_=0)).label("assigned"),
            )
            .filter(Device.active.is_(True))
            .filter(Device.asset_type_id.is_(None))
            .group_by(func.lower(Device.type))
            .all()
        )

        for row in legacy_counts:
            legacy = (row.legacy_type or "").lower()
            target_code = legacy_to_asset_code.get(legacy)
            if not target_code:
                continue

            target_id = asset_id_by_code.get(target_code.upper())
            if not target_id:
                continue

            slot = counts_by_asset_type_id.setdefault(
                target_id, {"total": 0, "assigned": 0}
            )
            slot["total"] += int(row.total or 0)
            slot["assigned"] += int(row.assigned or 0)

        # =====================================================
        # Construir device_stats (lo que consume el template)
        # =====================================================
        device_stats = []
        for at in visible_types:
            code = (at.code or "").lower()
            counts = counts_by_asset_type_id.get(at.id, {"total": 0, "assigned": 0})

            total = counts["total"]
            assigned = counts["assigned"]
            ratio = (assigned / total * 100) if total else 0

            device_stats.append({
                "type": code,
                "total": total,
                "assigned": assigned,
                "ratio": ratio,
            })

        # =====================================================
        # Alertas
        # =====================================================
        alerts = get_alerts_for_user(db, current_user, include_hidden=False) or []

        now_utc = datetime.now(timezone.utc)
        alerts_all = get_alerts_for_user(db, current_user, include_hidden=True) or []
        alerts_summary = {"notice": 0, "warning": 0, "critical": 0}

        for a in alerts_all:
            a_sev = (a.get("severity") or "notice").strip().lower()
            reasons = a.get("reasons") or []
            if reasons:
                for r in reasons:
                    if not reason_counts_for_calendar(r, now_utc):
                        continue
                    sev = (r.get("severity") or a_sev or "notice").strip().lower()
                    if sev not in alerts_summary:
                        sev = "notice"
                    alerts_summary[sev] += 1
            else:
                sev = a_sev if a_sev in alerts_summary else "notice"
                alerts_summary[sev] += 1
        # =====================================================
        # ITC: aviso rápido de "pickup needed" (si existe)
        # =====================================================
        pickup_notif = None
        if is_itc or is_admin:
            pickup_notif = (
                db.query(models.Notification)
                .filter(models.Notification.active.is_(True))
                .filter(models.Notification.department_target == "ITC support")
                .filter(models.Notification.status == "open")
                .filter(models.Notification.type == "pickup_needed")
                .order_by(models.Notification.created_at.desc())
                .first()
            )    

        pickup_message_display = None

        if pickup_notif:
            # Hora local bien formateada
            local_when = None
            if pickup_notif.created_at:
                dt = pickup_notif.created_at
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                local_dt = dt.astimezone(ZoneInfo("Europe/Madrid"))
                local_when = local_dt.strftime("%d/%m/%Y %H:%M")

            # Extraer nota si existe (sin jugar a regex extremo)
            note = None
            raw_msg = pickup_notif.message or ""
            if "Note:" in raw_msg:
                note = raw_msg.split("Note:", 1)[1].strip()

            # Construir mensaje final
            parts = []
            #parts.append("TCO requests ITC pickup.")

            #if local_when:
            #    parts.append(f"When: {local_when}")

            if note:
                parts.append(f"Note: {note}")

            pickup_message_display = "\n".join(parts)   
        # =====================================================
        # Render
        # =====================================================
        return render_template(
            "index.html",
            total_users=total_users,
            total_devices=total_devices,
            total_courses=total_courses,
            total_assignments=total_assignments,
            total_movements=total_movements,
            total_active_cards=total_active_cards,
            device_stats=device_stats,
            alerts=alerts,
            alerts_summary=alerts_summary,
            pickup_notif=pickup_notif,
            pickup_message_display=pickup_message_display,
        )

    finally:
        db.close()


@bp.route("/test-calendar")
@login_required
def test_calendar():
    return render_template("test_calendar.html")

def _contains(text: str | None, q: str) -> bool:
    if not q:
        return True
    if not text:
        return False
    return q.lower() in text.lower()


def _alert_has_type(alert: dict, type_q: str) -> bool:
    if not type_q:
        return True

    type_q = type_q.strip().lower()
    keys = [k.lower() for k in (alert.get("keys") or [])]

    if type_q in keys:
        return True

    if type_q.endswith("_"):
        return any(k.startswith(type_q) for k in keys)

    if type_q in ("tco", "itc", "admin"):
        return any(k.startswith(type_q + "_") for k in keys)

    return any(type_q in k for k in keys)


def _responsible_matches(course, q: str) -> bool:
    if not q:
        return True
    if not course:
        return False

    q = q.lower().strip()
    resp = getattr(course, "responsible", None)
    if not resp:
        return False

    fields = [
        getattr(resp, "username", None),
        getattr(resp, "email", None),
        getattr(resp, "name", None),
        getattr(resp, "surname", None),
    ]
    hay = " ".join(str(f) for f in fields if f)
    return q in hay.lower()


def filter_alerts(alerts: list[dict], severity=None, type_q=None, q=None, responsible=None):
    sev = (severity or "").strip().lower()
    type_q = (type_q or "").strip()
    q = (q or "").strip()
    responsible = (responsible or "").strip()

    out = []
    for a in alerts:
        if sev and (a.get("severity") or "").lower() != sev:
            continue

        if type_q and not _alert_has_type(a, type_q):
            continue

        if q:
            msg_ok = _contains(a.get("message"), q)
            reasons_ok = any(
                _contains((r or {}).get("text"), q)
                for r in (a.get("reasons") or [])
            )

            course = a.get("course")
            course_name = (
                getattr(course, "name", None)
                or getattr(course, "course", None)
                if course else None
            )
            course_ok = _contains(course_name, q)

            if not (msg_ok or reasons_ok or course_ok):
                continue

        course = a.get("course")
        if responsible and not _responsible_matches(course, responsible):
            continue

        out.append(a)

    return out


@bp.app_context_processor
def inject_notifications_summary():
    db = SessionLocal()
    try:
        if not current_user.is_authenticated:
            return dict(notifications_summary={"unread": 0})

        role = (getattr(current_user, "role", "") or "").strip().lower()
        dept = (getattr(current_user, "department", "") or "").strip()

        q = (
            db.query(models.Notification.id)
              .filter(models.Notification.active.is_(True))
              .filter(models.Notification.read_at.is_(None))
              .filter(models.Notification.status == "open")
        )

        # admin ve todo, el resto solo su dept
        if "admin" not in role:
            if not dept:
                return dict(notifications_summary={"unread": 0})
            q = q.filter(models.Notification.department_target == dept)

        unread = q.count()
        return dict(notifications_summary={"unread": unread})
    finally:
        db.close()

@bp.route("/dashboard/pickup/<int:notif_id>/done", methods=["POST"])
@login_required
def mark_pickup_done(notif_id):
    db = SessionLocal()
    try:
        actor_role = (getattr(current_user, "role", "") or "").strip().lower()
        actor_dept = (getattr(current_user, "department", "") or "").strip().lower()

        is_admin = ("admin" in actor_role)
        is_itc = (actor_dept == "itc support") or actor_role.startswith("itc")

        if not (is_admin or is_itc):
            flash("Not allowed.", "danger")
            return redirect(url_for("main.index"))

        n = db.query(Notification).get(notif_id)
        if not n or not (n.active is True):
            flash("Notification not found.", "warning")
            return redirect(url_for("main.index"))

        # Asegura que no puedan cerrar “cualquier cosa”
        if (n.type or "") != "pickup_needed" or (n.department_target or "") != "ITC support":
            flash("Not allowed.", "danger")
            return redirect(url_for("main.index"))

        n.status = "done"
        # opcional: marcar como leído también
        try:
            n.read = True
        except Exception:
            pass

        # opcional: si tienes campos de auditoría
        if hasattr(n, "updated_at"):
            n.updated_at = datetime.now(timezone.utc)

        db.commit()
        flash("Pickup marked as done.", "success")
        return redirect(url_for("main.index"))

    finally:
        db.close()



@bp.route("/dashboard/itc-pickup-fragment")
@login_required
def dashboard_itc_pickup_fragment():
    db = SessionLocal()
    try:
        actor_role = (getattr(current_user, "role", "") or "").strip().lower()
        actor_dept = (getattr(current_user, "department", "") or "").strip().lower()

        is_admin = ("admin" in actor_role)
        is_itc = (actor_dept == "itc support") or actor_role.startswith("itc")

        pickup_notif = None
        if is_itc or is_admin:
            pickup_notif = (
                db.query(models.Notification)
                .filter(models.Notification.active.is_(True))
                .filter(models.Notification.department_target == "ITC support")
                .filter(models.Notification.status == "open")
                .filter(models.Notification.type == "pickup_needed")
                .order_by(models.Notification.created_at.desc())
                .first()
            )

        pickup_message_display = None
        if pickup_notif:
            local_when = None
            if pickup_notif.created_at:
                dt = pickup_notif.created_at
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                local_dt = dt.astimezone(ZoneInfo("Europe/Madrid"))
                local_when = local_dt.strftime("%d/%m/%Y %H:%M")

            note = None
            raw_msg = pickup_notif.message or ""
            if "Note:" in raw_msg:
                note = raw_msg.split("Note:", 1)[1].strip()

            parts = []
            # if local_when: parts.append(f"When: {local_when}")
            if note:
                parts.append(f"Note: {note}")

            pickup_message_display = "\n".join(parts)

        return render_template(
            "dashboard/_itc_pickup_fragment.html",
            pickup_notif=pickup_notif,
            pickup_message_display=pickup_message_display,
        )
    finally:
        db.close()

@bp.get("/dashboard/partials/alerts")
@login_required
def dashboard_alerts_partial():
    db = SessionLocal()
    try:
        alerts_summary = build_alerts_summary(db, current_user)
        return render_template(
            "partials/_alerts_accordion.html",
            alerts_summary=alerts_summary
        )
    finally:
        db.close()

@bp.get("/dashboard/partials/calendar")
@login_required
def dashboard_calendar_partial():
    return render_template("partials/_calendar.html")