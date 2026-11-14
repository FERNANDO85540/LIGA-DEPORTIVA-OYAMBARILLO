"""Fases de campeonato: Fase Regular, Liguilla Final, Liguilla de No Descenso y Finales.

La Fase Regular es implícita: son las jornadas con fase_id NULL (todo lo
histórico). Las demás fases viven en la tabla `fases`, con sus equipos en
`fase_equipos`, sus propias jornadas (jornadas.fase_id) y sus propios ajustes
de puntos (puntos_sancion.fase_id), así su tabla de posiciones arranca de cero.

Goles y tarjetas NO dependen de la fase: se calculan por jugador sobre todo el
campeonato, por lo que se siguen acumulando entre fases. Por la misma razón las
jornadas de una fase nueva continúan la numeración del campeonato (las
suspensiones y la acumulación de amarillas se ordenan por número de jornada).
"""
from app.utils import ahora_ecuador

REGULAR = "regular"

TIPOS_FASE = {
    "liguilla_final": {"nombre": "Liguilla Final", "orden": 1, "icono": "🏆"},
    "liguilla_descenso": {"nombre": "Liguilla de No Descenso", "orden": 1, "icono": "🛡️"},
    "finales": {"nombre": "Finales", "orden": 2, "icono": "🥇"},
}

# Desde qué fase se puede generar cada tipo de fase.
DESTINOS_POR_ORIGEN = {
    REGULAR: ("liguilla_final", "liguilla_descenso", "finales"),
    "liguilla_final": ("finales",),
}

FASE_REGULAR = {
    "id": None, "clave": REGULAR, "tipo": REGULAR, "nombre": "Fase Regular", "orden": 0, "icono": "📋",
    "fase_origen_id": None,
}


def _fase_dict(fila):
    info = TIPOS_FASE.get(fila["tipo"], {})
    return {
        "id": fila["id"], "clave": str(fila["id"]), "tipo": fila["tipo"], "nombre": fila["nombre"],
        "orden": fila["orden"], "icono": info.get("icono", "🏁"), "fase_origen_id": fila["fase_origen_id"],
    }


def fases_del_torneo(db, categoria, division):
    """Fase Regular + fases generadas, en orden (Regular, Liguillas, Finales)."""
    filas = db.execute(
        "SELECT * FROM fases WHERE categoria = ? AND division = ? ORDER BY orden, id", (categoria, division or "")
    ).fetchall()
    return [dict(FASE_REGULAR)] + [_fase_dict(f) for f in filas]


def fase_seleccionada(db, categoria, division, clave, por_defecto="actual"):
    """Devuelve la fase pedida (`clave` = 'regular' o el id). Si no se pide
    ninguna válida, la fase vigente (la de mayor orden; si hay dos del mismo
    orden, la primera creada: Liguilla Final antes que la de No Descenso)."""
    fases = fases_del_torneo(db, categoria, division)
    clave = str(clave or "").strip()
    for f in fases:
        if f["clave"] == clave:
            return f, fases
    if por_defecto == REGULAR:
        return fases[0], fases
    mayor = max(f["orden"] for f in fases)
    return next(f for f in fases if f["orden"] == mayor), fases


def obtener_fase(db, fase_id):
    if fase_id in (None, "", REGULAR):
        return dict(FASE_REGULAR)
    fila = db.execute("SELECT * FROM fases WHERE id = ?", (int(fase_id),)).fetchone()
    return _fase_dict(fila) if fila else None


def equipos_de_fase(db, categoria, division, fase):
    """Nombres de los equipos que juegan la fase (Regular: todos los del torneo)."""
    if fase["id"] is None:
        filas = db.execute(
            "SELECT nombre FROM equipos WHERE categoria = ? AND division = ? ORDER BY nombre",
            (categoria, division or ""),
        ).fetchall()
        return [f["nombre"] for f in filas]
    filas = db.execute(
        "SELECT equipo FROM fase_equipos WHERE fase_id = ? ORDER BY posicion_origen, equipo", (fase["id"],)
    ).fetchall()
    return [f["equipo"] for f in filas]


def filtro_jornadas_fase(fase, alias="jo"):
    """Fragmento SQL (y parámetros) que limita las jornadas a una fase."""
    if fase["id"] is None:
        return f"{alias}.fase_id IS NULL", ()
    return f"{alias}.fase_id = ?", (fase["id"],)


def numero_minimo_jornada(db, categoria, division, fase):
    """Las jornadas de una fase deben numerarse después de las de las fases
    anteriores (de menor orden), para que suspensiones y acumulación de
    amarillas sigan su curso cronológico entre fases."""
    if fase["id"] is None:
        return 1
    fila = db.execute(
        """SELECT MAX(jo.numero) AS m FROM jornadas jo LEFT JOIN fases f ON f.id = jo.fase_id
           WHERE jo.categoria = ? AND jo.division = ? AND COALESCE(f.orden, 0) < ?""",
        (categoria, division or "", fase["orden"]),
    ).fetchone()
    return (fila["m"] or 0) + 1


