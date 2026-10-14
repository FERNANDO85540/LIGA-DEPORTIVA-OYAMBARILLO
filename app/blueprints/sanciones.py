"""Comisión de Penas y Sanciones."""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from config import CATEGORIA_ACTIVA
from app.database import get_db
from app.decorators import sanciones_required
from app.services.liga import _categoria_y_division, _categorias_liga, _divisiones_de_categoria
from app.services.sanciones import _amarillas_validas_agrupadas, _rojas_pendientes_de_sancion, _sancion_activa
from app.utils import _to_float

bp = Blueprint("sanciones", __name__)


@bp.route("/sanciones")
@sanciones_required
def sanciones_modulo():
    db = get_db()
    
    categoria, division = _categoria_y_division(
        db, request.args.get("categoria", CATEGORIA_ACTIVA), request.args.get("division", "")
    )

    catalogo = db.execute("SELECT * FROM sanciones_catalogo ORDER BY articulo, id").fetchall()
    
    # Filtramos rojas pendientes por categoría y división
    rojas_pendientes = [r for r in _rojas_pendientes_de_sancion(db) 
                        if r["categoria"] == categoria and r["division"] == division]

    # Sanciones registradas de la categoría
    sanciones = db.execute("""
        SELECT s.*, j.nombres AS j_nombres, j.apellidos AS j_apellidos, j.equipo AS j_equipo
        FROM sanciones s
        JOIN jugadores j ON j.id = s.jugador_id
        WHERE s.categoria = ? AND s.division = ?
        ORDER BY s.fecha DESC, s.id DESC
    """, (categoria, division)).fetchall()
    
    sanciones_activas = {s["id"] for s in sanciones if _sancion_activa(db, s)}

    return render_template(
        "sanciones/sanciones_modulo.html",
        catalogo=catalogo,
        rojas_pendientes=rojas_pendientes,
        sanciones=sanciones,
        sanciones_activas=sanciones_activas,
        categoria=categoria,
        categorias_liga=_categorias_liga(db),
        division=division,
        divisiones=_divisiones_de_categoria(db, categoria),
    )


@bp.route("/sanciones/acumulacion")
@sanciones_required
def sanciones_acumulacion():
    """Nueva vista separada para ver solo la acumulación de tarjetas."""
    db = get_db()
    categoria, division = _categoria_y_division(
        db, request.args.get("categoria", CATEGORIA_ACTIVA), request.args.get("division", "")
    )
    
    jugadores = db.execute(
        "SELECT * FROM jugadores WHERE categoria = ? AND division = ? ORDER BY equipo, apellidos, nombres",
        (categoria, division)
    ).fetchall()
    jugadores_map = {j["id"]: j for j in jugadores}
    
    todas_validas = _amarillas_validas_agrupadas(db)
    validas_por_jugador = {jid: tarjetas for jid, tarjetas in todas_validas.items() if jid in jugadores_map}
    
    todas_tarjetas = db.execute("SELECT jugador_id, tipo, valor_multa FROM tarjetas").fetchall()
    rojas_count = {}
    multas_total = {}
    for t in todas_tarjetas:
        if t["jugador_id"] in jugadores_map:
            multas_total[t["jugador_id"]] = multas_total.get(t["jugador_id"], 0) + (t["valor_multa"] or 0)
            if t["tipo"] == "roja":
                rojas_count[t["jugador_id"]] = rojas_count.get(t["jugador_id"], 0) + 1

    jugadores_con_tarjetas = set(validas_por_jugador) | set(rojas_count)
    acumulado = []
    for jid in jugadores_con_tarjetas:
        j = jugadores_map.get(jid)
        if not j: continue
        validas = len(validas_por_jugador.get(jid, []))
        rojas = rojas_count.get(jid, 0)
        acumulado.append({
            "nombres": j["nombres"], "apellidos": j["apellidos"], "equipo": j["equipo"],
            "amarillas_validas": validas, "rojas": rojas, "total": validas + rojas,
            "multas": multas_total.get(jid, 0),
        })
    acumulado.sort(key=lambda x: x["total"], reverse=True)

    return render_template(
        "sanciones/acumulacion_tarjetas.html",
        acumulado=acumulado,
        categoria=categoria,
        division=division
    )


