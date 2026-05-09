"""Local dev entry point. On Render we use gunicorn (see Procfile)."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    import os
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=5000, debug=debug)
