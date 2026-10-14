"""Comisión Técnica: fixture, oficialización de resultados, mesa y deducción de puntos."""

from flask import Blueprint, flash, render_template, request, url_for

from config import CATEGORIA_ACTIVA, USANDO_POSTGRES
from app.database import get_db
from app.decorators import tecnica_required
from app.services.estadisticas import _calcular_goleadores, _calcular_tabla_posiciones
from app.services.liga import _categoria_y_division, _categorias_liga, _divisiones_de_categoria
from app.services.partidos import _categoria_de_partido, _fixture_completo
from app.utils import ahora_ecuador, volver_a

bp = Blueprint("tecnica", __name__)


@bp.route("/tecnica/jornada/agregar", methods=["POST"])
@tecnica_required
def agregar_jornada():
    db = get_db()
    categoria, division = _categoria_y_division(
        db, request.form.get("categoria", CATEGORIA_ACTIVA), request.form.get("division", "")
    )
    numero = request.form.get("numero", "").strip()
    fecha = request.form.get("fecha", "").strip()
    if not numero.isdigit():
        flash("Ingresa un número de jornada válido.")
        return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))

    locales = request.form.getlist("equipo_local")
    visitantes = request.form.getlist("equipo_visitante")
    horas = request.form.getlist("hora")
    fechas_partido = request.form.getlist("fecha_partido")
    descansos = [e for e in request.form.getlist("descansos") if e]

    partidos_validos = []
    equipos_usados = set()
    for local, visitante, hora, fecha_partido in zip(locales, visitantes, horas, fechas_partido):
        local, visitante, hora, fecha_partido = local.strip(), visitante.strip(), hora.strip(), fecha_partido.strip()
        if not local or not visitante:
            continue
        if local == visitante:
            flash("Un equipo no puede jugar contra sí mismo.")
            return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))
        if local in equipos_usados or visitante in equipos_usados:
            flash("Hay un equipo asignado a más de un partido en la misma jornada.")
            return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))
        equipos_usados.add(local)
        equipos_usados.add(visitante)
        partidos_validos.append((local, visitante, hora, fecha_partido))

    for equipo in descansos:
        if equipo in equipos_usados:
            flash(f"'{equipo}' no puede descansar y jugar en la misma jornada.")
            return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))

    if not partidos_validos and not descansos:
        flash("Agrega al menos un partido o un equipo que descansa.")
        return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))

    returning = " RETURNING id" if USANDO_POSTGRES else ""
    cur = db.execute(
        f"INSERT INTO jornadas (numero, fecha, categoria, division) VALUES (?, ?, ?, ?){returning}",
        (int(numero), fecha or None, categoria, division),
    )
    jornada_id = cur.fetchone()["id"] if USANDO_POSTGRES else cur.lastrowid
    for local, visitante, hora, fecha_partido in partidos_validos:
        db.execute(
            "INSERT INTO partidos (jornada_id, equipo_local, equipo_visitante, hora, fecha) VALUES (?, ?, ?, ?, ?)",
            (jornada_id, local, visitante, hora or None, fecha_partido or None),
        )
    for equipo in descansos:
        db.execute("INSERT INTO descansos (jornada_id, equipo) VALUES (?, ?)", (jornada_id, equipo))
    db.commit()
    flash(f"Jornada {numero} agregada.", "ok")
    return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))


@bp.route("/tecnica/jornada/<int:jornada_id>/eliminar", methods=["POST"])
@tecnica_required
def eliminar_jornada(jornada_id):
    db = get_db()
    jornada = db.execute("SELECT * FROM jornadas WHERE id = ?", (jornada_id,)).fetchone()
    categoria = jornada["categoria"] if jornada else CATEGORIA_ACTIVA
    division = jornada["division"] if jornada else ""
    db.execute("DELETE FROM partidos WHERE jornada_id = ?", (jornada_id,))
    db.execute("DELETE FROM descansos WHERE jornada_id = ?", (jornada_id,))
    db.execute("DELETE FROM jornadas WHERE id = ?", (jornada_id,))
    db.commit()
    flash("Jornada eliminada.", "ok")
    return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))


@bp.route("/tecnica")
@tecnica_required
def tecnica_modulo():
    db = get_db()
    
    categoria, division = _categoria_y_division(
        db, request.args.get("categoria", CATEGORIA_ACTIVA), request.args.get("division", "")
    )
    equipos = db.execute(
        "SELECT * FROM equipos WHERE categoria = ? AND division = ? ORDER BY nombre", (categoria, division)
    ).fetchall()
    jornadas = _fixture_completo(db, categoria, division)
    ultima = db.execute(
        "SELECT MAX(numero) m FROM jornadas WHERE categoria = ? AND division = ?", (categoria, division)
    ).fetchone()["m"]
    siguiente_numero = (ultima or 0) + 1
    tabla = _calcular_tabla_posiciones(db, categoria, division)
    goleadores = _calcular_goleadores(db, categoria, division, limite=10)
    sanciones_puntos = db.execute("SELECT * FROM puntos_sancion WHERE categoria = ? AND division = ? ORDER BY id DESC", (categoria, division)).fetchall()

    return render_template(
        "tecnica/tecnica_modulo.html",
        categoria=categoria,
        categorias_liga=_categorias_liga(db),
        division=division,
        divisiones=_divisiones_de_categoria(db, categoria),
        equipos=equipos,
        siguiente_numero=siguiente_numero,
        jornadas=jornadas,
        tabla=tabla,
        goleadores=goleadores,
        sanciones_puntos=sanciones_puntos,
    )


