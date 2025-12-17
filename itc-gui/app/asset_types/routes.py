from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from app.db import SessionLocal
import app.models as models
from . import bp

DEPARTMENTS = ["TCO", "ITC support"]  # ajusta si luego sale alguno más


ALLOWED_ROLES = ("admin", "supervisor")

def is_admin_user():
    # Mantengo el nombre para no tocar más código, pero ahora es "admin o supervisor"
    role = (getattr(current_user, "role", "") or "")
    role = role.strip().lower()

    # soporta "admin", "admin,supervisor", "itc_admin", etc.
    tokens = [t.strip() for t in role.replace(";", ",").split(",") if t.strip()]

    # match directo: "admin" / "supervisor"
    if role in ALLOWED_ROLES:
        return True

    # match por tokens exactos: "admin,supervisor"
    if any(r in tokens for r in ALLOWED_ROLES):
        return True

    # match por substring: "itc_admin", "supervisor_itc"
    if any(r in role for r in ALLOWED_ROLES):
        return True

    return False


def require_admin():
    # Mantengo el nombre para no tocar más código
    if not current_user.is_authenticated or not is_admin_user():
        dept = (getattr(current_user, "department", "") or "").strip().lower()
        role = (getattr(current_user, "role", "") or "").strip().lower()
        if "supervisor" in role and dept != "itc support":
            abort(403)
        abort(403)


@bp.before_request
def _guard():
    # Admin y Supervisor pueden ver/editar asset types
    require_admin()


def _get_roots(db):
    return (
        db.query(models.AssetType)
          .filter(models.AssetType.parent_id.is_(None))
          .order_by(models.AssetType.sort_order.asc(), models.AssetType.code.asc())
          .all()
    )


@bp.route("/")
@login_required
def index():
    db = SessionLocal()
    try:
        q = (request.args.get("q") or "").strip()

        query = db.query(models.AssetType)

        if q:
            like = f"%{q}%"
            query = query.filter(
                (models.AssetType.code.ilike(like)) |
                (models.AssetType.name.ilike(like)) |
                (models.AssetType.managed_by_department.ilike(like))
            )

        asset_types = query.order_by(
            models.AssetType.parent_id.asc().nullsfirst(),
            models.AssetType.sort_order.asc(),
            models.AssetType.code.asc()
        ).all()

        roots = _get_roots(db)

        # Mapa de parent -> children para render bonito
        children_map = {}
        for at in asset_types:
            if at.parent_id is not None:
                children_map.setdefault(at.parent_id, []).append(at)

        return render_template(
            "asset_types/index.html",
            page_title="Asset types",
            q=q,
            roots=roots,
            children_map=children_map,
            asset_types=asset_types,
            DEPARTMENTS=DEPARTMENTS
        )
    finally:
        db.close()


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    db = SessionLocal()
    try:
        roots = _get_roots(db)

        if request.method == "POST":
            code = (request.form.get("code") or "").strip()
            name = (request.form.get("name") or "").strip()
            parent_id_raw = (request.form.get("parent_id") or "").strip()
            managed_by = (request.form.get("managed_by_department") or "").strip()
            sort_order_raw = (request.form.get("sort_order") or "0").strip()

            requires_rfid = request.form.get("requires_rfid") == "on"
            requires_barcode = request.form.get("requires_barcode") == "on"
            show_in_calendar = request.form.get("show_in_calendar") == "on"
            active = request.form.get("active") == "on"

            if not code or not name:
                flash("Code y Name son obligatorios.", "warning")
                return render_template(
                    "asset_types/form.html",
                    page_title="New asset type",
                    asset_type=None,
                    roots=roots,
                    DEPARTMENTS=DEPARTMENTS
                )

            code = code.upper().replace(" ", "_")

            parent_id = None
            if parent_id_raw:
                try:
                    parent_id = int(parent_id_raw)
                except ValueError:
                    parent_id = None

            if managed_by not in DEPARTMENTS:
                flash("Departamento inválido.", "warning")
                return render_template(
                    "asset_types/form.html",
                    page_title="New asset type",
                    asset_type=None,
                    roots=roots,
                    DEPARTMENTS=DEPARTMENTS
                )

            try:
                sort_order = int(sort_order_raw)
            except ValueError:
                sort_order = 0

            at = models.AssetType(
                code=code,
                name=name,
                parent_id=parent_id,
                managed_by_department=managed_by,
                requires_rfid=requires_rfid,
                requires_barcode=requires_barcode,
                show_in_calendar=show_in_calendar,
                sort_order=sort_order,
                active=active,
            )

            db.add(at)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("No se pudo crear. Revisa que el Code sea único.", "danger")
                return render_template(
                    "asset_types/form.html",
                    page_title="New asset type",
                    asset_type=None,
                    roots=roots,
                    DEPARTMENTS=DEPARTMENTS
                )

            flash("Asset type creado.", "success")
            return redirect(url_for("asset_types.index"))

        return render_template(
            "asset_types/form.html",
            page_title="New asset type",
            asset_type=None,
            roots=roots,
            DEPARTMENTS=DEPARTMENTS
        )
    finally:
        db.close()


