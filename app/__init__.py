from flask import Flask
from .config import load_config
from .db import init_db
from .auth import init_basic_auth


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.update(load_config())

    init_db(app)
    init_basic_auth(app)

    from .routes.public import bp as public_bp
    app.register_blueprint(public_bp)

    return app
