"""Comisión de Calificación: calificar jugadores en lote."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.database import get_db
from app.decorators import calificacion_required
from app.utils import formatear_fecha_hora

bp = Blueprint("comision", __name__)


@bp.route("/comision")
@calificacion_required
def comision_modulo():
    db = get_db()
    jugadores_raw = db.execute(
        "SELECT * FROM jugadores ORDER BY equipo, apellidos, nombres"
    ).fetchall()
    jugadores = []
    for row in jugadores_raw:
        j = dict(row)
        campeonato = j.get("categoria", "")
        if j.get("subcategoria") == "Juvenil":
            campeonato += " - Juvenil"
        numero = (j.get("numero_camiseta") or "").strip()
        jugadores.append({
            "id": j.get("id"), "equipo": j.get("equipo"), "campeonato": campeonato,
            "numero_camiseta": int(numero) if numero.isdigit() else None,
            "cedula": j.get("cedula"), "nombres": j.get("nombres"), "apellidos": j.get("apellidos"),
            "calificado": bool(j.get("calificado")),
            "reemplazo": bool(j.get("reemplazo_solicitado")),
            "inscrito": formatear_fecha_hora(j.get("fecha_registro")),
        })
    total = len(jugadores)
    calificados = sum(1 for j in jugadores if j["calificado"])
    reemplazos = sum(1 for j in jugadores if j["reemplazo"])

    return render_template(
        "comision/comision_modulo.html",
        jugadores=jugadores,
        total=total,
        calificados=calificados,
        reemplazos=reemplazos,
    )


@bp.route("/comision/calificar_lote", methods=["POST"])
@calificacion_required
def calificar_lote():
    db = get_db()
    jugador_ids = [int(x) for x in request.form.getlist("jugador_id") if x.isdigit()]
    accion = request.form.get("accion", "calificar")
    nuevo_estado = 1 if accion == "calificar" else 0
    if not jugador_ids:
        flash("Selecciona al menos un jugador en la tabla.")
        return redirect(url_for("comision.comision_modulo"))
    placeholders = ",".join("?" * len(jugador_ids))
    db.execute(
        f"UPDATE jugadores SET calificado = ? WHERE id IN ({placeholders})",
        (nuevo_estado, *jugador_ids),
    )
    db.commit()
    mensaje = "Jugadores calificados correctamente." if nuevo_estado else "Se quitó la calificación de los jugadores seleccionados."
    flash(mensaje, "ok")
    return redirect(url_for("comision.comision_modulo"))
