# models.py
from datetime import datetime, date, timezone

from flask_login import UserMixin
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy import text
from sqlalchemy.sql.sqltypes import Boolean
from .extensions import db


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    surname = db.Column(db.String(100))
    uid = db.Column(db.String(60), unique=True)  # encaja mejor con la columna de la BD
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True)
    role = db.Column(db.String(50), nullable=False, default="user")
    active = db.Column(db.Boolean, default=True, nullable=False)
    # NO tiene sentido default=True en un String; lo dejamos nullable y sin default
    department = db.Column(db.String(50), nullable=True)

    movements = relationship(
        "Movements",
        back_populates="user",
        passive_deletes=False,
    )

    assignments_created = relationship(
        "Assignment",
        back_populates="creator",
        foreign_keys="Assignment.created_by",
    )

    # helpers opcionales
    def get_id(self):
        return str(self.id)


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(120), nullable=False)
    uid = db.Column(db.String(64), unique=True, nullable=False)

    # LEGACY: mantener temporalmente para compatibilidad
    type = db.Column(db.String(20), nullable=False, default="guest")

    status = db.Column(db.String(20), nullable=False, default="available")
    active = db.Column(Boolean, nullable=False, server_default=text("true"))
    notes = db.Column(db.String(255))

    # NUEVO: enlace a AssetType (subtipo)
    asset_type_id = db.Column(
        db.Integer,
        db.ForeignKey("asset_types.id", ondelete="RESTRICT"),
        nullable=True,   # luego lo pasas a False cuando el código esté migrado
        index=True,
    )

    # NUEVO: para equipos que van por barcode (laptop/usb)
    barcode = db.Column(db.String(128), nullable=True, unique=False)

    asset_type = db.relationship("AssetType", back_populates="devices")

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    assignments = relationship("Assignment", back_populates="device")

    def __repr__(self):
        return (
            f"<Device id={self.id} uid={self.uid} "
            f"asset_type_id={self.asset_type_id} status={self.status}>"
        )

    @property
    def asset_type_code(self):
        return self.asset_type.code if self.asset_type else None

    @property
    def asset_type_name(self):
        return self.asset_type.name if self.asset_type else None

    @property
    def asset_parent_name(self):
        # Tipo raíz (CARD/LAPTOP/USB) si tienes parent cargado
        if self.asset_type and self.asset_type.parent:
            return self.asset_type.parent.name
        return None
    
class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    course = db.Column(db.String(120), nullable=False)

    start_date = db.Column(Date, nullable=True)
    end_date = db.Column(Date, nullable=True)

    # Estado negocio (TCO)
    status_tco = db.Column(db.String(20), nullable=True)

    created_at = db.Column(
        db.DateTime, nullable=False, server_default=func.now()
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    notes = db.Column(db.String(255), nullable=True)
    trainees = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(255), nullable=True)
    client = db.Column(db.String(255), nullable=True)

    # Responsable del curso (User)
    responsible_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Estado ITC / soporte
    status_itc = db.Column(db.String(20), nullable=True)

    # Relaciones
    assignments = relationship("Assignment", back_populates="course")

    responsible = relationship(
        "User",
        foreign_keys=[responsible_id],
        backref="courses_responsible_for",
    )

    asset_requirements = relationship(
    "CourseAssetRequirement",
    back_populates="course",
    cascade="all, delete-orphan",
    lazy="joined",
    )
    def __repr__(self):
        return f"<Course id={self.id} course={self.course!r} name={self.name!r}>"

    @property
    def auto_status(self) -> str:
        """
        Estado calculado según fechas y hoy (vista TCO).
        Devuelve siempre en minúsculas: planned / active / finished / cancelled
        """

        # Si el curso está marcado como cancelado explícitamente, lo respetamos
        if (self.status_tco or "").lower() == "cancelled":
            return "cancelled"

        today = date.today()

        if self.start_date is None and self.end_date is None:
            # Sin fechas: lo tratamos como 'planned' por defecto
            return "planned"

        # Solo fecha de inicio
        if self.start_date and not self.end_date:
            if today < self.start_date:
                return "planned"
            elif today == self.start_date:
                return "active"
            else:
                return "finished"

        # Inicio y fin
        if today < self.start_date:
            return "planned"
        if self.start_date <= today <= self.end_date:
            return "active"
        if today > self.end_date:
            return "finished"

        # Por si acaso
        return "planned"


