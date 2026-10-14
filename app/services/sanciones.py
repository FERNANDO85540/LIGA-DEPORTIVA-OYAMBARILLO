"""Reglas de Penas y Sanciones: suspensiones, rojas y acumulación de amarillas."""
from app.utils import ahora_ecuador


import re

FECHA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------- Cómputo central de suspensiones ----------
#
# Regla: una sanción de N partidos se cumple SOLO con partidos que el equipo
# del jugador ya jugó (Vocalía llenó la hoja o la Comisión Técnica oficializó
# el resultado), dentro de su campeonato/división y desde su inicio. Los
# partidos programados a futuro y las jornadas en que el equipo descansa no
# descuentan nada. Público, Penas y Vocalía usan todos esta misma lógica.

def _partido_jugado(partido):
    return bool(partido["jugado"] or partido["hoja_editada"])


def _partidos_del_equipo(db, equipo, categoria, division):
    return db.execute(
        """SELECT p.id, p.jugado, p.hoja_editada, p.fecha, jo.numero AS jornada_numero
           FROM partidos p JOIN jornadas jo ON jo.id = p.jornada_id
           WHERE jo.categoria = ? AND jo.division = ?
             AND (p.equipo_local = ? OR p.equipo_visitante = ?)
           ORDER BY jo.numero, p.id""",
        (categoria, division or "", equipo, equipo),
    ).fetchall()


def _partido_en_rango(sancion, partido):
    """¿El partido cae desde el inicio de la sanción? La fecha de inicio
    definida a mano manda; si el partido no tiene fecha, se usa la jornada."""
    fecha_inicio = (sancion["fecha_inicio"] or "").strip()
    fecha_partido = (partido["fecha"] or "").strip()
    if fecha_inicio and FECHA_ISO.match(fecha_partido):
        return fecha_partido >= fecha_inicio
    if sancion["jornada_desde_numero"] is None:
        return bool(fecha_inicio)
    return partido["jornada_numero"] >= sancion["jornada_desde_numero"]


def estado_sancion(db, sancion, equipo=None):
    """Estado de una sanción calculado sobre los partidos realmente jugados.

    Devuelve dict con: total, cumplidos, pendientes, activa, estado
    ('activa' | 'cumplida' | 'levantada' | 'sin_inicio') y `proximos`: los
    partidos aún no jugados en que el jugador no puede jugar."""
    total = sancion["jornadas_sancionado"] or 0
    base = {"total": total, "cumplidos": 0, "pendientes": 0, "activa": False, "proximos": []}
    if sancion["anulada"]:
        return {**base, "estado": "levantada"}
    if sancion["jornada_desde_numero"] is None and not (sancion["fecha_inicio"] or "").strip():
        return {**base, "estado": "sin_inicio"}
    if equipo is None:
        fila = db.execute("SELECT equipo FROM jugadores WHERE id = ?", (sancion["jugador_id"],)).fetchone()
        equipo = fila["equipo"] if fila else None
    partidos = [
        p for p in _partidos_del_equipo(db, equipo, sancion["categoria"], sancion["division"])
        if _partido_en_rango(sancion, p)
    ]
    cumplidos = min(sum(1 for p in partidos if _partido_jugado(p)), total)
    pendientes = total - cumplidos
    proximos = [p for p in partidos if not _partido_jugado(p)][:pendientes]
    return {
        **base, "cumplidos": cumplidos, "pendientes": pendientes, "activa": pendientes > 0,
        "proximos": proximos, "estado": "activa" if pendientes > 0 else "cumplida",
    }


def _sancion_activa(db, sancion):
    """True si a la sanción todavía le faltan partidos por cumplir."""
    return estado_sancion(db, sancion)["activa"]


