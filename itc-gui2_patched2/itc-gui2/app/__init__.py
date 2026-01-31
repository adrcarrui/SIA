# app/__init__.py
from datetime import datetime,timedelta
from flask import Flask, redirect, url_for, request, session
from .extensions import db as sqla_db, login_manager, bcrypt   # ← instancia de Flask-SQLAlchemy
from .db import DATABASE_URL                                   # ← tu URL de SQLAlchemy puro
from flask_login import current_user
from app.scripts.get_overdue_assignments import (
    get_cards_vs_trainees_alerts,
    get_overdue_course_alerts,
)
from app.db import SessionLocal
from flask.sessions import SecureCookieSessionInterface
# NFC is optional. In the distributed-reader model, the server does not need PC/SC.
try:
    from app.nfc.acr122 import init_buzzer_off
except Exception:  # smartcard libs/reader not installed on server
    init_buzzer_off = None

def create_app():
    app = Flask(__name__)
    class DeptSessionInterface(SecureCookieSessionInterface):
        def get_expiration_time(self, app, session):
            # Si la sesión no es permanente, Flask no pone expiración (cookie de navegador)
            if not session.permanent:
                return None

            try:
                from flask_login import current_user
                dept = (getattr(current_user, "department", "") or "").strip().lower()
            except Exception:
                dept = ""

            # TCO: 30 minutos
            if dept == "tco":
                return datetime.utcnow() + timedelta(minutes=30)

            # ITC Support: muy largo (prácticamente nunca)
            if dept == "itc support":
                return datetime.utcnow() + timedelta(days=3650)  # 10 años

            # Resto: 15 minutos
            return datetime.utcnow() + timedelta(minutes=15)

    app.session_interface = DeptSessionInterface()

    @app.before_request
    def refresh_session_by_dept():
        if not current_user.is_authenticated:
            return

        # No dejes que el polling mantenga viva la sesión
        if request.path.startswith("/api/counters"):
            return

        # Renovar expiración en actividad real
        session.permanent = True

    if init_buzzer_off is not None:
        try:
            init_buzzer_off()
        except Exception as e:
            print(f"[WARN] Could not init NFC buzzer off: {e}")

    # Config
    app.config["SECRET_KEY"] = "cambia-esto"
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

    # Inicializa extensiones (usa sqla_db, NO "db")
    sqla_db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    # ✅ Rollback automático si algo falla en la request
    @app.teardown_request
    def rollback_on_error(exc):
        if exc is not None:
            try:
                sqla_db.session.rollback()
            except Exception:
                pass

    # ✅ Cinturón extra: si la respuesta es 500, aseguramos rollback
    @app.after_request
    def rollback_on_500(resp):
        try:
            if resp.status_code >= 500:
                sqla_db.session.rollback()
        except Exception:
            pass
        return resp

    @app.context_processor
    def inject_overdue_counter():
        # OJO: esto usa SessionLocal (otra sesión distinta).
        # Está bien mientras NO intentes mezclar objetos ORM entre sesiones.
        db = SessionLocal()
        try:
            overdue = get_overdue_course_alerts(db)
            total_overdue_1 = sum(1 for o in overdue if o.get("type") == "overdue_1")
            total_overdue_2 = sum(1 for o in overdue if o.get("type") == "overdue_2")
            return {
                "overdue_total": len(overdue),
                "overdue_1_count": total_overdue_1,
                "overdue_2_count": total_overdue_2,
            }
        finally:
            db.close()

    # Blueprints
    from .auth import bp as auth_bp
    from .main import bp as main_bp
    from .users import bp as users_bp
    from .courses import bp as courses_bp
    from .devices import bp as devices_bp
    from .movements import bp as movements_bp
    from .assignments import bp as assignments_bp
    from .asset_types import bp as asset_types_bp
    from .notifications import bp as notifications_bp
    from .alerts import bp as alerts_bp
    from .api import bp as api_bp
    from .prueba import bp as prueba_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(main_bp)
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(courses_bp, url_prefix="/courses")
    app.register_blueprint(devices_bp, url_prefix="/devices")
    app.register_blueprint(movements_bp, url_prefix="/movements")
    app.register_blueprint(assignments_bp, url_prefix="/assignments")
    app.register_blueprint(asset_types_bp, url_prefix="/asset_types")
    app.register_blueprint(notifications_bp, url_prefix="/notifications")
    app.register_blueprint(alerts_bp, url_prefix="/alerts")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(prueba_bp, url_prefix="/prueba")

    with app.app_context():
        print("\n== URL MAP ==")
        for r in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
            print(f"{r.rule:30s} -> {r.endpoint}")
        print("== FIN URL MAP ==\n")

    # user_loader (usa la sesión de Flask-SQLAlchemy)
    from .models import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return sqla_db.session.get(User, int(user_id))

    # current_user disponible en todas las plantillas
    @app.context_processor
    def inject_user():
        return dict(current_user=current_user)

    return app
