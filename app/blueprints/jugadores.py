"""Ficha del jugador: edición, documentos, calificación, carnet y baja."""
import io

from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, session, url_for

from config import CAMPOS_FOTO_VALIDOS, SUBCATEGORIAS
from app.database import get_db
from app.decorators import calificacion_required, jugador_permitido, login_required
from app.services.carnets import _carnet_response, _generar_carnet
from app.services.jugadores import (
    _guardar_imagen_subida, _jugador_califica, _jugadores_que_ya_jugaron, _subcategoria_por_nacimiento,
    _validar_dorsal_unico,
)
from app.services.liga import _contar_juveniles, _edad_minima_categoria, _limite_juveniles_categoria
from app.utils import _calcular_edad, _mayuscula, ahora_ecuador

bp = Blueprint("jugadores", __name__)


@bp.route("/api/cedula_existe")
@login_required
def api_cedula_existe():
    """Consulta rápida (para avisar en el formulario antes de guardar) si la
    cédula ya está inscrita. Con `categoria`, "existe" significa inscrita en
    ESE campeonato (no se puede repetir); si solo está en otros campeonatos se
    devuelven sus datos en `en_otro_torneo` para autocompletar el formulario."""
    cedula = request.args.get("cedula", "").strip()
    categoria = request.args.get("categoria", "").strip()
    if not cedula:
        return jsonify({"existe": False})
    db = get_db()
    filas = db.execute(
        "SELECT nombres, apellidos, equipo, categoria, fecha_nacimiento FROM jugadores WHERE cedula = ? ORDER BY id",
        (cedula,),
    ).fetchall()
    mismo_torneo = [f for f in filas if not categoria or f["categoria"] == categoria]
    if mismo_torneo:
        f = mismo_torneo[0]
        return jsonify({"existe": True, "nombres": f["nombres"], "apellidos": f["apellidos"],
                        "equipo": f["equipo"], "categoria": f["categoria"]})
    if filas:
        f = filas[0]
        return jsonify({"existe": False, "en_otro_torneo": {
            "nombres": f["nombres"], "apellidos": f["apellidos"], "equipo": f["equipo"],
            "categoria": f["categoria"], "fecha_nacimiento": f["fecha_nacimiento"],
        }})
    return jsonify({"existe": False})


