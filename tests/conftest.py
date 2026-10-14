import os
import sys
import tempfile

import pytest

# config.py lee estas variables al importarse: se fijan antes de importar la app.
DATA_DIR = tempfile.mkdtemp(prefix="liga-tests-")
os.environ["LIGA_DATA_DIR"] = DATA_DIR
os.environ.pop("DATABASE_URL", None)
for rol, clave in {"SANCIONES_PASS": "s", "VOCALIA_PASS": "v", "TECNICA_PASS": "t", "CALIFICACION_PASS": "c"}.items():
    os.environ[rol] = clave
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.database import DBWrapper, _conectar  # noqa: E402


@pytest.fixture
def app():
    ruta = os.path.join(DATA_DIR, "liga.db")
    if os.path.exists(ruta):
        os.remove(ruta)
    aplicacion = create_app({"TESTING": True})
    yield aplicacion


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    conexion = DBWrapper(_conectar())
    yield conexion
    conexion.close()


def login(client, usuario, clave):
    client.get("/logout")
    respuesta = client.post("/login", data={"usuario": usuario, "clave": clave})
    assert respuesta.status_code == 302


def login_admin(client):
    login(client, "admin", "Oyambarillo2026")
