# app/__init__.py
from flask import Flask, redirect, url_for
from .extensions import db as sqla_db, login_manager, bcrypt   # ← instancia de Flask-SQLAlchemy
from .db import DATABASE_URL                                   # ← tu URL de SQLAlchemy puro
from flask_login import current_user

def create_app():
    app = Flask(__name__)

    # Config
    app.config["SECRET_KEY"] = "cambia-esto"
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Inicializa extensiones (usa sqla_db, NO "db")
    sqla_db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    # Blueprints
    from .auth import bp as auth_bp
    from .main import bp as main_bp
    from .users import bp as users_bp
    from .courses import bp as courses_bp
    from .devices import bp as devices_bp
    from .courses import bp as courses_bp
    from .movements import bp as movements_bp
    from .assignments import bp as assignments_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(main_bp)
    app.register_blueprint(users_bp, url_prefix="/users")
    app.register_blueprint(courses_bp, url_prefix="/courses")
    app.register_blueprint(devices_bp, url_prefix="/devices")
    app.register_blueprint(movements_bp, url_prefix="/movements")
    app.register_blueprint(assignments_bp, url_prefix="/assignments")

    with app.app_context():
        print("\n== URL MAP ==")
        for r in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
            print(f"{r.rule:30s} -> {r.endpoint}")
        print("== FIN URL MAP ==\n")

    @app.route("/")
    def root_redirect_to_login():
        return redirect(url_for("auth.login"))

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
