from app.services.sanciones import _generar_sanciones_por_acumulacion, _jugador_suspendido, estado_sancion
from tests.conftest import login, login_admin


def _liga(db, jornadas=4, descansa_beta_en=None):
    """Sub 45 con ALFA vs BETA en cada jornada (fechas 2026-09-0N) y un jugador por equipo."""
    db.execute("DELETE FROM equipos")
    for nombre in ("ALFA", "BETA"):
        db.execute("INSERT INTO equipos (nombre, categoria, division) VALUES (?, 'Sub 45', '')", (nombre,))
    ids = {}
    for equipo, cedula in (("ALFA", "1000000001"), ("BETA", "1000000002")):
        cur = db.execute(
            "INSERT INTO jugadores (cedula, nombres, apellidos, fecha_nacimiento, equipo, categoria, division, "
            "numero_camiseta, fecha_registro) VALUES (?, 'N', ?, '1975-01-01', ?, 'Sub 45', '', '1', '2026-01-01 10:00')",
            (cedula, equipo, equipo),
        )
        ids[equipo] = cur.lastrowid
    partidos = {}
    for n in range(1, jornadas + 1):
        jornada_id = db.execute(
            "INSERT INTO jornadas (numero, categoria, division) VALUES (?, 'Sub 45', '')", (n,)
        ).lastrowid
        if n == descansa_beta_en:
            db.execute("INSERT INTO descansos (jornada_id, equipo) VALUES (?, 'BETA')", (jornada_id,))
            continue
        partidos[n] = db.execute(
            "INSERT INTO partidos (jornada_id, equipo_local, equipo_visitante, fecha) VALUES (?, 'ALFA', 'BETA', ?)",
            (jornada_id, f"2026-09-0{n}"),
        ).lastrowid
    db.commit()
    return ids, partidos


def _sancionar(db, jugador_id, partidos, desde_jornada, origen="manual"):
    sid = db.execute(
        "INSERT INTO sanciones (jugador_id, motivo, jornadas_sancionado, jornada_desde_numero, categoria, division, "
        "fecha, origen) VALUES (?, 'Agresión', ?, ?, 'Sub 45', '', '2026-09-01 10:00', ?)",
        (jugador_id, partidos, desde_jornada, origen),
    ).lastrowid
    db.commit()
    return db.execute("SELECT * FROM sanciones WHERE id = ?", (sid,)).fetchone()


def _jugar(db, partido_id):
    db.execute("UPDATE partidos SET jugado = 1 WHERE id = ?", (partido_id,))
    db.commit()


def test_partidos_futuros_no_cuentan_como_cumplidos(db, client):
    ids, partidos = _liga(db)
    sancion = _sancionar(db, ids["BETA"], 2, desde_jornada=2)

    # Hay 4 jornadas programadas pero ninguna jugada: antes salía "cumplida".
    estado = estado_sancion(db, sancion)
    assert estado["activa"] and estado["cumplidos"] == 0 and estado["pendientes"] == 2

    _jugar(db, partidos[2])
    estado = estado_sancion(db, sancion)
    assert estado["activa"] and estado["cumplidos"] == 1
    assert [p["jornada_numero"] for p in estado["proximos"]] == [3]
    assert "BETA" in client.get("/publico/sancionados").get_data(as_text=True)

    _jugar(db, partidos[3])
    assert not estado_sancion(db, sancion)["activa"]
    assert "BETA" not in client.get("/publico/sancionados").get_data(as_text=True)


def test_hoja_de_vocalia_llenada_cuenta_como_jugado(db):
    ids, partidos = _liga(db)
    sancion = _sancionar(db, ids["BETA"], 1, desde_jornada=2)
    db.execute("UPDATE partidos SET hoja_editada = 1 WHERE id = ?", (partidos[2],))
    db.commit()
    assert not estado_sancion(db, sancion)["activa"]


def test_descanso_no_descuenta_suspension(db):
    ids, partidos = _liga(db, descansa_beta_en=2)
    sancion = _sancionar(db, ids["BETA"], 1, desde_jornada=2)
    # Las demás jornadas existen pero no se jugaron; J2 BETA descansó.
    assert estado_sancion(db, sancion)["pendientes"] == 1


def test_vocalia_bloquea_solo_los_partidos_que_corresponden(db):
    ids, partidos = _liga(db)
    _sancionar(db, ids["BETA"], 1, desde_jornada=2)
    jornada = lambda n: db.execute("SELECT * FROM jornadas WHERE numero = ?", (n,)).fetchone()  # noqa: E731
    partido = lambda n: db.execute("SELECT * FROM partidos WHERE id = ?", (partidos[n],)).fetchone()  # noqa: E731

    assert not _jugador_suspendido(db, ids["BETA"], jornada(1), partido(1))
    assert _jugador_suspendido(db, ids["BETA"], jornada(2), partido(2))
    _jugar(db, partidos[2])
    # Al revisar la hoja ya jugada de J2 sigue figurando suspendido...
    assert _jugador_suspendido(db, ids["BETA"], jornada(2), partido(2))
    # ...y en J3 ya puede jugar.
    assert not _jugador_suspendido(db, ids["BETA"], jornada(3), partido(3))