@bp.route("/sanciones/roja_directa/agregar", methods=["POST"])
@sanciones_required
def agregar_roja_directa():
    db = get_db()
    tarjeta_id = request.form.get("tarjeta_id", "").strip()
    catalogo_id = request.form.get("catalogo_id", "").strip()

    if not tarjeta_id.isdigit() or not catalogo_id.isdigit():
        flash("Selecciona la roja a sancionar y el motivo (catálogo).")
        return redirect(request.referrer or url_for("sanciones.sanciones_modulo"))

    tarjeta = db.execute("SELECT * FROM tarjetas WHERE id = ? AND tipo = 'roja'", (int(tarjeta_id),)).fetchone()
    catalogo = db.execute("SELECT * FROM sanciones_catalogo WHERE id = ?", (int(catalogo_id),)).fetchone()
    if not tarjeta or not catalogo:
        flash("La roja o el motivo seleccionados no son válidos.")
        return redirect(request.referrer or url_for("sanciones.sanciones_modulo"))

    ya_sancionada = db.execute("SELECT 1 FROM sanciones WHERE tarjeta_id = ?", (tarjeta["id"],)).fetchone()
    if ya_sancionada:
        flash("Esa roja ya tiene una sanción registrada.")
        return redirect(request.referrer or url_for("sanciones.sanciones_modulo"))

    jornada = db.execute("SELECT * FROM jornadas WHERE id = ?", (tarjeta["jornada_id"],)).fetchone()
    if not jornada:
        flash("No se pudo determinar la jornada de esa roja.")
        return redirect(request.referrer or url_for("sanciones.sanciones_modulo"))

    valor_multa = catalogo["valor_multa_sugerido"] if catalogo["aplica_multa"] else None

    db.execute(
        """INSERT INTO sanciones (jugador_id, motivo, jornadas_sancionado, jornada_desde_id,
           jornada_desde_numero, categoria, division, valor_multa, pagada, fecha, origen, catalogo_id, tarjeta_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'manual', ?, ?)""",
        (tarjeta["jugador_id"], catalogo["descripcion_motivo"], catalogo["cantidad_fechas_suspension"],
         jornada["id"], jornada["numero"] + 1, jornada["categoria"], jornada["division"],
         valor_multa, datetime.now().strftime("%Y-%m-%d %H:%M"), int(catalogo_id), tarjeta["id"]),
    )
    db.commit()
    flash("Roja directa registrada: la sanción se calculó automáticamente.", "ok")
    
    # Redirigir a la misma categoría y división donde estaba el usuario
    return redirect(url_for("sanciones.sanciones_modulo", categoria=jornada["categoria"], division=jornada["division"]))


@bp.route("/sanciones/sancion/<int:sancion_id>/eliminar", methods=["POST"])
@sanciones_required
def eliminar_sancion(sancion_id):
    db = get_db()
    sancion = db.execute("SELECT categoria, division FROM sanciones WHERE id = ?", (sancion_id,)).fetchone()
    db.execute("DELETE FROM sanciones WHERE id = ?", (sancion_id,))
    db.commit()
    flash("Sanción eliminada.", "ok")
    if sancion:
        return redirect(url_for("sanciones.sanciones_modulo", categoria=sancion["categoria"], division=sancion["division"]))
    return redirect(url_for("sanciones.sanciones_modulo"))


@bp.route("/sanciones/sancion/<int:sancion_id>/pagada", methods=["POST"])
@sanciones_required
def marcar_sancion_pagada(sancion_id):
    db = get_db()
    sancion = db.execute("SELECT * FROM sanciones WHERE id = ?", (sancion_id,)).fetchone()
    if not sancion:
        flash("Sanción no encontrada.")
        return redirect(url_for("sanciones.sanciones_modulo"))
    nuevo = 0 if sancion["pagada"] else 1
    db.execute("UPDATE sanciones SET pagada = ? WHERE id = ?", (nuevo, sancion_id))
    db.commit()
    flash("Estado de pago actualizado.", "ok")
    return redirect(url_for("sanciones.sanciones_modulo", categoria=sancion["categoria"], division=sancion["division"]))


