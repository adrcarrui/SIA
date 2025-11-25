# models.py
from .extensions import db
from flask_login import UserMixin
from datetime import datetime,date
from .extensions import db
from sqlalchemy import func
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, String, Boolean, DateTime, text
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB

class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    surname = db.Column(db.String(100))
    uid = db.Column(db.String(100))
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True)
    role = db.Column(db.String(50))
    active = db.Column(db.Boolean, default=True, nullable=False)

    movements = relationship(
        "Movements",
        back_populates="user",
        passive_deletes=False
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

    # Puedes dejarlo como String con CHECK en la DB o usar Enum
    type = db.Column(db.String(20), nullable=False, default="guest")
    status = db.Column(db.String(20), nullable=False, default="available")
    active = Column(Boolean, nullable=False, server_default=text("true"))
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    assignments = relationship("Assignment", back_populates="device")
    def __repr__(self):
        return f"<Device id={self.id} uid={self.uid} type={self.type} status={self.status}>"


class Course(db.Model):
    __tablename__ = "courses"
    id = db.Column(db.Integer, primary_key=True)
    course = db.Column(db.String(120), nullable=False)
    start_date = db.Column(db.Date, nullable=True)
    end_date   = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=func.now())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    notes = db.Column(db.String(255), nullable=True)
    trainees = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(255), nullable=True)
    client = db.Column(db.String(255), nullable=True)
    assignments = relationship("Assignment", back_populates="course")
    def __repr__(self):
        return f"<Course id={self.id} course={self.course!r} name={self.name!r}>"
    
    @property
    def auto_status(self) -> str:
        """Estado calculado según fechas y hoy."""

        # Si el curso está marcado como cancelado a mano, respetamos eso.
        if (self.status or "").lower() == "cancelled":
            return "cancelled"

        today = date.today()

        if self.start_date is None and self.end_date is None:
            # Sin fechas: lo tratamos como 'planned' por defecto
            return "planned"

        # Si solo hay fecha de inicio:
        if self.start_date and not self.end_date:
            if today < self.start_date:
                return "Planned"
            elif today == self.start_date:
                return "Active"
            else:
                return "Finished"

        # Si hay inicio y fin
        if today < self.start_date:
            return "Planned"
        if self.start_date <= today <= self.end_date:
            return "Active"
        if today > self.end_date:
            return "Finished"

        # Por si acaso
        return "Planned"

class Movements(db.Model):
    __tablename__="movements"

    id = Column(Integer, primary_key=True,index=True)

    user_id = Column(Integer,ForeignKey("users.id", ondelete="RESTRICT"),nullable=False)
    entity_type = Column(String(50),nullable=False)
    entity_id = Column(Integer,nullable=True)
    action = Column(String(20),nullable=False)
    before_data = Column(JSONB,nullable=True)
    after_data = Column(JSONB,nullable=True)
    success = Column(Boolean,nullable=False,default=True)
    description = Column(Text,nullable=False)
    user_agent = Column(Text,nullable=False)
    created_at = Column(DateTime(timezone=True),nullable=False,default=datetime.utcnow)

    user = relationship("User", back_populates="movements")

    def __repr__(self):
        return f"<Movement id={self.id} user_id={self.user_id} action={self.action} entity_type={self.entity_type} entity_id={self.entity_id}>"

class Assignment(db.Model):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)

    device_id = Column(
        Integer,
        ForeignKey("devices.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )

    course_id = Column(
        Integer,
        ForeignKey("courses.id", onupdate="CASCADE", ondelete="RESTRICT"),
        nullable=False,
    )

    assigned_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    released_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    status = Column(
        String(20),
        nullable=False,
        default="active",
    )

    created_by = Column(
        Integer,
        ForeignKey("users.id", onupdate="CASCADE", ondelete="SET NULL"),
        nullable=True,
    )

    notes = Column(
        String(255),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

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