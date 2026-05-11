from flask import Blueprint

bp = Blueprint("reworks", __name__, template_folder="../templates")

from . import routes  # noqa