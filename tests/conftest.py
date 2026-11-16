import os
import sys
import tempfile

import pytest

# config.py lee estas variables al importarse: se fijan antes de importar la app.
DATA_DIR = tempfile.mkdtemp(prefix="liga-tests-")
os.environ["LIGA_DATA_DIR"] = DATA_DIR
# Por defecto las pruebas usan SQLite. Con TEST_DATABASE_URL corren contra
# PostgreSQL (el motor de producción en Render), que devuelve filas como dict:
#   TEST_DATABASE_URL=postgresql://usuario:clave@localhost/liga_test pytest
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
else:
    os.environ.pop("DATABASE_URL", None)
for rol, clave in {"SANCIONES_PASS": "s", "VOCALIA_PASS": "v", "TECNICA_PASS": "t", "CALIFICACION_PASS": "c"}.items():
    os.environ[rol] = clave
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.database import DBWrapper, _conectar  # noqa: E402


def _limpiar_postgres():
    import psycopg2

    conexion = psycopg2.connect(TEST_DATABASE_URL)
    conexion.autocommit = True
    with conexion.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    conexion.close()


@pytest.fixture
def app():
    if TEST_DATABASE_URL:
        _limpiar_postgres()
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


solo_sqlite = pytest.mark.skipif(
    bool(TEST_DATABASE_URL), reason="Prueba de migración del archivo SQLite; no aplica en PostgreSQL."
)


def insertar(db, consulta, params=()):
    """INSERT que devuelve el id nuevo en SQLite y en PostgreSQL."""
    if TEST_DATABASE_URL:
        return db.execute(consulta + " RETURNING id", params).fetchone()["id"]
    return db.execute(consulta, params).lastrowid


def login(client, usuario, clave):
    client.get("/logout")
    respuesta = client.post("/login", data={"usuario": usuario, "clave": clave})
    assert respuesta.status_code == 302


def login_admin(client):
    login(client, "admin", "Oyambarillo2026")