@bp.route("/<int:at_id>/edit", methods=["GET", "POST"])
@login_required
def edit(at_id):
    db = SessionLocal()
    try:
        at = db.query(models.AssetType).get(at_id)
        if not at:
            flash("Asset type no encontrado.", "warning")
            return redirect(url_for("asset_types.index"))

        roots = _get_roots(db)

        if request.method == "POST":
            code = (request.form.get("code") or "").strip()
            name = (request.form.get("name") or "").strip()
            parent_id_raw = (request.form.get("parent_id") or "").strip()
            managed_by = (request.form.get("managed_by_department") or "").strip()
            sort_order_raw = (request.form.get("sort_order") or "0").strip()

            requires_rfid = request.form.get("requires_rfid") == "on"
            requires_barcode = request.form.get("requires_barcode") == "on"
            show_in_calendar = request.form.get("show_in_calendar") == "on"
            active = request.form.get("active") == "on"

            if not code or not name:
                flash("Code y Name son obligatorios.", "warning")
                return render_template(
                    "asset_types/form.html",
                    page_title="Edit asset type",
                    asset_type=at,
                    roots=roots,
                    DEPARTMENTS=DEPARTMENTS
                )

            code = code.upper().replace(" ", "_")

            parent_id = None
            if parent_id_raw:
                try:
                    parent_id = int(parent_id_raw)
                except ValueError:
                    parent_id = None

            if parent_id == at.id:
                flash("Un asset type no puede ser padre de sí mismo.", "warning")
                return render_template(
                    "asset_types/form.html",
                    page_title="Edit asset type",
                    asset_type=at,
                    roots=roots,
                    DEPARTMENTS=DEPARTMENTS
                )

            if managed_by not in DEPARTMENTS:
                flash("Departamento inválido.", "warning")
                return render_template(
                    "asset_types/form.html",
                    page_title="Edit asset type",
                    asset_type=at,
                    roots=roots,
                    DEPARTMENTS=DEPARTMENTS
                )

            try:
                sort_order = int(sort_order_raw)
            except ValueError:
                sort_order = 0

            at.code = code
            at.name = name
            at.parent_id = parent_id
            at.managed_by_department = managed_by
            at.requires_rfid = requires_rfid
            at.requires_barcode = requires_barcode
            at.show_in_calendar = show_in_calendar
            at.sort_order = sort_order
            at.active = active

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                flash("No se pudo actualizar. Revisa que el Code sea único.", "danger")
                return render_template(
                    "asset_types/form.html",
                    page_title="Edit asset type",
                    asset_type=at,
                    roots=roots,
                    DEPARTMENTS=DEPARTMENTS
                )

            flash("Asset type actualizado.", "success")
            return redirect(url_for("asset_types.index"))

        return render_template(
            "asset_types/form.html",
            page_title="Edit asset type",
            asset_type=at,
            roots=roots,
            DEPARTMENTS=DEPARTMENTS
        )
    finally:
        db.close()


@bp.route("/<int:at_id>/delete", methods=["POST"])
@login_required
def delete(at_id):
    db = SessionLocal()
    try:
        at = db.query(models.AssetType).get(at_id)
        if not at:
            flash("Asset type no encontrado.", "warning")
            return redirect(url_for("asset_types.index"))

        has_children = db.query(models.AssetType.id).filter(models.AssetType.parent_id == at_id).first()
        if has_children:
            flash("No se puede eliminar: tiene subtipos asociados.", "danger")
            return redirect(url_for("asset_types.index"))

        in_use = db.query(models.Device.id).filter(models.Device.asset_type_id == at_id).first()
        if in_use:
            flash("No se puede eliminar: hay devices usando este asset type.", "danger")
            return redirect(url_for("asset_types.index"))

        db.delete(at)
        db.commit()
        flash("Asset type eliminado.", "success")
        return redirect(url_for("asset_types.index"))
    finally:
        db.close()