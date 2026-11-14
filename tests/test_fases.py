"""Fases de campeonato, Ajuste de Puntos, "Mis Estadísticas" y edición de cédula."""
import os
import re
import sqlite3

from app.services.estadisticas import _calcular_goleadores, _calcular_tabla_posiciones
from app.services.fases import fase_seleccionada
from tests.conftest import DATA_DIR, login, login_admin

def _texto(respuesta):
    """HTML con los mensajes flash legibles (base.html los escapa con tojson)."""
    html = respuesta.get_data(as_text=True)
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), html)


EQUIPOS = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"]


def _torneo(db, equipos=EQUIPOS, categoria="Senior", division="Máxima"):
    """Torneo con un jugador por equipo y una jornada regular por pareja, en la
    que gana el de menor índice (A1 queda 1.º, A10 último)."""
    db.execute("DELETE FROM equipos")
    if division:
        db.execute("INSERT INTO divisiones (categoria, nombre) VALUES (?, ?)", (categoria, division))
    jugadores = {}
    for i, nombre in enumerate(equipos):
        db.execute("INSERT INTO equipos (nombre, categoria, division) VALUES (?, ?, ?)", (nombre, categoria, division))
        jugadores[nombre] = db.execute(
            "INSERT INTO jugadores (cedula, nombres, apellidos, fecha_nacimiento, equipo, categoria, division, "
            "numero_camiseta, fecha_registro) VALUES (?, 'N', ?, '1975-01-01', ?, ?, ?, ?, '2026-01-01 10:00')",
            (f"17{i:08d}", nombre, nombre, categoria, division, str(i + 1)),
        ).lastrowid
    numero = 0
    for i in range(len(equipos)):
        for j in range(i + 1, len(equipos)):
            numero += 1
            jornada = db.execute(
                "INSERT INTO jornadas (numero, categoria, division) VALUES (?, ?, ?)", (numero, categoria, division)
            ).lastrowid
            partido = db.execute(
                "INSERT INTO partidos (jornada_id, equipo_local, equipo_visitante, jugado) VALUES (?, ?, ?, 1)",
                (jornada, equipos[i], equipos[j]),
            ).lastrowid
            db.execute("INSERT INTO goles (jugador_id, partido_id, cantidad, fecha) VALUES (?, ?, 1, '2026-01-01')",
                       (jugadores[equipos[i]], partido))
    db.commit()
    return jugadores, numero


def _configurar(client, categoria="Senior", division="Máxima", final="6", descenso="1", n_descenso="", finales="4"):
    login_admin(client)
    client.post("/categorias/config_fases", data={
        "categoria": categoria, "division": division, "cupos_liguilla_final": final,
        "tiene_liguilla_descenso": descenso, "cupos_liguilla_descenso": n_descenso, "cupos_finales": finales,
    })


def _generar_desde_regular(client, db, categoria="Senior", division="Máxima"):
    """Envía la propuesta que muestra la Comisión Técnica tal cual."""
    login(client, "tecnica", "t")
    html = client.get(f"/tecnica?categoria={categoria}&division={division}").get_data(as_text=True)
    assert "Generar siguiente fase" in html
    regular, _ = fase_seleccionada(db, categoria, division, "regular")
    tabla = _calcular_tabla_posiciones(db, categoria, division, regular)
    from app.services.fases import config_fases, propuesta_de_clasificacion
    propuesta = propuesta_de_clasificacion(tabla, "regular", config_fases(db, categoria, division))
    data = {"categoria": categoria, "division": division, "fase": "regular",
            "equipo": [f["equipo"] for f in tabla], "destino": [propuesta[f["equipo"]] for f in tabla]}
    return client.post("/tecnica/fases/generar", data=data, follow_redirects=True)


def _equipos_de(db, tipo):
    fila = db.execute("SELECT id FROM fases WHERE tipo = ?", (tipo,)).fetchone()
    return fila["id"], [f["equipo"] for f in db.execute(
        "SELECT equipo FROM fase_equipos WHERE fase_id = ? ORDER BY posicion_origen", (fila["id"],)).fetchall()]


