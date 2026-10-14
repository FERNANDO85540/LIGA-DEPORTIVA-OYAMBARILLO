import os
import sqlite3
from datetime import datetime, timedelta, timezone

from app.utils import ahora_ecuador, nombre_corto
from tests.conftest import DATA_DIR, login, login_admin


def _equipo(db, nombre, categoria="Sub 45", division=""):
    db.execute("INSERT INTO equipos (nombre, categoria, division) VALUES (?, ?, ?)", (nombre, categoria, division))
    db.commit()
    return db.execute("SELECT id FROM equipos WHERE nombre = ?", (nombre,)).fetchone()["id"]


def _inscribir(client, equipo_id, cedula, dorsal="", nacimiento="1975-01-01"):
    return client.post(f"/equipo/{equipo_id}/agregar_jugador", data={
        "cedula": cedula, "nombres": "Juan", "apellidos": "Pérez", "fecha_nacimiento": nacimiento,
        "numero_camiseta": dorsal,
    }, follow_redirects=True).get_data(as_text=True)


def test_mismo_jugador_en_distintos_torneos_pero_no_dos_veces_en_el_mismo(db, client):
    login_admin(client)
    sub45_a, sub45_b = _equipo(db, "ALFA"), _equipo(db, "BETA")
    senior = _equipo(db, "HALCONES", "Senior")

    _inscribir(client, sub45_a, "1700000001")
    _inscribir(client, senior, "1700000001")
    html = _inscribir(client, sub45_b, "1700000001")
    assert "inscrita en el campeonato Sub 45" in html
    filas = db.execute("SELECT equipo FROM jugadores WHERE cedula = '1700000001' ORDER BY id").fetchall()
    assert [f["equipo"] for f in filas] == ["ALFA", "HALCONES"]


def test_api_cedula_por_torneo(db, client):
    login_admin(client)
    _inscribir(client, _equipo(db, "ALFA"), "1700000001")
    assert client.get("/api/cedula_existe?cedula=1700000001&categoria=Sub 45").json["existe"] is True
    datos = client.get("/api/cedula_existe?cedula=1700000001&categoria=Senior").json
    assert datos["existe"] is False and datos["en_otro_torneo"]["equipo"] == "ALFA"


def test_dorsal_unico_por_equipo(db, client):
    login_admin(client)
    alfa = _equipo(db, "ALFA")
    _inscribir(client, alfa, "1700000001", dorsal="7")
    assert "ya lo usa" in _inscribir(client, alfa, "1700000002", dorsal="07")
    assert "ya lo usa" not in _inscribir(client, alfa, "1700000003", dorsal="8")
    # Otro equipo puede repetir el número.
    assert "ya lo usa" not in _inscribir(client, _equipo(db, "BETA"), "1700000004", dorsal="7")

    jugador = db.execute("SELECT id FROM jugadores WHERE cedula = '1700000003'").fetchone()["id"]
    client.post(f"/jugador/{jugador}/actualizar", data={"nombres": "Juan", "numero_camiseta": "7"})
    assert db.execute("SELECT numero_camiseta FROM jugadores WHERE id = ?", (jugador,)).fetchone()[0] == "8"


def _jugador_calificado(db, client):
    alfa = _equipo(db, "ALFA")
    db.execute("UPDATE equipos SET usuario = 'alfa', clave = '1234' WHERE id = ?", (alfa,))
    db.commit()
    login_admin(client)
    _inscribir(client, alfa, "1700000001")
    jugador = db.execute("SELECT id FROM jugadores").fetchone()["id"]
    db.execute("UPDATE jugadores SET calificado = 1, carnet_impreso = 1 WHERE id = ?", (jugador,))
    db.commit()
    login(client, "alfa", "1234")
    return alfa, jugador


def test_solicitud_de_reemplazo(db, client):
    alfa, jugador = _jugador_calificado(db, client)
    assert "Solicitud de reemplazo" in client.get(f"/equipo/{alfa}").get_data(as_text=True)
    html = client.post(f"/jugador/{jugador}/solicitar_reemplazo", follow_redirects=True).get_data(as_text=True)
    assert "Su solicitud ha sido enviada" in html
    assert db.execute("SELECT reemplazo_solicitado FROM jugadores").fetchone()[0] == 1