@bp.route("/tecnica/partido/<int:partido_id>/resultado", methods=["POST"])
@tecnica_required
def registrar_resultado(partido_id):
    db = get_db()
    partido = db.execute("SELECT * FROM partidos WHERE id = ?", (partido_id,)).fetchone()
    categoria, division = _categoria_de_partido(db, partido_id)
    if not partido:
        flash("Partido no encontrado.")
        return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))
    gl = request.form.get("goles_local", "").strip()
    gv = request.form.get("goles_visitante", "").strip()
    if not gl.isdigit() or not gv.isdigit():
        flash("Ingresa un marcador válido (números).")
        return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))
    db.execute(
        "UPDATE partidos SET goles_local = ?, goles_visitante = ?, jugado = 1 WHERE id = ?",
        (int(gl), int(gv), partido_id),
    )
    db.commit()
    flash("Resultado registrado.", "ok")
    return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))


@bp.route("/tecnica/partido/<int:partido_id>/quitar_resultado", methods=["POST"])
@tecnica_required
def quitar_resultado(partido_id):
    db = get_db()
    categoria, division = _categoria_de_partido(db, partido_id)
    db.execute(
        "UPDATE partidos SET goles_local = NULL, goles_visitante = NULL, jugado = 0 WHERE id = ?",
        (partido_id,),
    )
    db.commit()
    flash("Resultado eliminado.", "ok")
    return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))


@bp.route("/tecnica/partido/<int:partido_id>/aprobar", methods=["POST"])
@tecnica_required
def tecnica_aprobar_partido(partido_id):
    """La comisión técnica simplemente da el 'OK' al partido que ya cerró Vocalía."""
    db = get_db()
    categoria, division = _categoria_de_partido(db, partido_id)
    db.execute("UPDATE partidos SET jugado = 1, en_vivo = 0, ganador_escritorio = NULL WHERE id = ?", (partido_id,))
    db.commit()
    flash("Partido oficializado con el resultado de Vocalía.", "ok")
    return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))


@bp.route("/tecnica/partido/<int:partido_id>/escritorio", methods=["POST"])
@tecnica_required
def tecnica_ganador_escritorio(partido_id):
    """El partido lo gana un equipo en la mesa (2-0) por sanción al rival."""
    db = get_db()
    categoria, division = _categoria_de_partido(db, partido_id)
    ganador = request.form.get("ganador_escritorio")
    
    partido = db.execute("SELECT equipo_local, equipo_visitante FROM partidos WHERE id = ?", (partido_id,)).fetchone()
    if ganador not in (partido["equipo_local"], partido["equipo_visitante"]):
        flash("Debes seleccionar un equipo válido.")
        return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))
        
    db.execute("UPDATE partidos SET jugado = 1, en_vivo = 0, ganador_escritorio = ? WHERE id = ?", (ganador, partido_id))
    db.commit()
    flash(f"Partido resuelto en mesa: 2 - 0 a favor de {ganador}.", "ok")
    return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))


@bp.route("/tecnica/restar_puntos", methods=["POST"])
@tecnica_required
def tecnica_restar_puntos():
    db = get_db()
    categoria = request.form.get("categoria")
    division = request.form.get("division")
    equipo = request.form.get("equipo")
    puntos = request.form.get("puntos", "0")
    motivo = request.form.get("motivo", "").strip()
    
    if not puntos.isdigit() or int(puntos) <= 0 or not motivo:
        flash("Ingresa una cantidad de puntos válida y un motivo.")
        return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))
        
    db.execute(
        "INSERT INTO puntos_sancion (equipo, categoria, division, puntos_descontar, motivo, fecha) VALUES (?, ?, ?, ?, ?, ?)",
        (equipo, categoria, division, int(puntos), motivo, ahora_ecuador().strftime("%Y-%m-%d %H:%M"))
    )
    db.commit()
    flash(f"Se restaron {puntos} puntos a {equipo}.", "ok")
    return volver_a(url_for("tecnica.tecnica_modulo", categoria=categoria, division=division))


@bp.route("/tecnica/restar_puntos/<int:sancion_id>/eliminar", methods=["POST"])
@tecnica_required
def tecnica_eliminar_resta_puntos(sancion_id):
    db = get_db()
    sancion = db.execute("SELECT categoria, division FROM puntos_sancion WHERE id = ?", (sancion_id,)).fetchone()
    if sancion:
        db.execute("DELETE FROM puntos_sancion WHERE id = ?", (sancion_id,))
        db.commit()
        flash("Penalización de puntos eliminada. La tabla ha sido recalculada.", "ok")
        return volver_a(url_for("tecnica.tecnica_modulo", categoria=sancion["categoria"], division=sancion["division"]))
    return volver_a(url_for("tecnica.tecnica_modulo"))
