from flask import Blueprint

# Nombre único del blueprint: "devices"
# Usamos la carpeta de templates global: app/templates/...
bp = Blueprint("devices", __name__, template_folder="../templates")

# Importa las rutas para registrar los endpoints en este blueprint
from . import routes  # noqa: E402,F401
