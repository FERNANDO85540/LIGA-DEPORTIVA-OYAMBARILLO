"""Tabla de posiciones y goleadores."""
from config import CATEGORIA_ACTIVA


def _calcular_tabla_posiciones(db, categoria=CATEGORIA_ACTIVA, division=""):
    equipos = db.execute(
        "SELECT nombre FROM equipos WHERE categoria = ? AND division = ? ORDER BY nombre", (categoria, division)
    ).fetchall()
    
    tabla = {
        e["nombre"]: {"equipo": e["nombre"], "pj": 0, "g": 0, "e": 0, "p": 0, "gf": 0, "gc": 0, "pts": 0, "pts_sancion": 0}
        for e in equipos
    }

    # 1. Procesar Partidos
    partidos = db.execute(
        """SELECT p.* FROM partidos p JOIN jornadas jo ON jo.id = p.jornada_id
           WHERE jo.categoria = ? AND jo.division = ? AND p.jugado = 1""",
        (categoria, division),
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

    # 2. Descontar Puntos de Sanción
    sanciones = db.execute("SELECT equipo, SUM(puntos_descontar) as perdidos FROM puntos_sancion WHERE categoria = ? AND division = ? GROUP BY equipo", (categoria, division)).fetchall()
    for s in sanciones:
        if s["equipo"] in tabla:
            tabla[s["equipo"]]["pts"] -= s["perdidos"]
            tabla[s["equipo"]]["pts_sancion"] = s["perdidos"]

    filas = list(tabla.values())
    for f in filas:
        f["dg"] = f["gf"] - f["gc"]
        
    filas.sort(key=lambda f: (-f["pts"], -f["dg"], -f["gf"]))
    return filas


def _calcular_goleadores(db, categoria=CATEGORIA_ACTIVA, division="", limite=10):
    return db.execute(
        """
        SELECT j.id, j.nombres, j.apellidos, j.equipo, SUM(g.cantidad) AS goles
        FROM goles g
        JOIN jugadores j ON j.id = g.jugador_id
        WHERE j.categoria = ? AND j.division = ?
        GROUP BY j.id, j.nombres, j.apellidos, j.equipo
        ORDER BY goles DESC
        LIMIT ?
        """,
        (categoria, division, limite),
    ).fetchall()