class Movements(db.Model):
    __tablename__ = "movements"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=True)
    action = Column(String(20), nullable=False)
    before_data = Column(JSONB, nullable=True)
    after_data = Column(JSONB, nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    description = Column(Text, nullable=False)
    user_agent = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    user = relationship("User", back_populates="movements")

    def __repr__(self):
        return (
            f"<Movement id={self.id} user_id={self.user_id} "
            f"action={self.action} entity_type={self.entity_type} "
            f"entity_id={self.entity_id}>"
        )


class Assignment(db.Model):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer,ForeignKey("devices.id", onupdate="CASCADE", ondelete="RESTRICT"),nullable=False,)
    course_id = Column(Integer,ForeignKey("courses.id", onupdate="CASCADE", ondelete="RESTRICT"),nullable=False,)
    assigned_at = Column(DateTime(timezone=True),nullable=False,default=datetime.utcnow,)
    released_at = Column(DateTime(timezone=True),nullable=True,)
    status = Column(String(20),nullable=False,default="active",)
    created_by = Column(Integer,ForeignKey("users.id", onupdate="CASCADE", ondelete="SET NULL"),nullable=True,)
    notes = Column(String(255),nullable=True,)
    created_at = Column(DateTime(timezone=True),nullable=False,default=datetime.utcnow,)
    updated_at = Column(DateTime(timezone=True),nullable=False,default=datetime.utcnow,onupdate=datetime.utcnow,)

    # Relaciones
    device = relationship("Device", back_populates="assignments")
    course = relationship("Course", back_populates="assignments")

    # usuario que creó el assignment
    creator = relationship(
        "User",
        back_populates="assignments_created",
        foreign_keys=[created_by],
    )

    def __repr__(self):
        return (
            f"<Assignment id={self.id} "
            f"device_id={self.device_id} course_id={self.course_id} "
            f"status={self.status} created_by={self.created_by}>"
        )

#Tabla assets

class AssetType(db.Model):
    __tablename__ = "asset_types"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)

    parent_id = Column(Integer, ForeignKey("asset_types.id", ondelete="RESTRICT"), nullable=True)

    managed_by_department = Column(String(100), nullable=False)

    requires_rfid = Column(Boolean, nullable=False, default=False)
    requires_barcode = Column(Boolean, nullable=False, default=False)
    show_in_calendar = Column(Boolean, nullable=False, default=True)

    sort_order = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Jerarquía
    parent = relationship("AssetType", remote_side=[id], backref="children")
    devices = relationship("Device", back_populates="asset_type")
    course_requirements = relationship("CourseAssetRequirement", backref="asset_type_ref")

    def __repr__(self):
        return f"<AssetType code={self.code} name={self.name} parent_id={self.parent_id}>"  
    
class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    read_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    assigned_to_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    course_id = db.Column(db.Integer, db.ForeignKey("courses.id", ondelete="SET NULL"))

    department_target = db.Column(db.String(50), nullable=False)   # "ITC support", "TCO"
    type = db.Column(db.String(50), nullable=False)                # course_created, course_updated, pickup_request...
    severity = db.Column(db.String(20), nullable=False, default="notice")  # notice|warning|critical
    status = db.Column(db.String(20), nullable=False, default="open")      # open|in_progress|done|dismissed

    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)

    read_at = db.Column(db.DateTime(timezone=True))
    active = db.Column(db.Boolean, nullable=False, default=True)

    # Relaciones opcionales (si te interesa navegar)
    created_by = db.relationship("User", foreign_keys=[created_by_user_id], lazy="joined")
    read_by = db.relationship("User", foreign_keys=[read_by_user_id], lazy="joined")
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_user_id], lazy="joined")
    course = db.relationship("Course", foreign_keys=[course_id], lazy="joined")

    def __repr__(self):
        return f"<Notification id={self.id} type={self.type} target={self.department_target} status={self.status}>"
    
class CourseAssetRequirement(db.Model):
    __tablename__ = "course_asset_requirements"

    id = db.Column(db.Integer, primary_key=True)

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    asset_type_id = db.Column(
        db.Integer,
        db.ForeignKey("asset_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    quantity = db.Column(db.Integer, nullable=False, default=1)
    active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    course = db.relationship("Course", back_populates="asset_requirements")
    asset_type = db.relationship("AssetType", lazy="joined")

    def __repr__(self):
        return f"<CourseAssetRequirement course_id={self.course_id} asset_type_id={self.asset_type_id} qty={self.quantity}>"
