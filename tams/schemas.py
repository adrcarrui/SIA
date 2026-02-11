# schemas.py
from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Optional, Literal, Any

# USERS
class UserBase(BaseModel):
    name: str
    username: Optional[str] = None
    uid: Optional[str] = Field(None, description="CÃ³digo MIFARE del usuario")

class UserCreate(UserBase):
    pass

class UserUpdate(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    uid: Optional[str] = None
    active: Optional[bool] = None

class UserOut(UserBase):
    id: int
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True

# COURSES
class CourseBase(BaseModel):
    name: str
    start_date: date
    end_date: date
    status: Optional[str] = "planned"

class CourseCreate(CourseBase):
    pass

class CourseUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None

class CourseOut(CourseBase):
    id: int

    class Config:
        from_attributes = True

# DEVICES
class DeviceBase(BaseModel):
    uid: str
    name: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = "available"
    active: Optional[bool] = True

class DeviceCreate(DeviceBase):
    pass

class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    active: Optional[bool] = None

class DeviceOut(DeviceBase):
    id: int

    class Config:
        from_attributes = True

#MOVEMENTS

class MovementBase(BaseModel):
    entity_type: Literal["user","device","course"]
    entity_id: Optional[int] = None
    action: Literal["create","update","delete"]
    description: Optional[str] = None
    before_data: Optional[dict[str, Any]] = None
    after_data: Optional[dict[str, Any]] = None
    success: bool = True

class MovementRead(MovementBase):
    id: int
    user_id: int
    user_agent: Optional[str] = None
    create_at: datetime

    class Config:
        from_attributes = True

class MovementList(MovementBase):
    #Dame el historial de X
    movement: list[MovementRead]