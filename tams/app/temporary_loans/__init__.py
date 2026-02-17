from flask import Blueprint

# Nombre único del blueprint: "temporary_loans"
# Usamos la carpeta de templates global: app/templates/...
bp = Blueprint("temporary_loans", __name__, template_folder="../templates")

# Importa las rutas para registrar los endpoints en este blueprint
from . import routes  # noqa: E402,F401