@bp.route("/sanciones/catalogo")
@sanciones_required
def catalogo_sanciones():
    db = get_db()
    catalogo = db.execute("SELECT * FROM sanciones_catalogo ORDER BY articulo, id").fetchall()
    return render_template("sanciones/catalogo_sanciones.html", catalogo=catalogo)


@bp.route("/sanciones/catalogo/agregar", methods=["POST"])
@sanciones_required
def agregar_catalogo():
    db = get_db()
    articulo = request.form.get("articulo", "").strip()
    descripcion_motivo = request.form.get("descripcion_motivo", "").strip()
    cantidad_fechas_suspension = request.form.get("cantidad_fechas_suspension", "1").strip()
    aplica_multa = 1 if request.form.get("aplica_multa") == "1" else 0
    valor_multa_sugerido = _to_float(request.form.get("valor_multa_sugerido", "0")) if aplica_multa else None

    if not descripcion_motivo or not cantidad_fechas_suspension.isdigit() or int(cantidad_fechas_suspension) < 1:
        flash("Ingresa la descripción del motivo y una cantidad de fechas de suspensión válida.")
        return redirect(url_for("sanciones.catalogo_sanciones"))

    db.execute(
        """INSERT INTO sanciones_catalogo (articulo, descripcion_motivo, cantidad_fechas_suspension,
           aplica_multa, valor_multa_sugerido) VALUES (?, ?, ?, ?, ?)""",
        (articulo or None, descripcion_motivo, int(cantidad_fechas_suspension), aplica_multa, valor_multa_sugerido),
    )
    db.commit()
    flash("Motivo agregado al catálogo.", "ok")
    return redirect(url_for("sanciones.catalogo_sanciones"))


@bp.route("/sanciones/catalogo/<int:catalogo_id>/editar", methods=["POST"])
@sanciones_required
def editar_catalogo(catalogo_id):
    db = get_db()
    articulo = request.form.get("articulo", "").strip()
    descripcion_motivo = request.form.get("descripcion_motivo", "").strip()
    cantidad_fechas_suspension = request.form.get("cantidad_fechas_suspension", "1").strip()
    aplica_multa = 1 if request.form.get("aplica_multa") == "1" else 0
    valor_multa_sugerido = _to_float(request.form.get("valor_multa_sugerido", "0")) if aplica_multa else None

    if not descripcion_motivo or not cantidad_fechas_suspension.isdigit() or int(cantidad_fechas_suspension) < 1:
        flash("Ingresa la descripción del motivo y una cantidad de fechas de suspensión válida.")
        return redirect(url_for("sanciones.catalogo_sanciones"))

    db.execute(
        """UPDATE sanciones_catalogo SET articulo = ?, descripcion_motivo = ?, cantidad_fechas_suspension = ?,
           aplica_multa = ?, valor_multa_sugerido = ? WHERE id = ?""",
        (articulo or None, descripcion_motivo, int(cantidad_fechas_suspension), aplica_multa,
         valor_multa_sugerido, catalogo_id),
    )
    db.commit()
    flash("Motivo del catálogo actualizado.", "ok")
    return redirect(url_for("sanciones.catalogo_sanciones"))


@bp.route("/sanciones/catalogo/<int:catalogo_id>/eliminar", methods=["POST"])
@sanciones_required
def eliminar_catalogo(catalogo_id):
    db = get_db()
    db.execute("DELETE FROM sanciones_catalogo WHERE id = ?", (catalogo_id,))
    db.commit()
    flash("Motivo eliminado del catálogo.", "ok")
    return redirect(url_for("sanciones.catalogo_sanciones"))