def siguiente_numero_jornada(db, categoria, division, fase):
    fila = db.execute(
        "SELECT MAX(numero) AS m FROM jornadas WHERE categoria = ? AND division = ?", (categoria, division or "")
    ).fetchone()
    return max((fila["m"] or 0) + 1, numero_minimo_jornada(db, categoria, division, fase))


# ---------- Configuración por torneo ----------

def config_fases(db, categoria, division):
    fila = db.execute(
        "SELECT * FROM config_fases WHERE categoria = ? AND division = ?", (categoria, division or "")
    ).fetchone()
    if not fila:
        return {"cupos_liguilla_final": None, "tiene_liguilla_descenso": False,
                "cupos_liguilla_descenso": None, "cupos_finales": None}
    return {
        "cupos_liguilla_final": fila["cupos_liguilla_final"],
        "tiene_liguilla_descenso": bool(fila["tiene_liguilla_descenso"]),
        "cupos_liguilla_descenso": fila["cupos_liguilla_descenso"],
        "cupos_finales": fila["cupos_finales"],
    }


def guardar_config_fases(db, categoria, division, cupos_final, tiene_descenso, cupos_descenso, cupos_finales):
    division = division or ""
    existe = db.execute(
        "SELECT id FROM config_fases WHERE categoria = ? AND division = ?", (categoria, division)
    ).fetchone()
    valores = (cupos_final, 1 if tiene_descenso else 0, cupos_descenso if tiene_descenso else None, cupos_finales)
    if existe:
        db.execute(
            """UPDATE config_fases SET cupos_liguilla_final = ?, tiene_liguilla_descenso = ?,
               cupos_liguilla_descenso = ?, cupos_finales = ? WHERE id = ?""",
            (*valores, existe["id"]),
        )
    else:
        db.execute(
            """INSERT INTO config_fases (cupos_liguilla_final, tiene_liguilla_descenso, cupos_liguilla_descenso,
               cupos_finales, categoria, division) VALUES (?, ?, ?, ?, ?, ?)""",
            (*valores, categoria, division),
        )


def propuesta_de_clasificacion(tabla, origen, config):
    """Destino sugerido para cada equipo de la tabla de la fase de origen,
    según la configuración del torneo. Devuelve {equipo: tipo_destino | ''}.
    '' = eliminado / sin participación en la siguiente fase."""
    propuesta = {}
    if origen == REGULAR:
        cupos = config["cupos_liguilla_final"]
        if cupos is None:
            return {f["equipo"]: "" for f in tabla}
        restantes = tabla[cupos:]
        if config["tiene_liguilla_descenso"]:
            n = config["cupos_liguilla_descenso"]
            descenso = restantes if n is None else restantes[-n:] if n > 0 else []
        else:
            descenso = []
        nombres_descenso = {f["equipo"] for f in descenso}
        for i, f in enumerate(tabla):
            if i < cupos:
                propuesta[f["equipo"]] = "liguilla_final"
            elif f["equipo"] in nombres_descenso:
                propuesta[f["equipo"]] = "liguilla_descenso"
            else:
                propuesta[f["equipo"]] = ""
        return propuesta
    cupos = config["cupos_finales"]
    for i, f in enumerate(tabla):
        propuesta[f["equipo"]] = "finales" if cupos is not None and i < cupos else ""
    return propuesta


def crear_fase(db, categoria, division, tipo, equipos_con_posicion, fase_origen_id=None):
    """Crea la fase con sus equipos. `equipos_con_posicion`: [(equipo, posición en la fase de origen)]."""
    from config import USANDO_POSTGRES

    info = TIPOS_FASE[tipo]
    returning = " RETURNING id" if USANDO_POSTGRES else ""
    cur = db.execute(
        f"""INSERT INTO fases (categoria, division, tipo, nombre, orden, fase_origen_id, fecha)
            VALUES (?, ?, ?, ?, ?, ?, ?){returning}""",
        (categoria, division or "", tipo, info["nombre"], info["orden"], fase_origen_id,
         ahora_ecuador().strftime("%Y-%m-%d %H:%M")),
    )
    fase_id = cur.fetchone()["id"] if USANDO_POSTGRES else cur.lastrowid
    for equipo, posicion in equipos_con_posicion:
        db.execute(
            "INSERT INTO fase_equipos (fase_id, equipo, posicion_origen) VALUES (?, ?, ?)",
            (fase_id, equipo, posicion),
        )
    return fase_id
