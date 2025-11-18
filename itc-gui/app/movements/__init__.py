# app/movements/__init__.py
from flask import Blueprint

bp = Blueprint("movements", __name__, url_prefix="/movements")

from . import routes  # importa las rutas al final
