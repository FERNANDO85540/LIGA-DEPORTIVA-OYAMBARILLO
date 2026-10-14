"""Vocalía: hoja oficial del encuentro (asistencia, tarjetas, goles, incidentes, árbitro)."""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from config import CATEGORIA_ACTIVA
from app.database import get_db
from app.decorators import vocalia_required
from app.services.jugadores import _ordenar_por_numero_camiseta
from app.services.liga import _categoria_y_division, _categorias_liga, _divisiones_de_categoria
from app.services.partidos import _fixture_completo
from app.services.sanciones import _generar_sanciones_por_acumulacion, _jugador_suspendido

bp = Blueprint("vocalia", __name__)


@bp.route("/vocalia")
@vocalia_required
def vocalia_modulo():
    db = get_db()
    categoria, division = _categoria_y_division(
        db, request.args.get("categoria", CATEGORIA_ACTIVA), request.args.get("division", "")
    )
    jornadas = _fixture_completo(db, categoria, division)
    return render_template(
        "vocalia/vocalia_modulo.html",
        categoria=categoria, categorias_liga=_categorias_liga(db),
        division=division, divisiones=_divisiones_de_categoria(db, categoria),
        jornadas=jornadas,
    )


@bp.route("/vocalia/partido/<int:partido_id>", methods=["GET"])
@vocalia_required
def vocalia_hoja(partido_id):
    db = get_db()
    partido = db.execute("SELECT * FROM partidos WHERE id = ?", (partido_id,)).fetchone()
    if not partido:
        flash("Partido no encontrado.")
        return redirect(url_for("vocalia.vocalia_modulo"))
    jornada = db.execute("SELECT * FROM jornadas WHERE id = ?", (partido["jornada_id"],)).fetchone()

    jugadores_local = _ordenar_por_numero_camiseta(db.execute(
        "SELECT * FROM jugadores WHERE equipo = ? ORDER BY apellidos, nombres", (partido["equipo_local"],)
    ).fetchall())
    jugadores_visitante = _ordenar_por_numero_camiseta(db.execute(
        "SELECT * FROM jugadores WHERE equipo = ? ORDER BY apellidos, nombres", (partido["equipo_visitante"],)
    ).fetchall())

    asistencia_rows = db.execute(
        "SELECT jugador_id, participo FROM vocalia_asistencia WHERE partido_id = ?", (partido_id,)
    ).fetchall()
    asistencia = {r["jugador_id"]: r["participo"] for r in asistencia_rows}

    tarjetas_rows = db.execute(
        "SELECT jugador_id, tipo FROM tarjetas WHERE partido_id = ?", (partido_id,)
    ).fetchall()
    amarillas_count = {}
    rojas_ids = set()
    
    # Resumen para mostrar en el frontend
    resumen_tarjetas = {
        partido["equipo_local"]: {"amarillas": 0, "rojas": 0},
        partido["equipo_visitante"]: {"amarillas": 0, "rojas": 0}
    }
    
    # Map de jugador a equipo para sumar al resumen
    equipo_por_jugador = {j["id"]: j["equipo"] for j in list(jugadores_local) + list(jugadores_visitante)}

    for r in tarjetas_rows:
        equipo = equipo_por_jugador.get(r["jugador_id"])
        if r["tipo"] == "amarilla":
            amarillas_count[r["jugador_id"]] = amarillas_count.get(r["jugador_id"], 0) + 1
            if equipo: resumen_tarjetas[equipo]["amarillas"] += 1
        else:
            rojas_ids.add(r["jugador_id"])
            if equipo: resumen_tarjetas[equipo]["rojas"] += 1

    goles_rows = db.execute(
        "SELECT jugador_id, SUM(cantidad) AS total FROM goles WHERE partido_id = ? GROUP BY jugador_id", (partido_id,)
    ).fetchall()
    goles_por_jugador = {r["jugador_id"]: r["total"] for r in goles_rows}

    incidentes = db.execute(
        "SELECT * FROM vocalia_incidentes WHERE partido_id = ? ORDER BY fecha", (partido_id,)
    ).fetchall()

    jugadores_js = [
        {"id": j["id"], "label": f"{j['apellidos']} {j['nombres']} ({j['numero_camiseta'] or '-'})", "equipo": j["equipo"]}
        for j in list(jugadores_local) + list(jugadores_visitante)
    ]

    suspendidos_ids = {
        j["id"] for j in list(jugadores_local) + list(jugadores_visitante)
        if _jugador_suspendido(db, j["id"], jornada)
    }

    return render_template(
        "vocalia/vocalia_hoja.html",
        partido=partido, jornada=jornada,
        jugadores_local=jugadores_local, jugadores_visitante=jugadores_visitante,
        asistencia=asistencia, amarillas_count=amarillas_count, rojas_ids=rojas_ids,
        suspendidos_ids=suspendidos_ids,
        goles_por_jugador=goles_por_jugador, incidentes=incidentes,
        jugadores_js=jugadores_js,
        resumen_tarjetas=resumen_tarjetas # Pasamos el resumen
    )


