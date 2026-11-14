"""Tabla de posiciones (por fase), goleadores y tarjetas por jugador.

Goleadores y tarjetas son la ÚNICA fuente de verdad para la tabla pública de
goleadores, el módulo de Acumulación de Tarjetas (Penas) y "Mis Estadísticas"
de cada equipo: todos llaman a _goles_por_jugador / _tarjetas_por_jugador.
No dependen de la fase: se acumulan durante todo el campeonato.
"""
from config import CATEGORIA_ACTIVA
from app.services.fases import FASE_REGULAR, equipos_de_fase, filtro_jornadas_fase


def _calcular_tabla_posiciones(db, categoria=CATEGORIA_ACTIVA, division="", fase=None):
    """Tabla de una fase (por defecto, la Fase Regular). Cada fase arranca de
    cero: solo cuenta sus propias jornadas y sus propios ajustes de puntos."""
    fase = fase or FASE_REGULAR
    tabla = {
        nombre: {"equipo": nombre, "pj": 0, "g": 0, "e": 0, "p": 0, "gf": 0, "gc": 0, "pts": 0, "pts_ajuste": 0}
        for nombre in equipos_de_fase(db, categoria, division, fase)
    }

    # 1. Procesar Partidos
    filtro, params_fase = filtro_jornadas_fase(fase)
    partidos = db.execute(
        f"""SELECT p.* FROM partidos p JOIN jornadas jo ON jo.id = p.jornada_id
           WHERE jo.categoria = ? AND jo.division = ? AND p.jugado = 1 AND {filtro}""",
        (categoria, division, *params_fase),
    ).fetchall()

    for p in partidos:
        local, visitante = p["equipo_local"], p["equipo_visitante"]
        if local not in tabla or visitante not in tabla:
            continue

        tabla[local]["pj"] += 1
        tabla[visitante]["pj"] += 1

        # ¿El partido se resolvió por escritorio (Comisión Técnica)?
        if p["ganador_escritorio"]:
            if p["ganador_escritorio"] == local:
                gl, gv = 2, 0
            else:
                gl, gv = 0, 2
        else:
            # Si fue partido normal, sumamos los goles que registró Vocalía
            gl_rows = db.execute("SELECT SUM(cantidad) AS g FROM goles g JOIN jugadores j ON j.id = g.jugador_id WHERE g.partido_id = ? AND j.equipo = ?", (p["id"], local)).fetchone()
            gv_rows = db.execute("SELECT SUM(cantidad) AS g FROM goles g JOIN jugadores j ON j.id = g.jugador_id WHERE g.partido_id = ? AND j.equipo = ?", (p["id"], visitante)).fetchone()
            gl = gl_rows["g"] if gl_rows and gl_rows["g"] is not None else 0
            gv = gv_rows["g"] if gv_rows and gv_rows["g"] is not None else 0

        tabla[local]["gf"] += gl
        tabla[local]["gc"] += gv
        tabla[visitante]["gf"] += gv
        tabla[visitante]["gc"] += gl

        if gl > gv:
            tabla[local]["g"] += 1
            tabla[local]["pts"] += 3
            tabla[visitante]["p"] += 1
        elif gl < gv:
            tabla[visitante]["g"] += 1
            tabla[visitante]["pts"] += 3
            tabla[local]["p"] += 1
        else:
            tabla[local]["e"] += 1
            tabla[visitante]["e"] += 1
            tabla[local]["pts"] += 1
            tabla[visitante]["pts"] += 1

    # 2. Ajuste de Puntos de ESTA fase (negativo = sanción, positivo = bonificación)
    for a in _ajustes_por_equipo(db, categoria, division, fase):
        if a["equipo"] in tabla:
            tabla[a["equipo"]]["pts"] += a["ajuste"]
            tabla[a["equipo"]]["pts_ajuste"] = a["ajuste"]

    filas = list(tabla.values())
    for f in filas:
        f["dg"] = f["gf"] - f["gc"]

    filas.sort(key=lambda f: (-f["pts"], -f["dg"], -f["gf"]))
    return filas


def _ajustes_por_equipo(db, categoria, division, fase):
    if fase["id"] is None:
        filtro, params = "fase_id IS NULL", ()
    else:
        filtro, params = "fase_id = ?", (fase["id"],)
    filas = db.execute(
        f"""SELECT equipo, SUM(COALESCE(puntos_ajuste, -puntos_descontar)) AS ajuste FROM puntos_sancion
            WHERE categoria = ? AND division = ? AND {filtro} GROUP BY equipo""",
        (categoria, division or "", *params),
    ).fetchall()
    return [{"equipo": f["equipo"], "ajuste": f["ajuste"] or 0} for f in filas]


def _ajustes_de_fase(db, categoria, division, fase):
    """Registros de Ajuste de Puntos de una fase (para listarlos y deshacerlos)."""
    if fase["id"] is None:
        filtro, params = "fase_id IS NULL", ()
    else:
        filtro, params = "fase_id = ?", (fase["id"],)
    filas = db.execute(
        f"SELECT * FROM puntos_sancion WHERE categoria = ? AND division = ? AND {filtro} ORDER BY id DESC",
        (categoria, division or "", *params),
    ).fetchall()
    resultado = []
    for f in filas:
        d = dict(f)
        d["ajuste"] = f["puntos_ajuste"] if f["puntos_ajuste"] is not None else -(f["puntos_descontar"] or 0)
        resultado.append(d)
    return resultado


def _goles_por_jugador(db, categoria=CATEGORIA_ACTIVA, division="", equipo=None):
    """Goles acumulados (todas las fases) por jugador del campeonato. Fuente
    única de la tabla de Goleadores y de "Mis Estadísticas"."""
    filtro_equipo, params = ("AND j.equipo = ?", (equipo,)) if equipo is not None else ("", ())
    return db.execute(
        f"""
        SELECT j.id, j.nombres, j.apellidos, j.equipo, SUM(g.cantidad) AS goles
        FROM goles g
        JOIN jugadores j ON j.id = g.jugador_id
        WHERE j.categoria = ? AND j.division = ? {filtro_equipo}
        GROUP BY j.id, j.nombres, j.apellidos, j.equipo
        ORDER BY goles DESC, j.apellidos, j.nombres
        """,
        (categoria, division or "", *params),
    ).fetchall()


def _calcular_goleadores(db, categoria=CATEGORIA_ACTIVA, division="", limite=10):
    filas = _goles_por_jugador(db, categoria, division)
    return filas[:limite] if limite else filas


def _tarjetas_por_jugador(db, jugador_ids):
    """Tarjetas acumuladas (todas las fases) por jugador, con las mismas reglas
    del módulo de Acumulación de Tarjetas de Penas: las dos amarillas de una
    expulsión por doble amarilla en el mismo partido no cuentan como válidas.

    Devuelve {jugador_id: {"amarillas": n, "rojas": n, "multas": $}}."""
    from app.services.sanciones import _amarillas_validas_agrupadas

    ids = set(jugador_ids)
    resultado = {jid: {"amarillas": 0, "rojas": 0, "multas": 0} for jid in ids}
    for jid, tarjetas in _amarillas_validas_agrupadas(db).items():
        if jid in ids:
            resultado[jid]["amarillas"] = len(tarjetas)
    for t in db.execute("SELECT jugador_id, tipo, valor_multa FROM tarjetas").fetchall():
        if t["jugador_id"] in ids:
            resultado[t["jugador_id"]]["multas"] += t["valor_multa"] or 0
            if t["tipo"] == "roja":
                resultado[t["jugador_id"]]["rojas"] += 1
    return resultado
