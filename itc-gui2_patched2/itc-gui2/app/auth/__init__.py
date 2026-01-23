from flask import Blueprint
bp = Blueprint("auth", __name__, template_folder="../templates")  # ojo al ../
from . import routes  # noqa