def test_maxima_6_a_liguilla_y_4_a_no_descenso_sin_tocar_la_regular(db, client):
    jugadores, ultima = _torneo(db)
    regular_antes = _calcular_tabla_posiciones(db, "Senior", "Máxima")
    _configurar(client)
    html = _texto(_generar_desde_regular(client, db))
    assert "Liguilla Final (6 equipos)" in html and "Liguilla de No Descenso (4 equipos)" in html

    final_id, final = _equipos_de(db, "liguilla_final")
    descenso_id, descenso = _equipos_de(db, "liguilla_descenso")
    assert final == EQUIPOS[:6] and descenso == EQUIPOS[6:]

    # La Fase Regular queda intacta y la liguilla arranca en cero.
    assert _calcular_tabla_posiciones(db, "Senior", "Máxima") == regular_antes
    fase_final, _ = fase_seleccionada(db, "Senior", "Máxima", str(final_id))
    tabla_final = _calcular_tabla_posiciones(db, "Senior", "Máxima", fase_final)
    assert [f["equipo"] for f in tabla_final] and all(f["pts"] == 0 and f["pj"] == 0 for f in tabla_final)
    assert {f["equipo"] for f in tabla_final} == set(EQUIPOS[:6])

    # Jornada de liguilla: la numeración continúa la del campeonato.
    r = client.post("/tecnica/jornada/agregar", data={
        "categoria": "Senior", "division": "Máxima", "fase": str(final_id), "numero": "1",
        "equipo_local": "A6", "equipo_visitante": "A1", "hora": "", "fecha_partido": ""}, follow_redirects=True)
    assert "continúan la numeración" in _texto(r)
    r = client.post("/tecnica/jornada/agregar", data={
        "categoria": "Senior", "division": "Máxima", "fase": str(final_id), "numero": str(ultima + 1),
        "equipo_local": "A6", "equipo_visitante": "A7", "hora": "", "fecha_partido": ""}, follow_redirects=True)
    assert "clasificados a esa fase" in _texto(r)  # A7 juega No Descenso
    client.post("/tecnica/jornada/agregar", data={
        "categoria": "Senior", "division": "Máxima", "fase": str(final_id), "numero": str(ultima + 1),
        "equipo_local": "A6", "equipo_visitante": "A1", "hora": "", "fecha_partido": ""})
    partido = db.execute(
        "SELECT p.id FROM partidos p JOIN jornadas jo ON jo.id = p.jornada_id WHERE jo.fase_id = ?", (final_id,)
    ).fetchone()["id"]
    for _ in range(3):
        db.execute("INSERT INTO goles (jugador_id, partido_id, cantidad, fecha) VALUES (?, ?, 1, '2026-02-01')",
                   (jugadores["A6"], partido))
    db.commit()
    client.post(f"/tecnica/partido/{partido}/aprobar")

    tabla_final = _calcular_tabla_posiciones(db, "Senior", "Máxima", fase_final)
    assert tabla_final[0]["equipo"] == "A6" and tabla_final[0]["pts"] == 3 and tabla_final[0]["pj"] == 1
    assert _calcular_tabla_posiciones(db, "Senior", "Máxima") == regular_antes

    # Goles acumulados entre fases: A6 tenía 4 en la regular (ganó a A7..A10) + 3.
    goles_a6 = {g["equipo"]: g["goles"] for g in _calcular_goleadores(db, "Senior", "Máxima", limite=0)}["A6"]
    assert goles_a6 == 7

    # Pestañas públicas.
    publico = client.get(f"/publico/tabla?categoria=Senior&division=Máxima&fase={final_id}").get_data(as_text=True)
    assert "Liguilla Final" in publico and "Fase Regular" in publico
    calendario = client.get(f"/publico/calendario?categoria=Senior&division=Máxima&fase={descenso_id}")
    assert calendario.status_code == 200


def test_primera_6_a_liguilla_y_2_eliminados(db, client):
    _torneo(db, EQUIPOS[:8], division="Primera")
    _configurar(client, division="Primera", descenso="0")
    _generar_desde_regular(client, db, division="Primera")
    _, final = _equipos_de(db, "liguilla_final")
    assert final == EQUIPOS[:6]
    assert db.execute("SELECT COUNT(*) c FROM fases WHERE tipo = 'liguilla_descenso'").fetchone()["c"] == 0


