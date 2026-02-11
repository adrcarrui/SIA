# main.py
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import List

from app.db import SessionLocal, engine
import app.models as models
import schemas

app = FastAPI(title="TCO Vending Cards API")

# ya creaste las tablas en postgres, asÃ­ que lo dejamos comentado
# models.Base.metadata.create_all(bind=engine)

# dependencia de DB por peticiÃ³n
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def read_root():
    return {"status": "ok", "message": "TCO Vending Cards API"}


# =========================================================
# USERS
# =========================================================
@app.post("/users", response_model=schemas.UserOut)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    if user.username:
        existing = db.query(models.User).filter(models.User.username == user.username).first()
        if existing:
            raise HTTPException(status_code=400, detail="username ya existe")
    if user.uid:
        existing = db.query(models.User).filter(models.User.uid == user.uid).first()
        if existing:
            raise HTTPException(status_code=400, detail="uid ya existe")

    db_user = models.User(
        name=user.name,
        username=user.username,
        uid=user.uid,
        active=True,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.get("/users", response_model=List[schemas.UserOut])
def list_users(db: Session = Depends(get_db)):
    return db.query(models.User).order_by(models.User.id).all()


@app.get("/users/{user_id}", response_model=schemas.UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="usuario no encontrado")
    return user


@app.put("/users/{user_id}", response_model=schemas.UserOut)
def update_user(user_id: int, payload: schemas.UserUpdate, db: Session = Depends(get_db)):
    user = db.query(models.User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="usuario no encontrado")

    data = payload.model_dump(exclude_unset=True)

    if "username" in data and data["username"]:
        existing = (
            db.query(models.User)
            .filter(models.User.username == data["username"], models.User.id != user_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="username ya existe")

    if "uid" in data and data["uid"]:
        existing = (
            db.query(models.User)
            .filter(models.User.uid == data["uid"], models.User.id != user_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="uid ya existe")

    for k, v in data.items():
        setattr(user, k, v)

    db.commit()
    db.refresh(user)
    return user


@app.delete("/users/{user_id}")
def disable_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="usuario no encontrado")
    user.active = False
    db.commit()
    return {"detail": "usuario desactivado"}


# =========================================================
# COURSES
# =========================================================
@app.post("/courses", response_model=schemas.CourseOut)
def create_course(course: schemas.CourseCreate, db: Session = Depends(get_db)):
    if course.end_date < course.start_date:
        raise HTTPException(status_code=400, detail="end_date no puede ser anterior a start_date")
    db_course = models.Course(
        name=course.name,
        start_date=course.start_date,
        end_date=course.end_date,
        status=course.status,
    )
    db.add(db_course)
    db.commit()
    db.refresh(db_course)
    return db_course


@app.get("/courses", response_model=List[schemas.CourseOut])
def list_courses(db: Session = Depends(get_db)):
    return db.query(models.Course).order_by(models.Course.start_date.desc()).all()


@app.get("/courses/{course_id}", response_model=schemas.CourseOut)
def get_course(course_id: int, db: Session = Depends(get_db)):
    course = db.query(models.Course).get(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="curso no encontrado")
    return course


@app.put("/courses/{course_id}", response_model=schemas.CourseOut)
def update_course(course_id: int, payload: schemas.CourseUpdate, db: Session = Depends(get_db)):
    course = db.query(models.Course).get(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="curso no encontrado")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(course, k, v)

    if course.end_date < course.start_date:
        raise HTTPException(status_code=400, detail="end_date no puede ser anterior a start_date")

    db.commit()
    db.refresh(course)
    return course


# =========================================================
# DEVICES
# =========================================================
@app.post("/devices", response_model=schemas.DeviceOut)
def create_device(device: schemas.DeviceCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Device).filter(models.Device.uid == device.uid).first()
    if existing:
        raise HTTPException(status_code=400, detail="ya existe una tarjeta con ese uid")

    db_device = models.Device(
        uid=device.uid,
        name=device.name,
        type=device.type,
        status=device.status or "available",
        active=True if device.active is None else device.active,
    )
    db.add(db_device)
    db.commit()
    db.refresh(db_device)
    return db_device


@app.get("/devices", response_model=List[schemas.DeviceOut])
def list_devices(db: Session = Depends(get_db)):
    return db.query(models.Device).order_by(models.Device.id).all()


@app.get("/devices/{device_id}", response_model=schemas.DeviceOut)
def get_device(device_id: int, db: Session = Depends(get_db)):
    device = db.query(models.Device).get(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="dispositivo no encontrado")
    return device


@app.put("/devices/{device_id}", response_model=schemas.DeviceOut)
def update_device(device_id: int, payload: schemas.DeviceUpdate, db: Session = Depends(get_db)):
    device = db.query(models.Device).get(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="dispositivo no encontrado")

    data = payload.model_dump(exclude_unset=True)

    # no permitir cambiar el uid desde la API
    if "uid" in data:
        raise HTTPException(status_code=400, detail="no se puede cambiar el uid de la tarjeta")

    for k, v in data.items():
        setattr(device, k, v)

    db.commit()
    db.refresh(device)
    return device
