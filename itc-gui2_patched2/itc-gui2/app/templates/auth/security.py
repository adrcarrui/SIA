# app/auth/security.py

from functools import wraps
from flask import abort
from flask_login import current_user


def roles_required(*roles):
    """
    Restringe el acceso a usuarios cuyo current_user.role esté en 'roles'.
    Uso:
        @roles_required("admin")
        @roles_required("admin", "supervisor")
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if getattr(current_user, "role", None) not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