def test_sub45_liguilla_de_4_y_finales_desde_la_liguilla(db, client):
    _torneo(db, EQUIPOS[:7], categoria="Sub 45", division="")
    _configurar(client, categoria="Sub 45", division="", final="4", descenso="0", finales="2")
    _generar_desde_regular(client, db, categoria="Sub 45", division="")
    final_id, final = _equipos_de(db, "liguilla_final")
    assert final == EQUIPOS[:4]

    html = client.get(f"/tecnica?categoria=Sub 45&fase={final_id}").get_data(as_text=True)
    assert "Generar siguiente fase" not in html  # todavía no se jugó nada en la liguilla
    jornada = db.execute("INSERT INTO jornadas (numero, categoria, division, fase_id) VALUES (99, 'Sub 45', '', ?)",
                         (final_id,)).lastrowid
    db.execute("INSERT INTO partidos (jornada_id, equipo_local, equipo_visitante, jugado) VALUES (?, 'A1', 'A2', 1)",
               (jornada,))
    db.commit()
    html = client.get(f"/tecnica?categoria=Sub 45&fase={final_id}").get_data(as_text=True)
    assert "Generar siguiente fase desde Liguilla Final" in html
    r = client.post("/tecnica/fases/generar", data={
        "categoria": "Sub 45", "division": "", "fase": str(final_id),
        "equipo": ["A1", "A2", "A3", "A4"], "destino": ["finales", "finales", "", ""]}, follow_redirects=True)
    assert "Finales (2 equipos)" in _texto(r)
    # La liguilla ya tiene una fase derivada: no se puede deshacer.
    r = client.post(f"/tecnica/fases/{final_id}/eliminar", follow_redirects=True)
    assert "No se puede eliminar" in _texto(r)


def test_ajuste_de_puntos_por_fase_positivo_y_negativo(db, client):
    _torneo(db, EQUIPOS[:4], categoria="Sub 45", division="")
    _configurar(client, categoria="Sub 45", division="", final="2", descenso="1")
    _generar_desde_regular(client, db, categoria="Sub 45", division="")
    final_id, _ = _equipos_de(db, "liguilla_final")
    regular, _ = fase_seleccionada(db, "Sub 45", "", "regular")
    pts_a1_regular = _calcular_tabla_posiciones(db, "Sub 45", "", regular)[0]["pts"]

    login(client, "tecnica", "t")
    client.post("/tecnica/ajuste_puntos", data={"categoria": "Sub 45", "division": "", "fase": "regular",
                                                "equipo": "A1", "puntos": "-3", "motivo": "Agresión"})
    client.post("/tecnica/ajuste_puntos", data={"categoria": "Sub 45", "division": "", "fase": str(final_id),
                                                "equipo": "A1", "puntos": "2", "motivo": "Bonificación 1.er lugar"})
    r = client.post("/tecnica/ajuste_puntos", data={"categoria": "Sub 45", "division": "", "fase": str(final_id),
                                                    "equipo": "A4", "puntos": "1", "motivo": "x"},
                    follow_redirects=True)
    assert "Selecciona un equipo que participe" in _texto(r)  # A4 no está en la Liguilla Final

    tabla_regular = {f["equipo"]: f for f in _calcular_tabla_posiciones(db, "Sub 45", "", regular)}
    assert tabla_regular["A1"]["pts"] == pts_a1_regular - 3 and tabla_regular["A1"]["pts_ajuste"] == -3
    fase_final, _ = fase_seleccionada(db, "Sub 45", "", str(final_id))
    tabla_final = {f["equipo"]: f for f in _calcular_tabla_posiciones(db, "Sub 45", "", fase_final)}
    assert tabla_final["A1"]["pts"] == 2 and tabla_final["A1"]["pts_ajuste"] == 2
    html = client.get(f"/tecnica?categoria=Sub 45&fase={final_id}").get_data(as_text=True)
    assert "Bonificación: +2 pts" in html and "Ajuste de Puntos" in html