def test_fecha_de_inicio_manual_y_levantar(db, client):
    ids, partidos = _liga(db)
    sancion = _sancionar(db, ids["BETA"], 1, desde_jornada=2)
    _jugar(db, partidos[2])
    assert not estado_sancion(db, sancion)["activa"]

    login(client, "sanciones", "s")
    r = client.post(f"/sanciones/sancion/{sancion['id']}/editar", data={
        "motivo": "Agresión al árbitro", "jornadas_sancionado": "1", "fecha_inicio": "2026-09-03",
        "next": "/sanciones?categoria=Sub+45",
    })
    assert r.status_code == 302 and r.headers["Location"] == "/sanciones?categoria=Sub+45"
    sancion = db.execute("SELECT * FROM sanciones WHERE id = ?", (sancion["id"],)).fetchone()
    assert sancion["motivo"] == "Agresión al árbitro" and sancion["fecha_inicio"] == "2026-09-03"
    # J2 (2026-09-02) queda antes del inicio: vuelve a estar activa.
    assert estado_sancion(db, sancion)["activa"]

    client.post(f"/sanciones/sancion/{sancion['id']}/levantar")
    sancion = db.execute("SELECT * FROM sanciones WHERE id = ?", (sancion["id"],)).fetchone()
    assert sancion["anulada"] == 1 and estado_sancion(db, sancion)["estado"] == "levantada"


def test_editar_rechaza_datos_invalidos(db, client):
    ids, _ = _liga(db)
    sancion = _sancionar(db, ids["BETA"], 2, desde_jornada=2)
    login(client, "sanciones", "s")
    client.post(f"/sanciones/sancion/{sancion['id']}/editar",
                data={"motivo": "", "jornadas_sancionado": "0", "fecha_inicio": "31/12/2026"})
    assert db.execute("SELECT motivo, jornadas_sancionado FROM sanciones").fetchone()["motivo"] == "Agresión"


def _hoja(client, partido_id, equipo, jugador_id, amarillas):
    return client.post(f"/vocalia/partido/{partido_id}/hoja/guardar", data={
        "equipo_nombre": equipo, "todos_ids": [str(jugador_id)], "participo": [str(jugador_id)],
        f"amarillas_{jugador_id}": str(amarillas), f"goles_{jugador_id}": "0",
    })


def test_cinco_amarillas_es_bidireccional(db, client):
    ids, partidos = _liga(db, jornadas=6)
    login(client, "vocalia", "v")
    for n in range(1, 6):
        _hoja(client, partidos[n], "ALFA", ids["ALFA"], 1)
    acumulacion = "SELECT * FROM sanciones WHERE origen = 'acumulacion'"
    filas = db.execute(acumulacion).fetchall()
    assert len(filas) == 1 and filas[0]["jornada_desde_numero"] == 6

    # Vocalía corrige: quita la amarilla de J3 -> quedan 4, se borra la sanción.
    _hoja(client, partidos[3], "ALFA", ids["ALFA"], 0)
    assert db.execute(acumulacion).fetchall() == []

    # Se vuelve a poner: la sanción reaparece en el mismo lugar (orden por jornada, no por id).
    _hoja(client, partidos[3], "ALFA", ids["ALFA"], 1)
    filas = db.execute(acumulacion).fetchall()
    assert len(filas) == 1 and filas[0]["jornada_desde_numero"] == 6


def test_acumulacion_no_se_elimina_a_mano_pero_se_puede_levantar(db, client):
    ids, _ = _liga(db)
    sancion = _sancionar(db, ids["ALFA"], 1, desde_jornada=2, origen="acumulacion")
    login(client, "sanciones", "s")
    client.post(f"/sanciones/sancion/{sancion['id']}/eliminar")
    assert db.execute("SELECT COUNT(*) c FROM sanciones").fetchone()["c"] == 1
    _generar_sanciones_por_acumulacion(db)  # sin amarillas -> la quita la sincronización
    assert db.execute("SELECT COUNT(*) c FROM sanciones").fetchone()["c"] == 0


def test_vocalia_no_marca_participo_a_suspendido(db, client):
    ids, partidos = _liga(db)
    _sancionar(db, ids["BETA"], 1, desde_jornada=2)
    login(client, "vocalia", "v")
    _hoja(client, partidos[2], "BETA", ids["BETA"], 0)
    fila = db.execute("SELECT participo FROM vocalia_asistencia WHERE jugador_id = ?", (ids["BETA"],)).fetchone()
    assert fila["participo"] == 0


def test_tesoreria_oculta(db, client):
    ids, _ = _liga(db)
    _sancionar(db, ids["BETA"], 1, desde_jornada=2)
    login(client, "sanciones", "s")
    html = client.get("/sanciones").get_data(as_text=True)
    assert "Multa" not in html and "Pagada" not in html
    assert "Multa" not in client.get("/sanciones/acumulacion").get_data(as_text=True)


def test_catalogo_conserva_multa_oculta(db, client):
    login(client, "sanciones", "s")
    db.execute("INSERT INTO sanciones_catalogo (articulo, descripcion_motivo, cantidad_fechas_suspension, "
               "aplica_multa, valor_multa_sugerido) VALUES ('76', 'Agresión', 2, 1, 20)")
    db.commit()
    client.post("/sanciones/catalogo/1/editar", data={"articulo": "76", "descripcion_motivo": "Agresión grave",
                                                     "cantidad_fechas_suspension": "3"})
    fila = db.execute("SELECT * FROM sanciones_catalogo").fetchone()
    assert fila["descripcion_motivo"] == "Agresión grave" and fila["aplica_multa"] == 1 and fila["valor_multa_sugerido"] == 20


def test_estado_en_vivo_eliminado(client):
    login_admin(client)
    assert client.post("/tecnica/partido/1/en_vivo/iniciar").status_code == 404
