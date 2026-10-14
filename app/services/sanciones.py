"""Reglas de Penas y Sanciones: suspensiones, rojas y acumulación de amarillas."""
from datetime import datetime


def _jugador_suspendido(db, jugador_id, jornada_actual):
    """True si el jugador tiene una sanción de la Comisión de Penas y Sanciones
    que todavía lo deja suspendido en esta jornada (mismo campeonato/categoría/división)."""
    if not jornada_actual:
        return False
    sanciones_rows = db.execute(
        "SELECT jornadas_sancionado, jornada_desde_numero, categoria, division FROM sanciones "
        "WHERE jugador_id = ? AND jornada_desde_numero IS NOT NULL",
        (jugador_id,),
    ).fetchall()
    for s in sanciones_rows:
        if s["categoria"] != jornada_actual["categoria"] or s["division"] != jornada_actual["division"]:
            continue
        inicio = s["jornada_desde_numero"]
        fin = inicio + s["jornadas_sancionado"] - 1
        if inicio <= jornada_actual["numero"] <= fin:
            return True
    return False


def _sancion_activa(db, sancion):
    """True si la sanción todavía cubre jornadas no jugadas (no se ha 'cumplido')."""
    if sancion["jornada_desde_numero"] is None:
        return False
    ultima = db.execute(
        "SELECT MAX(numero) m FROM jornadas WHERE categoria = ? AND division = ?",
        (sancion["categoria"], sancion["division"]),
    ).fetchone()["m"] or 0
    fin = sancion["jornada_desde_numero"] + sancion["jornadas_sancionado"] - 1
    return ultima <= fin


def _rojas_pendientes_de_sancion(db):
    """Tarjetas rojas (ya cargadas 100% desde Vocalía) que todavía no tienen
    una sanción registrada — son las únicas que puede elegir el formulario
    de 'Registrar roja directa', para no dejar sancionar a cualquier jugador
    ni sancionar dos veces la misma expulsión."""
    return db.execute("""
        SELECT t.id AS tarjeta_id, t.jugador_id, t.observacion, t.fecha,
               j.nombres AS j_nombres, j.apellidos AS j_apellidos, j.equipo AS j_equipo,
               jo.numero AS jornada_numero, jo.categoria AS categoria, jo.division AS division
        FROM tarjetas t
        JOIN jugadores j ON j.id = t.jugador_id
        LEFT JOIN jornadas jo ON jo.id = t.jornada_id
        WHERE t.tipo = 'roja'
          AND t.id NOT IN (SELECT tarjeta_id FROM sanciones WHERE tarjeta_id IS NOT NULL)
        ORDER BY t.fecha DESC, t.id DESC
    """).fetchall()


def _amarillas_validas_agrupadas(db):
    """Agrupa las tarjetas amarillas por (jugador, partido). Devuelve una lista de
    filas de tarjetas agrupadas por jugador, ya EXCLUYENDO los pares de amarillas
    que resultaron en expulsión por doble amarilla en el mismo partido (esa falta
    ya se paga con la suspensión de la roja, según el Módulo 2 del reglamento)."""
    filas = db.execute(
        """SELECT t.id, t.jugador_id, t.partido_id, t.jornada_id, jo.numero AS jornada_numero,
                  jo.categoria AS categoria, jo.division AS division
           FROM tarjetas t
           LEFT JOIN jornadas jo ON jo.id = t.jornada_id
           WHERE t.tipo = 'amarilla'
           ORDER BY t.id"""
    ).fetchall()

    por_partido = {}
    for f in filas:
        key = (f["jugador_id"], f["partido_id"]) if f["partido_id"] is not None else (f["jugador_id"], f["id"])
        por_partido.setdefault(key, []).append(f)

    validas_por_jugador = {}
    for (jugador_id, _clave), grupo in por_partido.items():
        if len(grupo) >= 2:
            continue
        validas_por_jugador.setdefault(jugador_id, []).extend(grupo)

    return validas_por_jugador


def _generar_sanciones_por_acumulacion(db):
    """Genera automáticamente una sanción de 1 jornada de suspensión por cada
    múltiplo de 5 amarillas válidas acumuladas por jugador (globalmente, ya
    excluyendo las expulsiones por doble amarilla). Es idempotente: solo agrega
    las sanciones que falten y nunca borra las ya generadas."""
    validas_por_jugador = _amarillas_validas_agrupadas(db)
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    for jugador_id, tarjetas_validas in validas_por_jugador.items():
        tarjetas_validas.sort(key=lambda t: t["id"])
        objetivo = len(tarjetas_validas) // 5
        if objetivo == 0:
            continue
        existentes = db.execute(
            "SELECT COUNT(*) c FROM sanciones WHERE jugador_id = ? AND origen = 'acumulacion'",
            (jugador_id,),
        ).fetchone()["c"]
        for n in range(existentes, objetivo):
            disparo = tarjetas_validas[(n + 1) * 5 - 1]
            if disparo["jornada_numero"] is None:
                continue
            db.execute(
                """INSERT INTO sanciones (jugador_id, motivo, jornadas_sancionado, jornada_desde_id,
                   jornada_desde_numero, categoria, division, valor_multa, pagada, fecha, origen, catalogo_id)
                   VALUES (?, ?, 1, ?, ?, ?, ?, NULL, 0, ?, 'acumulacion', NULL)""",
                (jugador_id, "Acumulación de 5 tarjetas amarillas", disparo["jornada_id"],
                 disparo["jornada_numero"] + 1, disparo["categoria"], disparo["division"], ahora),
            )