def test_migracion_deduccion_vieja_pasa_a_ajuste_negativo(app):
    ruta = os.path.join(DATA_DIR, "liga.db")
    conn = sqlite3.connect(ruta)
    conn.execute("DELETE FROM migraciones WHERE nombre = '2026_11_fases_y_ajuste_de_puntos'")
    conn.execute("CREATE TABLE ps_vieja AS SELECT id, equipo, categoria, division, puntos_descontar, motivo, fecha "
                 "FROM puntos_sancion")
    conn.execute("DROP TABLE puntos_sancion")
    conn.execute("ALTER TABLE ps_vieja RENAME TO puntos_sancion")
    conn.execute("INSERT INTO puntos_sancion (equipo, categoria, division, puntos_descontar, motivo, fecha) "
                 "VALUES ('ALFA', 'Sub 45', '', 3, 'Multa', '2026-09-01 10:00')")
    conn.commit()
    conn.close()

    from app import create_app
    create_app({"TESTING": True})
    conn = sqlite3.connect(ruta)
    fila = conn.execute("SELECT puntos_descontar, puntos_ajuste, fase_id FROM puntos_sancion").fetchone()
    conn.close()
    assert fila == (3, -3, None)


# ---------- Mis Estadísticas ----------

def test_mis_estadisticas_coinciden_con_goleadores_y_acumulacion(db, client):
    jugadores, _ = _torneo(db, ["ALFA", "BETA"], categoria="Sub 45", division="")
    alfa = db.execute("SELECT id FROM equipos WHERE nombre = 'ALFA'").fetchone()["id"]
    beta = db.execute("SELECT id FROM equipos WHERE nombre = 'BETA'").fetchone()["id"]
    db.execute("UPDATE equipos SET usuario = 'alfa', clave = '1234' WHERE id = ?", (alfa,))
    partido = db.execute("SELECT id FROM partidos").fetchone()["id"]
    for _ in range(6):
        db.execute("INSERT INTO goles (jugador_id, partido_id, cantidad, fecha) VALUES (?, ?, 1, '2026-01-01')",
                   (jugadores["ALFA"], partido))
    for n in range(3):
        db.execute("INSERT INTO tarjetas (jugador_id, partido_id, tipo, fecha) VALUES (?, ?, 'amarilla', '2026')",
                   (jugadores["ALFA"], 100 + n))
    # Doble amarilla en un partido (no cuentan como amarillas) + su roja.
    for tipo in ("amarilla", "amarilla", "roja"):
        db.execute("INSERT INTO tarjetas (jugador_id, partido_id, tipo, fecha) VALUES (?, 200, ?, '2026')",
                   (jugadores["ALFA"], tipo))
    db.commit()

    goleadores = {g["equipo"]: g["goles"] for g in _calcular_goleadores(db, "Sub 45", "")}
    assert goleadores["ALFA"] == 7

    login(client, "sanciones", "s")
    acumulacion = client.get("/sanciones/acumulacion?categoria=Sub 45").get_data(as_text=True)
    assert ">3</td>" in acumulacion and ">1</td>" in acumulacion

    login(client, "alfa", "1234")
    assert "Mis Estadísticas" in client.get(f"/equipo/{alfa}").get_data(as_text=True)
    respuesta = client.get(f"/equipo/{alfa}/estadisticas")
    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "<strong>7</strong>" in html
    assert 'font-weight:600;">3</td>' in html and 'font-weight:600;">1</td>' in html

    # Privado: otro equipo, el público y otros roles no entran; el admin sí.
    assert client.get(f"/equipo/{beta}/estadisticas").status_code == 302
    client.get("/logout")
    assert client.get(f"/equipo/{alfa}/estadisticas").status_code == 302
    login(client, "tecnica", "t")
    assert client.get(f"/equipo/{alfa}/estadisticas").status_code == 302
    login_admin(client)
    assert client.get(f"/equipo/{beta}/estadisticas").status_code == 200


def test_goleadores_publicos_muestran_equipo_en_movil(db, client):
    _torneo(db, ["ALFA", "BETA"], categoria="Sub 45", division="")
    html = client.get("/publico/tabla?categoria=Sub 45").get_data(as_text=True)
    assert '<span class="sub-movil">ALFA</span>' in html


# ---------- Cédula editable según estado ----------

def _jugador(db, client, calificado=0, reemplazo=0):
    _torneo(db, ["ALFA", "BETA"], categoria="Sub 45", division="")
    jugador = db.execute("SELECT id FROM jugadores WHERE equipo = 'ALFA'").fetchone()["id"]
    db.execute("UPDATE jugadores SET calificado = ?, reemplazo_solicitado = ?, carnet_impreso = 1 WHERE id = ?",
               (calificado, reemplazo, jugador))
    alfa = db.execute("SELECT id FROM equipos WHERE nombre = 'ALFA'").fetchone()["id"]
    db.execute("UPDATE equipos SET usuario = 'alfa', clave = '1234' WHERE id = ?", (alfa,))
    db.commit()
    login(client, "alfa", "1234")
    return jugador


