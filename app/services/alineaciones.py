"""Alineaciones (formaciones en cancha) que arma cada equipo por partido."""
from datetime import datetime

from config import USANDO_POSTGRES


# Formaciones disponibles para la alineación: cada slot tiene una posición en
# la cancha (top/left en % para ubicarlo con CSS) y una etiqueta corta.
FORMACIONES = {
    "4-3-3": [
        {"code": "GK", "label": "POR", "top": 90, "left": 50},
        {"code": "LB", "label": "LI", "top": 72, "left": 16},
        {"code": "CB1", "label": "DFC", "top": 76, "left": 36},
        {"code": "CB2", "label": "DFC", "top": 76, "left": 64},
        {"code": "RB", "label": "LD", "top": 72, "left": 84},
        {"code": "CDM1", "label": "MCD", "top": 54, "left": 36},
        {"code": "CDM2", "label": "MCD", "top": 54, "left": 64},
        {"code": "CAM", "label": "MC", "top": 36, "left": 50},
        {"code": "LW", "label": "EI", "top": 14, "left": 18},
        {"code": "ST", "label": "DC", "top": 8, "left": 50},
        {"code": "RW", "label": "ED", "top": 14, "left": 82},
    ],
    "4-4-2": [
        {"code": "GK", "label": "POR", "top": 90, "left": 50},
        {"code": "LB", "label": "LI", "top": 72, "left": 16},
        {"code": "CB1", "label": "DFC", "top": 76, "left": 36},
        {"code": "CB2", "label": "DFC", "top": 76, "left": 64},
        {"code": "RB", "label": "LD", "top": 72, "left": 84},
        {"code": "LM", "label": "MI", "top": 46, "left": 16},
        {"code": "CM1", "label": "MC", "top": 48, "left": 38},
        {"code": "CM2", "label": "MC", "top": 48, "left": 62},
        {"code": "RM", "label": "MD", "top": 46, "left": 84},
        {"code": "ST1", "label": "DC", "top": 12, "left": 38},
        {"code": "ST2", "label": "DC", "top": 12, "left": 62},
    ],
    "3-5-2": [
        {"code": "GK", "label": "POR", "top": 90, "left": 50},
        {"code": "CB1", "label": "DFC", "top": 76, "left": 30},
        {"code": "CB2", "label": "DFC", "top": 80, "left": 50},
        {"code": "CB3", "label": "DFC", "top": 76, "left": 70},
        {"code": "LM", "label": "MI", "top": 48, "left": 10},
        {"code": "CM1", "label": "MC", "top": 50, "left": 36},
        {"code": "CM2", "label": "MC", "top": 54, "left": 50},
        {"code": "CM3", "label": "MC", "top": 50, "left": 64},
        {"code": "RM", "label": "MD", "top": 48, "left": 90},
        {"code": "ST1", "label": "DC", "top": 12, "left": 38},
        {"code": "ST2", "label": "DC", "top": 12, "left": 62},
    ],
}


def _formacion_valida(nombre):
    return nombre if nombre in FORMACIONES else "4-3-3"


def _obtener_alineacion(db, partido_id, equipo_nombre):
    fila = db.execute(
        "SELECT * FROM alineaciones WHERE partido_id = ? AND equipo = ?",
        (partido_id, equipo_nombre),
    ).fetchone()
    if not fila:
        return None
    jugadores = db.execute(
        """SELECT aj.posicion, aj.titular, j.id, j.nombres, j.apellidos, j.numero_camiseta
           FROM alineacion_jugadores aj JOIN jugadores j ON j.id = aj.jugador_id
           WHERE aj.alineacion_id = ? ORDER BY j.apellidos, j.nombres""",
        (fila["id"],),
    ).fetchall()
    titulares = {j["posicion"]: j for j in jugadores if j["titular"]}
    suplentes = [j for j in jugadores if not j["titular"]]
    return {"formacion": fila["formacion"], "titulares": titulares, "suplentes": suplentes}


def _guardar_alineacion(db, partido_id, equipo_nombre, formacion, titulares, suplentes):
    """titulares: lista de (posicion, jugador_id). suplentes: lista de jugador_id."""
    existente = db.execute(
        "SELECT id FROM alineaciones WHERE partido_id = ? AND equipo = ?",
        (partido_id, equipo_nombre),
    ).fetchone()
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    if existente:
        alineacion_id = existente["id"]
        db.execute("DELETE FROM alineacion_jugadores WHERE alineacion_id = ?", (alineacion_id,))
        db.execute(
            "UPDATE alineaciones SET formacion = ?, fecha_registro = ? WHERE id = ?",
            (formacion, ahora, alineacion_id),
        )
    else:
        returning = " RETURNING id" if USANDO_POSTGRES else ""
        cur = db.execute(
            f"INSERT INTO alineaciones (partido_id, equipo, formacion, fecha_registro) VALUES (?, ?, ?, ?){returning}",
            (partido_id, equipo_nombre, formacion, ahora),
        )
        alineacion_id = cur.fetchone()["id"] if USANDO_POSTGRES else cur.lastrowid

    for posicion, jugador_id in titulares:
        db.execute(
            "INSERT INTO alineacion_jugadores (alineacion_id, jugador_id, posicion, titular) VALUES (?, ?, ?, 1)",
            (alineacion_id, jugador_id, posicion),
        )
    for jugador_id in suplentes:
        db.execute(
            "INSERT INTO alineacion_jugadores (alineacion_id, jugador_id, posicion, titular) VALUES (?, ?, 'SUP', 0)",
            (alineacion_id, jugador_id),
        )
    db.commit()


def _rendimiento_titulares(db, equipo_nombre):
    """Para cada jugador que ha sido titular en alguna alineación guardada de
    este equipo, calcula el récord del equipo (V/E/D) en los partidos ya
    jugados donde ese jugador arrancó de titular."""
    filas = db.execute(
        """SELECT j.id AS jugador_id, j.nombres, j.apellidos,
                  p.equipo_local, p.equipo_visitante, p.goles_local, p.goles_visitante
           FROM alineacion_jugadores aj
           JOIN alineaciones a ON a.id = aj.alineacion_id
           JOIN jugadores j ON j.id = aj.jugador_id
           JOIN partidos p ON p.id = a.partido_id
           WHERE a.equipo = ? AND aj.titular = 1 AND p.jugado = 1
             AND p.goles_local IS NOT NULL AND p.goles_visitante IS NOT NULL""",
        (equipo_nombre,),
    ).fetchall()
    resumen = {}
    for f in filas:
        clave = f["jugador_id"]
        if clave not in resumen:
            resumen[clave] = {"jugador": f"{f['apellidos']} {f['nombres']}", "pj": 0, "v": 0, "e": 0, "d": 0}
        es_local = f["equipo_local"] == equipo_nombre
        gf = f["goles_local"] if es_local else f["goles_visitante"]
        gc = f["goles_visitante"] if es_local else f["goles_local"]
        resumen[clave]["pj"] += 1
        if gf > gc:
            resumen[clave]["v"] += 1
        elif gf < gc:
            resumen[clave]["d"] += 1
        else:
            resumen[clave]["e"] += 1
    filas_resumen = list(resumen.values())
    for r in filas_resumen:
        r["pct"] = round(100 * r["v"] / r["pj"]) if r["pj"] else 0
    filas_resumen.sort(key=lambda r: (-r["pct"], -r["pj"]))
    return filas_resumen
