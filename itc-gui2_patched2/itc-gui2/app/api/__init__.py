from flask import Blueprint

bp = Blueprint("api", __name__, url_prefix="/api")

from . import routes  # importa las rutas al final