def _jugador_suspendido(db, jugador_id, jornada_actual, partido=None):
    """True si el jugador no puede jugar ESTE partido por una sanción vigente
    (mismo campeonato/división). Un partido sin jugar queda bloqueado mientras
    falten partidos por cumplir; uno ya jugado (al revisar una hoja vieja) se
    evalúa contando solo los partidos jugados antes que él."""
    if not jornada_actual:
        return False
    jugador = db.execute("SELECT equipo FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        return False
    sanciones_rows = db.execute(
        "SELECT * FROM sanciones WHERE jugador_id = ? AND anulada = 0 AND categoria = ? AND division = ?",
        (jugador_id, jornada_actual["categoria"], jornada_actual["division"]),
    ).fetchall()
    for s in sanciones_rows:
        if s["jornada_desde_numero"] is None and not (s["fecha_inicio"] or "").strip():
            continue
        partidos = [
            p for p in _partidos_del_equipo(db, jugador["equipo"], s["categoria"], s["division"])
            if _partido_en_rango(s, p)
        ]
        if partido is None:
            # Sin partido concreto: se evalúa la jornada (compatibilidad).
            actual = next((p for p in partidos if p["jornada_numero"] == jornada_actual["numero"]), None)
        else:
            actual = next((p for p in partidos if p["id"] == partido["id"]), None)
        if actual is None:
            continue  # el partido es anterior al inicio de la sanción
        if _partido_jugado(actual):
            orden = (actual["jornada_numero"], actual["id"])
            cumplidos = sum(1 for p in partidos if _partido_jugado(p) and (p["jornada_numero"], p["id"]) < orden)
        else:
            cumplidos = sum(1 for p in partidos if _partido_jugado(p) and p["id"] != actual["id"])
        if cumplidos < s["jornadas_sancionado"]:
            return True
    return False


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
    """Sincroniza las sanciones automáticas por acumulación: 1 partido de
    suspensión por cada múltiplo de 5 amarillas válidas del jugador (ya
    excluyendo las expulsiones por doble amarilla).

    Es bidireccional: si Vocalía agrega amarillas se crean las sanciones que
    falten; si corrige y quita amarillas (ej. de 5 a 4), se borran las que ya
    no corresponden. Las que se mantienen solo se re-ubican si cambió la
    jornada de la 5.ª amarilla; motivo, partidos y fecha de inicio editados a
    mano por la Comisión se respetan."""
    validas_por_jugador = _amarillas_validas_agrupadas(db)
    con_sancion = {
        f["jugador_id"] for f in
        db.execute("SELECT DISTINCT jugador_id FROM sanciones WHERE origen = 'acumulacion'").fetchall()
    }
    ahora = ahora_ecuador().strftime("%Y-%m-%d %H:%M")
    for jugador_id in set(validas_por_jugador) | con_sancion:
        # Orden cronológico por jornada (no por id: Vocalía re-inserta las
        # tarjetas de un partido cada vez que guarda su hoja).
        tarjetas_validas = sorted(
            validas_por_jugador.get(jugador_id, []),
            key=lambda t: (t["jornada_numero"] or 0, t["partido_id"] or 0, t["id"]),
        )
        disparos = [tarjetas_validas[(n + 1) * 5 - 1] for n in range(len(tarjetas_validas) // 5)]
        disparos = [d for d in disparos if d["jornada_numero"] is not None]
        existentes = db.execute(
            "SELECT * FROM sanciones WHERE jugador_id = ? AND origen = 'acumulacion' ORDER BY id",
            (jugador_id,),
        ).fetchall()

        for existente, disparo in zip(existentes, disparos):
            if (existente["jornada_desde_id"], existente["jornada_desde_numero"]) != (
                    disparo["jornada_id"], disparo["jornada_numero"] + 1):
                db.execute(
                    "UPDATE sanciones SET jornada_desde_id = ?, jornada_desde_numero = ?, categoria = ?, division = ? "
                    "WHERE id = ?",
                    (disparo["jornada_id"], disparo["jornada_numero"] + 1, disparo["categoria"],
                     disparo["division"], existente["id"]),
                )
        for disparo in disparos[len(existentes):]:
            db.execute(
                """INSERT INTO sanciones (jugador_id, motivo, jornadas_sancionado, jornada_desde_id,
                   jornada_desde_numero, categoria, division, valor_multa, pagada, fecha, origen, catalogo_id)
                   VALUES (?, ?, 1, ?, ?, ?, ?, NULL, 0, ?, 'acumulacion', NULL)""",
                (jugador_id, "Acumulación de 5 tarjetas amarillas", disparo["jornada_id"],
                 disparo["jornada_numero"] + 1, disparo["categoria"], disparo["division"], ahora),
            )
        for sobrante in existentes[len(disparos):]:
            db.execute("DELETE FROM sanciones WHERE id = ?", (sobrante["id"],))
