import os
from app import create_app

# crea la instancia de Flask a nivel de módulo
app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=True,
    )

    