def test_reemplazo_bloqueado_si_ya_jugo(db, client):
    alfa, jugador = _jugador_calificado(db, client)
    db.execute("INSERT INTO vocalia_asistencia (partido_id, jugador_id, participo) VALUES (1, ?, 1)", (jugador,))
    db.commit()
    assert "Ya jugó" in client.get(f"/equipo/{alfa}").get_data(as_text=True)
    html = client.post(f"/jugador/{jugador}/solicitar_reemplazo", follow_redirects=True).get_data(as_text=True)
    assert "ya disput" in html
    assert db.execute("SELECT reemplazo_solicitado FROM jugadores").fetchone()[0] == 0


def test_fecha_de_inscripcion_en_hora_de_ecuador(db, client):
    login_admin(client)
    alfa = _equipo(db, "ALFA")
    _inscribir(client, alfa, "1700000001")
    guardada = datetime.strptime(db.execute("SELECT fecha_registro FROM jugadores").fetchone()[0], "%Y-%m-%d %H:%M")
    quito = datetime.now(timezone(timedelta(hours=-5))).replace(tzinfo=None)
    assert abs((guardada - quito).total_seconds()) < 120
    assert guardada.strftime("%d/%m/%Y %H:%M") in client.get(f"/equipo/{alfa}").get_data(as_text=True)
    assert abs((ahora_ecuador() - quito).total_seconds()) < 5


def test_volver_a_solo_acepta_rutas_internas(db, client):
    login(client, "tecnica", "t")
    r = client.post("/tecnica/jornada/agregar", data={"numero": "x", "next": "https://malicioso.com"})
    assert r.headers["Location"].startswith("/tecnica")
    r = client.post("/tecnica/jornada/agregar", data={"numero": "x", "next": "/tecnica?categoria=Senior"})
    assert r.headers["Location"] == "/tecnica?categoria=Senior"


def test_nombre_corto():
    assert nombre_corto("PÉREZ GÓMEZ", "JUAN CARLOS") == "PÉREZ J."


def test_migracion_desde_esquema_viejo(app):
    """Base con el esquema anterior (cédula UNIQUE global): se respalda, se migra
    y luego permite la misma cédula en otro campeonato."""
    ruta = os.path.join(DATA_DIR, "liga.db")
    conn = sqlite3.connect(ruta)
    conn.execute("DROP TABLE jugadores")
    conn.execute("DROP TABLE migraciones")
    conn.execute("""CREATE TABLE jugadores (id INTEGER PRIMARY KEY AUTOINCREMENT, cedula TEXT NOT NULL UNIQUE,
        nombres TEXT NOT NULL, apellidos TEXT NOT NULL, fecha_nacimiento TEXT, equipo TEXT NOT NULL,
        categoria TEXT NOT NULL, subcategoria TEXT NOT NULL DEFAULT 'Sub 45', numero_camiseta TEXT, foto TEXT,
        foto_confirmada INTEGER NOT NULL DEFAULT 0, cedula_frontal TEXT, cedula_reverso TEXT,
        calificado INTEGER NOT NULL DEFAULT 0, fecha_registro TEXT NOT NULL)""")
    conn.execute("INSERT INTO jugadores (id, cedula, nombres, apellidos, equipo, categoria, fecha_registro) "
                 "VALUES (40, '1700000001', 'A', 'B', 'ALFA', 'Sub 45', '2026-01-01 15:00')")
    conn.execute("DELETE FROM jugadores WHERE id = 40")  # el contador AUTOINCREMENT queda en 40
    conn.execute("INSERT INTO jugadores (id, cedula, nombres, apellidos, equipo, categoria, fecha_registro) "
                 "VALUES (5, '1700000001', 'A', 'B', 'ALFA', 'Sub 45', '2026-01-01 15:00')")
    conn.commit()
    conn.close()

    from app import create_app
    create_app({"TESTING": True})

    backups = os.listdir(os.path.join(DATA_DIR, "backups"))
    assert any(n.startswith("liga-pre-migracion-") for n in backups)
    conn = sqlite3.connect(ruta)
    conn.execute("INSERT INTO jugadores (cedula, nombres, apellidos, equipo, categoria, fecha_registro) "
                 "VALUES ('1700000001', 'A', 'B', 'HALCONES', 'Senior', '2026-01-01 10:00')")
    nuevo_id = conn.execute("SELECT MAX(id) FROM jugadores").fetchone()[0]
    assert nuevo_id == 41  # no reutiliza ids de jugadores eliminados
    try:
        conn.execute("INSERT INTO jugadores (cedula, nombres, apellidos, equipo, categoria, fecha_registro) "
                     "VALUES ('1700000001', 'A', 'B', 'BETA', 'Sub 45', '2026-01-01 10:00')")
        assert False, "debió fallar por el índice único (cedula, categoria)"
    except sqlite3.IntegrityError:
        pass
    conn.close()