def _cedula(db, jugador):
    return db.execute("SELECT cedula FROM jugadores WHERE id = ?", (jugador,)).fetchone()["cedula"]


def test_cedula_editable_si_pendiente_y_sin_colisiones(db, client):
    jugador = _jugador(db, client)
    assert '<input type="text" name="cedula"' in client.get(f"/jugador/{jugador}").get_data(as_text=True)
    otra = db.execute("SELECT cedula FROM jugadores WHERE equipo = 'BETA'").fetchone()["cedula"]
    html = _texto(client.post(f"/jugador/{jugador}/actualizar", data={"cedula": otra, "nombres": "N"},
                              follow_redirects=True))
    assert "ya está inscrita" in html and _cedula(db, jugador) != otra
    client.post(f"/jugador/{jugador}/actualizar", data={"cedula": "1799999999", "nombres": "N"})
    assert _cedula(db, jugador) == "1799999999"


def test_cedula_bloqueada_si_calificado(db, client):
    jugador = _jugador(db, client, calificado=1)
    original = _cedula(db, jugador)
    assert '<input type="text" name="cedula"' not in client.get(f"/jugador/{jugador}").get_data(as_text=True)
    client.post(f"/jugador/{jugador}/actualizar", data={"cedula": "1799999999", "nombres": "N"})
    assert _cedula(db, jugador) == original
    # Ni siquiera el admin puede cambiarla sin una solicitud de reemplazo.
    login_admin(client)
    html = _texto(client.post(f"/jugador/{jugador}/actualizar", data={"cedula": "1799999999", "nombres": "N"},
                              follow_redirects=True))
    assert "está bloqueada" in html and _cedula(db, jugador) == original


def test_reemplazo_permite_cambiar_cedula_y_vuelve_a_pendiente(db, client):
    jugador = _jugador(db, client, calificado=1, reemplazo=1)
    assert '<input type="text" name="cedula"' in client.get(f"/jugador/{jugador}").get_data(as_text=True)
    html = _texto(client.post(f"/jugador/{jugador}/actualizar", data={
        "cedula": "1799999999", "nombres": "Pedro", "apellidos": "Nuevo", "numero_camiseta": "1"},
        follow_redirects=True))
    assert "Reemplazo registrado" in html
    fila = db.execute("SELECT cedula, nombres, calificado, reemplazo_solicitado, carnet_impreso FROM jugadores "
                      "WHERE id = ?", (jugador,)).fetchone()
    assert tuple(fila) == ("1799999999", "PEDRO", 0, 0, 0)


def test_calificacion_puede_abrir_la_ficha(db, client):
    jugador = _jugador(db, client)
    login(client, "comision", "c")
    assert client.get(f"/jugador/{jugador}").status_code == 200


def test_migracion_carga_cupos_iniciales_sin_pisar_los_manuales(app):
    ruta = os.path.join(DATA_DIR, "liga.db")
    conn = sqlite3.connect(ruta)
    conn.execute("DELETE FROM migraciones WHERE nombre = '2026_11_cupos_de_fases_iniciales'")
    conn.execute("DELETE FROM config_fases")
    conn.execute("INSERT INTO divisiones (categoria, nombre) VALUES ('Senior', 'MÁXIMA'), ('Senior', 'Primera')")
    # Primera ya configurada a mano: se respeta.
    conn.execute("INSERT INTO config_fases (categoria, division, cupos_liguilla_final, tiene_liguilla_descenso) "
                 "VALUES ('Senior', 'Primera', 8, 0)")
    conn.commit()
    conn.close()

    from app import create_app
    create_app({"TESTING": True})
    conn = sqlite3.connect(ruta)
    filas = {
        (f[0], f[1]): f[2:] for f in conn.execute(
            "SELECT categoria, division, cupos_liguilla_final, tiene_liguilla_descenso, cupos_liguilla_descenso, "
            "cupos_finales FROM config_fases")
    }
    conn.close()
    assert filas == {
        ("Senior", "MÁXIMA"): (6, 1, None, 4),
        ("Senior", "Primera"): (8, 0, None, None),
        ("Sub 45", ""): (4, 0, None, None),
    }
