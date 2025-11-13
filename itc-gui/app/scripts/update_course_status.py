import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app.db import SessionLocal
import app.models as models
from sqlalchemy import case, func

def update_course_statuses():
    db = SessionLocal()
    db.query(models.Course).update({
        models.Course.status: case(
            (func.current_date() < models.Course.start_date, 'planned'),
            (func.current_date() > models.Course.end_date, 'finished'),
            else_='active'
        )
    })
    db.commit()
    db.close()
    print("âœ… Estados de los cursos actualizados correctamente")

if __name__ == "__main__":
    update_course_statuses()