@bp.route("/jugador/<int:jugador_id>", methods=["GET"])
@login_required
def ficha_jugador(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("main.index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("main.index"))
    edad = _calcular_edad(jugador["fecha_nacimiento"])
    equipo_row = db.execute("SELECT id FROM equipos WHERE nombre = ?", (jugador["equipo"],)).fetchone()
    equipo_id = equipo_row["id"] if equipo_row else None
    edad_minima = _edad_minima_categoria(db, jugador["categoria"])
    return render_template(
        "jugadores/ficha_jugador.html", jugador=jugador, edad=edad, subcategorias=SUBCATEGORIAS, equipo_id=equipo_id,
        edad_minima=edad_minima,
    )


@bp.route("/jugador/<int:jugador_id>/actualizar", methods=["POST"])
@login_required
def actualizar_jugador(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("main.index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("main.index"))

    if jugador["calificado"] and session.get("rol") != "admin":
        flash("Este jugador ya fue calificado y no se puede modificar. Contacta a la Comisión de Calificación.")
        return redirect(url_for("jugadores.ficha_jugador", jugador_id=jugador_id))

    nombres = _mayuscula(request.form.get("nombres", "")) or jugador["nombres"]
    apellidos = _mayuscula(request.form.get("apellidos", "")) or jugador["apellidos"]
    fecha_nacimiento = request.form.get("fecha_nacimiento", "").strip() or jugador["fecha_nacimiento"]
    numero_camiseta = request.form.get("numero_camiseta", "").strip()
    subcategoria = _subcategoria_por_nacimiento(fecha_nacimiento, jugador["categoria"])

    if not _jugador_califica(db, fecha_nacimiento, jugador["categoria"]):
        flash("Cédula no califica: no cumple con la edad mínima de este campeonato.")
        return redirect(url_for("jugadores.ficha_jugador", jugador_id=jugador_id))

    error_dorsal = _validar_dorsal_unico(db, jugador["equipo"], jugador["categoria"], numero_camiseta,
                                         excluir_id=jugador_id)
    if error_dorsal:
        flash(error_dorsal)
        return redirect(url_for("jugadores.ficha_jugador", jugador_id=jugador_id))

    limite_juveniles = _limite_juveniles_categoria(db, jugador["categoria"])
    if (subcategoria == "Juvenil" and jugador["subcategoria"] != "Juvenil" and limite_juveniles is not None
            and _contar_juveniles(db, jugador["equipo"], jugador["categoria"]) >= limite_juveniles):
        flash(f"No se puede cambiar la fecha: el equipo ya alcanzó el cupo máximo de {limite_juveniles} jugadores Juvenil.")
        return redirect(url_for("jugadores.ficha_jugador", jugador_id=jugador_id))

    nuevo_foto = _guardar_imagen_subida(request.files.get("foto"))
    nuevo_cedula_frontal = _guardar_imagen_subida(request.files.get("cedula_frontal"))
    nuevo_cedula_reverso = _guardar_imagen_subida(request.files.get("cedula_reverso"))
    foto_nombre = nuevo_foto or jugador["foto"]
    cedula_frontal = nuevo_cedula_frontal or jugador["cedula_frontal"]
    cedula_reverso = nuevo_cedula_reverso or jugador["cedula_reverso"]
    documentos_fecha = (
        ahora_ecuador().strftime("%Y-%m-%d %H:%M")
        if (nuevo_foto or nuevo_cedula_frontal or nuevo_cedula_reverso)
        else jugador["documentos_fecha"]
    )

    db.execute(
        """UPDATE jugadores SET nombres = ?, apellidos = ?, fecha_nacimiento = ?, subcategoria = ?,
           numero_camiseta = ?, foto = ?, cedula_frontal = ?, cedula_reverso = ?, documentos_fecha = ? WHERE id = ?""",
        (nombres, apellidos, fecha_nacimiento, subcategoria, numero_camiseta, foto_nombre,
         cedula_frontal, cedula_reverso, documentos_fecha, jugador_id),
    )
    db.commit()
    flash("Ficha del jugador actualizada.", "ok")
    return redirect(url_for("jugadores.ficha_jugador", jugador_id=jugador_id))


@bp.route("/jugador/<int:jugador_id>/quitar_foto/<campo>", methods=["POST"])
@login_required
def quitar_foto_jugador(jugador_id, campo):
    if campo not in CAMPOS_FOTO_VALIDOS:
        flash("Documento no válido.")
        return redirect(url_for("main.index"))

    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("main.index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("main.index"))

    if jugador["calificado"] and session.get("rol") != "admin":
        flash("Este jugador ya fue calificado y no se puede modificar. Contacta a la Comisión de Calificación.")
        return redirect(url_for("jugadores.ficha_jugador", jugador_id=jugador_id))

    db.execute(f"UPDATE jugadores SET {campo} = NULL WHERE id = ?", (jugador_id,))
    db.commit()
    flash("Documento eliminado.", "ok")
    return redirect(url_for("jugadores.ficha_jugador", jugador_id=jugador_id))


@bp.route("/jugador/<int:jugador_id>/calificar", methods=["POST"])
@calificacion_required
def calificar_jugador(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("main.index"))
    nuevo_estado = 0 if jugador["calificado"] else 1
    db.execute("UPDATE jugadores SET calificado = ? WHERE id = ?", (nuevo_estado, jugador_id))
    db.commit()
    flash("Jugador calificado correctamente." if nuevo_estado else "Se quitó la calificación del jugador.", "ok")
    return redirect(request.referrer or url_for("jugadores.ficha_jugador", jugador_id=jugador_id))


@bp.route("/jugador/<int:jugador_id>/carnet")
@login_required
def carnet_jugador(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("main.index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("main.index"))
    return _carnet_response(jugador)


@bp.route("/jugador/<int:jugador_id>/carnet.pdf")
@login_required
def carnet_jugador_pdf(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("main.index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("main.index"))

    frente, reverso = _generar_carnet(jugador)
    buf = io.BytesIO()
    frente.save(buf, format="PDF", save_all=True, append_images=[reverso])
    buf.seek(0)
    nombre_archivo = f"carnet_{jugador['cedula']}.pdf"
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=nombre_archivo)


@bp.route("/jugador/<int:jugador_id>/eliminar", methods=["POST"])
@login_required
def eliminar_jugador(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("main.index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("main.index"))
    equipo_id = db.execute("SELECT id FROM equipos WHERE nombre = ?", (jugador["equipo"],)).fetchone()["id"]
    if jugador["calificado"] and session.get("rol") != "admin":
        flash("Este jugador ya fue calificado y no se puede eliminar. Contacta a la Comisión de Calificación.")
        return redirect(url_for("equipos.detalle_equipo", equipo_id=equipo_id))
    db.execute("DELETE FROM jugadores WHERE id = ?", (jugador_id,))
    db.commit()
    flash("Jugador eliminado.", "ok")
    return redirect(url_for("equipos.detalle_equipo", equipo_id=equipo_id))


@bp.route("/jugador/<int:jugador_id>/solicitar_reemplazo", methods=["POST"])
@login_required
def solicitar_reemplazo(jugador_id):
    """Un jugador ya calificado (y con carnet) no se puede borrar ni cambiar
    desde el equipo: el delegado envía una solicitud de reemplazo, que solo
    levanta una bandera para la Comisión. Solo se permite si el jugador
    todavía no jugó ningún partido."""
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("main.index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("main.index"))
    equipo = db.execute("SELECT id FROM equipos WHERE nombre = ?", (jugador["equipo"],)).fetchone()
    destino = url_for("equipos.detalle_equipo", equipo_id=equipo["id"]) if equipo else url_for("main.index")

    if not jugador["calificado"]:
        flash("Este jugador todavía no está calificado: puedes editarlo o eliminarlo directamente.")
    elif jugador["reemplazo_solicitado"]:
        flash("Ya hay una solicitud de reemplazo enviada para este jugador.")
    elif jugador_id in _jugadores_que_ya_jugaron(db, [jugador_id]):
        flash("No se puede solicitar el reemplazo: el jugador ya disputó al menos un partido.")
    else:
        db.execute(
            "UPDATE jugadores SET reemplazo_solicitado = 1, reemplazo_fecha = ? WHERE id = ?",
            (ahora_ecuador().strftime("%Y-%m-%d %H:%M"), jugador_id),
        )
        db.commit()
        flash("Su solicitud ha sido enviada.", "ok")
    return redirect(destino)


@bp.route("/jugador/<int:jugador_id>/reemplazo/atender", methods=["POST"])
@calificacion_required
def atender_reemplazo(jugador_id):
    """La Comisión baja la bandera de reemplazo una vez atendida la solicitud."""
    db = get_db()
    db.execute("UPDATE jugadores SET reemplazo_solicitado = 0 WHERE id = ?", (jugador_id,))
    db.commit()
    flash("Solicitud de reemplazo marcada como atendida.", "ok")
    return redirect(request.referrer or url_for("comision.comision_modulo"))
