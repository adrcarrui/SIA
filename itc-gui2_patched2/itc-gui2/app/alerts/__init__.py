from flask import Blueprint

bp = Blueprint("alerts", __name__, url_prefix="/alerts")

from . import routes,api  # noqa