@bp.route("/vocalia/partido/<int:partido_id>/arbitro/guardar", methods=["POST"])
@vocalia_required
def guardar_arbitro(partido_id):
    db = get_db()
    arbitro = request.form.get("arbitro", "").strip()
    informe_arbitro = request.form.get("informe_arbitro", "").strip()
    db.execute(
        "UPDATE partidos SET arbitro = ?, informe_arbitro = ?, hoja_editada = 1 WHERE id = ?",
        (arbitro or None, informe_arbitro or None, partido_id),
    )
    db.commit()
    flash("Árbitro guardado.", "ok")
    return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))


@bp.route("/vocalia/partido/<int:partido_id>/informe_vocalia/guardar", methods=["POST"])
@vocalia_required
def guardar_informe_vocalia(partido_id):
    db = get_db()
    informe_vocalia = request.form.get("informe_vocalia", "").strip()
    db.execute("UPDATE partidos SET informe_vocalia = ?, hoja_editada = 1 WHERE id = ?", (informe_vocalia or None, partido_id))
    db.commit()
    flash("Informe de vocalía guardado.", "ok")
    return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))


@bp.route("/vocalia/partido/<int:partido_id>/hoja/guardar", methods=["POST"])
@vocalia_required
def guardar_hoja_equipo(partido_id):
    db = get_db()
    partido = db.execute("SELECT * FROM partidos WHERE id = ?", (partido_id,)).fetchone()
    if not partido:
        flash("Partido no encontrado.")
        return redirect(url_for("vocalia.vocalia_modulo"))

    equipo_nombre = request.form.get("equipo_nombre", "").strip()
    if equipo_nombre not in (partido["equipo_local"], partido["equipo_visitante"]):
        flash("Equipo inválido.")
        return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))

    ids_validos = {
        j["id"] for j in db.execute("SELECT id FROM jugadores WHERE equipo = ?", (equipo_nombre,)).fetchall()
    }
    todos_ids = [int(x) for x in request.form.getlist("todos_ids") if x.isdigit() and int(x) in ids_validos]
    marcados_participo = {int(x) for x in request.form.getlist("participo") if x.isdigit()}
    marcados_roja = {int(x) for x in request.form.getlist("roja") if x.isdigit()}

    jornada_actual = db.execute("SELECT * FROM jornadas WHERE id = ?", (partido["jornada_id"],)).fetchone()
    suspendidos_ids = {jid for jid in todos_ids if _jugador_suspendido(db, jid, jornada_actual)}
    if marcados_participo & suspendidos_ids:
        flash("No se marcó 'Participó' a jugadores actualmente sancionados/suspendidos.", "ok")
    marcados_participo -= suspendidos_ids

    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")

    for jugador_id in todos_ids:
        db.execute("DELETE FROM vocalia_asistencia WHERE partido_id = ? AND jugador_id = ?", (partido_id, jugador_id))
        db.execute(
            "INSERT INTO vocalia_asistencia (partido_id, jugador_id, participo) VALUES (?, ?, ?)",
            (partido_id, jugador_id, 1 if jugador_id in marcados_participo else 0),
        )

        db.execute("DELETE FROM tarjetas WHERE partido_id = ? AND jugador_id = ?", (partido_id, jugador_id))
        raw_am = request.form.get(f"amarillas_{jugador_id}", "0").strip()
        cantidad_amarillas = int(raw_am) if raw_am.isdigit() else 0
        cantidad_amarillas = max(0, min(cantidad_amarillas, 2))
        for _ in range(cantidad_amarillas):
            db.execute(
                "INSERT INTO tarjetas (jugador_id, jornada_id, partido_id, tipo, fecha) VALUES (?, ?, ?, 'amarilla', ?)",
                (jugador_id, partido["jornada_id"], partido_id, ahora),
            )
        # Doble amarilla = expulsión automática, aunque no se haya marcado roja directa.
        if jugador_id in marcados_roja or cantidad_amarillas >= 2:
            observacion = "Expulsión por doble amarilla" if cantidad_amarillas >= 2 and jugador_id not in marcados_roja else None
            db.execute(
                "INSERT INTO tarjetas (jugador_id, jornada_id, partido_id, tipo, observacion, fecha) VALUES (?, ?, ?, 'roja', ?, ?)",
                (jugador_id, partido["jornada_id"], partido_id, observacion, ahora),
            )

        db.execute("DELETE FROM goles WHERE partido_id = ? AND jugador_id = ?", (partido_id, jugador_id))
        raw = request.form.get(f"goles_{jugador_id}", "0").strip()
        cantidad = int(raw) if raw.isdigit() else 0
        if cantidad > 0:
            db.execute(
                "INSERT INTO goles (jugador_id, partido_id, cantidad, fecha) VALUES (?, ?, ?, ?)",
                (jugador_id, partido_id, cantidad, ahora),
            )

    # ... (todo el código anterior de guardar_hoja_equipo se mantiene igual)

    _generar_sanciones_por_acumulacion(db)
    
    # --- NUEVO: Sincronizar el marcador global sumando los goles de los jugadores ---
    gl_row = db.execute("SELECT SUM(cantidad) AS c FROM goles g JOIN jugadores j ON j.id = g.jugador_id WHERE g.partido_id = ? AND j.equipo = ?", (partido_id, partido["equipo_local"])).fetchone()
    gv_row = db.execute("SELECT SUM(cantidad) AS c FROM goles g JOIN jugadores j ON j.id = g.jugador_id WHERE g.partido_id = ? AND j.equipo = ?", (partido_id, partido["equipo_visitante"])).fetchone()
    
    gl = gl_row["c"] if gl_row and gl_row["c"] is not None else 0
    gv = gv_row["c"] if gv_row and gv_row["c"] is not None else 0
    
    # ACTUALIZA ESTA LÍNEA:
    db.execute("UPDATE partidos SET goles_local = ?, goles_visitante = ?, hoja_editada = 1 WHERE id = ?", (gl, gv, partido_id))
    # -------------------------------------------------------------------------------

    db.commit()
    flash(f"Hoja de {equipo_nombre} guardada.", "ok")
    return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))


