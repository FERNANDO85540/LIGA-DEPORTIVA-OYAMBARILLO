"""Application Factory de la Liga Deportiva Oyambarillo.

    from app import create_app
    app = create_app()

Cada área funcional es un Blueprint en app/blueprints/; la lógica reutilizable
(consultas y cálculos) vive en app/services/; la conexión y el esquema de la
base de datos en app/database.py; y las constantes en config.py.
"""
from flask import Flask

from config import MOSTRAR_TESORERIA, Config, STATIC_DIR, TEMPLATES_DIR


def create_app(config_extra=None):
    app = Flask(__name__, static_folder=STATIC_DIR, template_folder=TEMPLATES_DIR)
    app.config.from_object(Config)
    if config_extra:
        app.config.update(config_extra)
    app.secret_key = app.config["SECRET_KEY"]

    from app.database import close_db, init_db, preparar_directorios_de_datos
    preparar_directorios_de_datos()
    app.teardown_appcontext(close_db)

    from app.utils import formatear_fecha_hora
    app.jinja_env.filters["fecha_hora"] = formatear_fecha_hora

    @app.context_processor
    def _variables_globales():
        return {"mostrar_tesoreria": MOSTRAR_TESORERIA}

    from app.blueprints import (
        auth, carnets, categorias, comision, equipos, inscripcion, jugadores, main, publico, sanciones,
        tecnica, vocalia,
    )
    for modulo in (main, auth, inscripcion, equipos, jugadores, categorias, carnets, comision, tecnica,
                   sanciones, vocalia, publico):
        app.register_blueprint(modulo.bp)

    try:
        init_db()
    except Exception as e:
        # Si la base de datos no responde al arrancar (ej. suspendida por el
        # proveedor), no tumbamos todo el proceso: dejamos que arranque igual
        # para que las páginas que no dependen de la base (y los mensajes de
        # error) se puedan mostrar en vez de un 502 total.
        print(f"ADVERTENCIA: no se pudo inicializar la base de datos al arrancar: {e}")

    return app


_app_compat = None


def __getattr__(nombre):
    """Compatibilidad con el comando de arranque anterior `gunicorn app:app`:
    si alguien pide `app.app`, se crea (una sola vez) la aplicación."""
    global _app_compat
    if nombre == "app":
        if _app_compat is None:
            _app_compat = create_app()
        return _app_compat
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")
