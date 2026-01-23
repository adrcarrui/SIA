from flask import Blueprint

bp = Blueprint("asset_types", __name__, url_prefix="/asset-types")

from . import routes  # noqa