@bp.route("/vocalia/partido/<int:partido_id>/cambio/agregar", methods=["POST"])
@vocalia_required
def agregar_cambio(partido_id):
    db = get_db()
    partido = db.execute("SELECT * FROM partidos WHERE id = ?", (partido_id,)).fetchone()
    if not partido:
        flash("Partido no encontrado.")
        return redirect(url_for("vocalia.vocalia_modulo"))
    equipo = request.form.get("equipo", "").strip()
    if equipo not in (partido["equipo_local"], partido["equipo_visitante"]):
        flash("Selecciona un equipo válido.")
        return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))
    sale_id = request.form.get("jugador_sale_id", "").strip()
    entra_id = request.form.get("jugador_entra_id", "").strip()
    if not sale_id.isdigit() or not entra_id.isdigit():
        flash("Selecciona el jugador que sale y el que entra.")
        return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))
    ids_validos = {
        j["id"] for j in db.execute("SELECT id FROM jugadores WHERE equipo = ?", (equipo,)).fetchall()
    }
    if int(sale_id) not in ids_validos or int(entra_id) not in ids_validos:
        flash("Los jugadores del cambio deben pertenecer al equipo seleccionado.")
        return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))
    ahora = datetime.now()
    minuto = ahora.strftime("%H:%M")
    db.execute(
        "INSERT INTO vocalia_cambios (partido_id, equipo, jugador_sale_id, jugador_entra_id, minuto, fecha) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (partido_id, equipo, int(sale_id), int(entra_id), minuto, ahora.strftime("%Y-%m-%d %H:%M")),
    )
    db.commit()
    flash("Cambio registrado.", "ok")
    return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))


@bp.route("/vocalia/cambio/<int:cambio_id>/eliminar", methods=["POST"])
@vocalia_required
def eliminar_cambio(cambio_id):
    db = get_db()
    cambio = db.execute("SELECT partido_id FROM vocalia_cambios WHERE id = ?", (cambio_id,)).fetchone()
    partido_id = cambio["partido_id"] if cambio else None
    db.execute("DELETE FROM vocalia_cambios WHERE id = ?", (cambio_id,))
    db.commit()
    flash("Cambio eliminado.", "ok")
    if partido_id:
        return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))
    return redirect(url_for("vocalia.vocalia_modulo"))


@bp.route("/vocalia/partido/<int:partido_id>/incidente/agregar", methods=["POST"])
@vocalia_required
def agregar_incidente(partido_id):
    db = get_db()
    descripcion = request.form.get("descripcion", "").strip()
    if not descripcion:
        flash("Escribe una descripción del incidente.")
        return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))
    db.execute(
        "INSERT INTO vocalia_incidentes (partido_id, descripcion, fecha) VALUES (?, ?, ?)",
        (partido_id, descripcion, datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    db.execute("UPDATE partidos SET hoja_editada = 1 WHERE id = ?", (partido_id,)) # <- LÍNEA NUEVA
    db.commit()
    flash("Incidente registrado.", "ok")
    return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))


@bp.route("/vocalia/incidente/<int:incidente_id>/eliminar", methods=["POST"])
@vocalia_required
def eliminar_incidente(incidente_id):
    db = get_db()
    incidente = db.execute("SELECT partido_id FROM vocalia_incidentes WHERE id = ?", (incidente_id,)).fetchone()
    partido_id = incidente["partido_id"] if incidente else None
    db.execute("DELETE FROM vocalia_incidentes WHERE id = ?", (incidente_id,))
    db.commit()
    flash("Incidente eliminado.", "ok")
    if partido_id:
        return redirect(url_for("vocalia.vocalia_hoja", partido_id=partido_id))
    return redirect(url_for("vocalia.vocalia_modulo"))
