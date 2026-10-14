"""Equipos: alta/baja, accesos del delegado, detalle, alineaciones, pagos y alta de jugadores."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from config import CATEGORIA_ACTIVA, CUPO_MAXIMO_EQUIPO, FORMAS_PAGO_VALIDAS
from app.database import IntegrityError, get_db
from app.decorators import admin_required, equipo_permitido, login_required
from app.services.alineaciones import FORMACIONES, _formacion_valida, _guardar_alineacion, _obtener_alineacion
from app.services.equipos import _renombrar_equipo_cascada
from app.services.exportacion import _exportar_jugadores_excel
from app.services.jugadores import _guardar_imagen_subida, _insertar_jugador, _jugadores_que_ya_jugaron
from app.services.liga import (
    _categoria_y_division, _contar_juveniles, _edad_minima_categoria, _limite_juveniles_categoria,
)
from app.utils import _mayuscula, _to_float

bp = Blueprint("equipos", __name__)


@bp.route("/equipos/agregar", methods=["POST"])
@admin_required
def agregar_equipo():
    db = get_db()
    nombre = _mayuscula(request.form.get("nombre", ""))
    categoria, division = _categoria_y_division(
        db, request.form.get("categoria", CATEGORIA_ACTIVA), request.form.get("division", "")
    )
    if nombre:
        try:
            db.execute(
                "INSERT INTO equipos (nombre, categoria, division) VALUES (?, ?, ?)",
                (nombre, categoria, division),
            )
            db.commit()
            flash(f"Equipo '{nombre}' agregado.", "ok")
        except IntegrityError:
            db.rollback()
            flash(f"Ya existe un equipo llamado '{nombre}'.")
    return redirect(url_for("inscripcion.inscripcion", categoria=categoria, division=division))


@bp.route("/equipos/<int:equipo_id>/renombrar", methods=["POST"])
@admin_required
def renombrar_equipo(equipo_id):
    db = get_db()
    nuevo_nombre = _mayuscula(request.form.get("nombre", ""))
    if nuevo_nombre:
        actual = db.execute("SELECT nombre FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
        if actual:
            try:
                db.execute("UPDATE equipos SET nombre = ? WHERE id = ?", (nuevo_nombre, equipo_id))
                _renombrar_equipo_cascada(db, actual["nombre"], nuevo_nombre)
                db.commit()
                flash(f"Equipo renombrado a '{nuevo_nombre}'.", "ok")
            except IntegrityError:
                db.rollback()
                flash(f"Ya existe un equipo llamado '{nuevo_nombre}'.")
    return redirect(url_for("inscripcion.inscripcion"))


@bp.route("/equipos/<int:equipo_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_equipo(equipo_id):
    db = get_db()
    equipo = db.execute("SELECT nombre FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    if equipo:
        jugadores_count = db.execute(
            "SELECT COUNT(*) c FROM jugadores WHERE equipo = ?", (equipo["nombre"],)
        ).fetchone()["c"]
        if jugadores_count > 0:
            flash(f"No se puede eliminar '{equipo['nombre']}': tiene {jugadores_count} jugador(es) inscritos.")
        else:
            db.execute("DELETE FROM equipos WHERE id = ?", (equipo_id,))
            db.commit()
            flash(f"Equipo '{equipo['nombre']}' eliminado.", "ok")
    return redirect(url_for("inscripcion.inscripcion"))


@bp.route("/equipos/<int:equipo_id>/credenciales", methods=["POST"])
@admin_required
def credenciales_equipo(equipo_id):
    db = get_db()
    usuario = request.form.get("usuario", "").strip().lower()
    clave = request.form.get("clave", "").strip()
    if not (usuario and clave):
        flash("Usuario y clave son obligatorios.")
    else:
        try:
            db.execute("UPDATE equipos SET usuario = ?, clave = ? WHERE id = ?", (usuario, clave, equipo_id))
            db.commit()
            flash(f"Acceso del equipo actualizado: usuario '{usuario}'.", "ok")
        except IntegrityError:
            db.rollback()
            flash(f"El usuario '{usuario}' ya está en uso por otro equipo.")
    return redirect(url_for("equipos.detalle_equipo", equipo_id=equipo_id))


@bp.route("/mi_equipo/cambiar_clave", methods=["POST"])
@login_required
def cambiar_clave_equipo():
    """El delegado del equipo cambia su propia clave de acceso, a la que
    prefiera. El administrador conserva acceso total de todas formas (puede
    ver y volver a cambiar la clave de cualquier equipo desde su panel)."""
    if session.get("rol") != "equipo":
        flash("Esta opción es solo para el acceso de delegado de equipo.")
        return redirect(url_for("main.index"))

    equipo_id = session.get("equipo_id")
    nueva_clave = request.form.get("nueva_clave", "").strip()
    confirmar_clave = request.form.get("confirmar_clave", "").strip()

    if not nueva_clave or len(nueva_clave) < 4:
        flash("La nueva clave debe tener al menos 4 caracteres.")
    elif nueva_clave != confirmar_clave:
        flash("Las dos claves no coinciden.")
    else:
        db = get_db()
        db.execute("UPDATE equipos SET clave = ? WHERE id = ?", (nueva_clave, equipo_id))
        db.commit()
        flash("Tu clave de acceso se actualizó correctamente.", "ok")

    return redirect(url_for("equipos.detalle_equipo", equipo_id=equipo_id))


@bp.route("/equipos/<int:equipo_id>/credenciales/quitar", methods=["POST"])
@admin_required
def quitar_credenciales_equipo(equipo_id):
    db = get_db()
    db.execute("UPDATE equipos SET usuario = NULL, clave = NULL WHERE id = ?", (equipo_id,))
    db.commit()
    flash("Se quitó el acceso del delegado para este equipo.", "ok")
    return redirect(url_for("equipos.detalle_equipo", equipo_id=equipo_id))


@bp.route("/equipo/<int:equipo_id>", methods=["GET"])
@login_required
def detalle_equipo(equipo_id):
    db = get_db()
    equipo = db.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    if not equipo:
        flash("Equipo no encontrado.")
        return redirect(url_for("main.index"))

    if not equipo_permitido(equipo_id):
        flash("No tienes acceso a ese equipo.")
        return redirect(url_for("main.index"))

    jugadores = db.execute(
        "SELECT * FROM jugadores WHERE equipo = ? AND categoria = ? ORDER BY CAST(numero_camiseta AS INTEGER)",
        (equipo["nombre"], equipo["categoria"]),
    ).fetchall()
    saldo = equipo["valor_inscripcion"] - equipo["abono"]
    juveniles_count = _contar_juveniles(db, equipo["nombre"], equipo["categoria"])

    partidos_equipo = []
    for jr in db.execute(
        "SELECT * FROM jornadas WHERE categoria = ? AND division = ? ORDER BY numero, id",
        (equipo["categoria"], equipo["division"]),
    ).fetchall():
        partido = db.execute(
            "SELECT * FROM partidos WHERE jornada_id = ? AND (equipo_local = ? OR equipo_visitante = ?)",
            (jr["id"], equipo["nombre"], equipo["nombre"]),
        ).fetchone()
        descansa = db.execute(
            "SELECT * FROM descansos WHERE jornada_id = ? AND equipo = ?", (jr["id"], equipo["nombre"])
        ).fetchone()
        if partido:
            rival = partido["equipo_visitante"] if partido["equipo_local"] == equipo["nombre"] else partido["equipo_local"]
            local = partido["equipo_local"] == equipo["nombre"]
            partidos_equipo.append({
                "jornada": jr, "rival": rival, "local": local,
                "hora": partido["hora"], "fecha": partido["fecha"],
                "partido_id": partido["id"],
            })
        elif descansa:
            partidos_equipo.append({"jornada": jr, "rival": None, "local": None, "hora": None, "fecha": None, "partido_id": None})

    return render_template(
        "equipos/detalle_equipo.html",
        equipo=equipo,
        jugadores=jugadores,
        saldo=saldo,
        cupo_maximo=CUPO_MAXIMO_EQUIPO,
        categoria=equipo["categoria"],
        edad_minima=_edad_minima_categoria(db, equipo["categoria"]),
        juveniles_count=juveniles_count,
        cupo_maximo_juvenil=_limite_juveniles_categoria(db, equipo["categoria"]),
        partidos_equipo=partidos_equipo,
        ya_jugaron=_jugadores_que_ya_jugaron(db, [j["id"] for j in jugadores]),
    )


@bp.route("/equipo/<int:equipo_id>/partido/<int:partido_id>/alineacion", methods=["GET"])
@login_required
def alineacion_equipo(equipo_id, partido_id):
    if not equipo_permitido(equipo_id):
        flash("No tienes acceso a ese equipo.")
        return redirect(url_for("main.index"))
    db = get_db()
    equipo = db.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    if not equipo:
        flash("Equipo no encontrado.")
        return redirect(url_for("main.index"))

    partido = db.execute("SELECT * FROM partidos WHERE id = ?", (partido_id,)).fetchone()
    if not partido or equipo["nombre"] not in (partido["equipo_local"], partido["equipo_visitante"]):
        flash("Ese partido no corresponde a este equipo.")
        return redirect(url_for("equipos.detalle_equipo", equipo_id=equipo_id))
    rival = partido["equipo_visitante"] if partido["equipo_local"] == equipo["nombre"] else partido["equipo_local"]

    existente = _obtener_alineacion(db, partido_id, equipo["nombre"])
    formacion = _formacion_valida(request.args.get("formacion", existente["formacion"] if existente else "4-3-3"))
    slots = FORMACIONES[formacion]

    jugadores = db.execute(
        "SELECT * FROM jugadores WHERE equipo = ? ORDER BY apellidos, nombres", (equipo["nombre"],)
    ).fetchall()

    seleccion = {}
    suplentes_ids = set()
    if existente:
        suplentes_ids = {j["id"] for j in existente["suplentes"]}
        if existente["formacion"] == formacion:
            seleccion = {pos: j["id"] for pos, j in existente["titulares"].items()}
        else:
            # cambió de formación: los que eran titulares pasan a quedar disponibles otra vez
            suplentes_ids |= {j["id"] for j in existente["titulares"].values()}

    return render_template(
        "equipos/alineacion_equipo.html",
        equipo=equipo, partido=partido, rival=rival,
        formaciones=list(FORMACIONES.keys()), formacion=formacion, slots=slots,
        jugadores=jugadores, seleccion=seleccion, suplentes_ids=suplentes_ids,
        tiene_alineacion=existente is not None,
    )


@bp.route("/equipo/<int:equipo_id>/partido/<int:partido_id>/alineacion/guardar", methods=["POST"])
@login_required
def guardar_alineacion(equipo_id, partido_id):
    if not equipo_permitido(equipo_id):
        flash("No tienes acceso a ese equipo.")
        return redirect(url_for("main.index"))
    db = get_db()
    equipo = db.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    partido = db.execute("SELECT * FROM partidos WHERE id = ?", (partido_id,)).fetchone()
    if not equipo or not partido or equipo["nombre"] not in (partido["equipo_local"], partido["equipo_visitante"]):
        flash("Ese partido no corresponde a este equipo.")
        return redirect(url_for("main.index"))

    formacion = _formacion_valida(request.form.get("formacion", "4-3-3"))
    slots = FORMACIONES[formacion]

    ids_validos = {
        j["id"] for j in db.execute("SELECT id FROM jugadores WHERE equipo = ?", (equipo["nombre"],)).fetchall()
    }

    titulares = []
    usados = set()
    for slot in slots:
        raw = request.form.get(f"pos_{slot['code']}", "").strip()
        if not raw.isdigit():
            continue
        jugador_id = int(raw)
        if jugador_id not in ids_validos or jugador_id in usados:
            continue
        titulares.append((slot["code"], jugador_id))
        usados.add(jugador_id)

    suplentes = []
    for raw in request.form.getlist("suplentes"):
        if raw.isdigit():
            jugador_id = int(raw)
            if jugador_id in ids_validos and jugador_id not in usados:
                suplentes.append(jugador_id)
                usados.add(jugador_id)

    if not titulares:
        flash("Selecciona al menos un jugador titular.")
        return redirect(url_for("equipos.alineacion_equipo", equipo_id=equipo_id, partido_id=partido_id, formacion=formacion))

    _guardar_alineacion(db, partido_id, equipo["nombre"], formacion, titulares, suplentes)
    flash("Alineación guardada.", "ok")
    return redirect(url_for("equipos.alineacion_equipo", equipo_id=equipo_id, partido_id=partido_id, formacion=formacion))


@bp.route("/equipo/<int:equipo_id>/exportar")
@login_required
def exportar_equipo(equipo_id):
    db = get_db()
    equipo = db.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    if not equipo:
        flash("Equipo no encontrado.")
        return redirect(url_for("main.index"))
    if not equipo_permitido(equipo_id):
        flash("No tienes acceso a ese equipo.")
        return redirect(url_for("main.index"))

    jugadores = db.execute(
        "SELECT * FROM jugadores WHERE equipo = ? AND categoria = ? ORDER BY apellidos",
        (equipo["nombre"], equipo["categoria"]),
    ).fetchall()
    nombre_archivo = f"jugadores_{equipo['nombre'].replace(' ', '_')}.xlsx"
    return _exportar_jugadores_excel(jugadores, nombre_archivo)


@bp.route("/equipo/<int:equipo_id>/pago", methods=["POST"])
@admin_required
def actualizar_pago_equipo(equipo_id):
    db = get_db()
    valor_inscripcion = _to_float(request.form.get("valor_inscripcion", "0"))
    abono = _to_float(request.form.get("abono", "0"))
    forma_pago = request.form.get("forma_pago", "Efectivo").strip()
    if forma_pago not in FORMAS_PAGO_VALIDAS:
        forma_pago = "Efectivo"
    comprobante_pago = request.form.get("comprobante_pago", "").strip()
    db.execute(
        "UPDATE equipos SET valor_inscripcion = ?, abono = ?, forma_pago = ?, comprobante_pago = ? WHERE id = ?",
        (valor_inscripcion, abono, forma_pago, comprobante_pago, equipo_id),
    )
    db.commit()
    flash("Datos de pago actualizados.", "ok")
    return redirect(url_for("equipos.detalle_equipo", equipo_id=equipo_id))


@bp.route("/equipo/<int:equipo_id>/agregar_jugador", methods=["POST"])
@login_required
def agregar_jugador_equipo(equipo_id):
    db = get_db()
    equipo = db.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    if not equipo:
        flash("Equipo no encontrado.")
        return redirect(url_for("main.index"))
    if not equipo_permitido(equipo_id):
        flash("No tienes acceso a ese equipo.")
        return redirect(url_for("main.index"))

    foto = _guardar_imagen_subida(request.files.get("foto"))
    cedula_frontal = _guardar_imagen_subida(request.files.get("cedula_frontal"))
    cedula_reverso = _guardar_imagen_subida(request.files.get("cedula_reverso"))

    jugador_id, error = _insertar_jugador(
        db,
        equipo["nombre"],
        request.form.get("cedula", "").strip(),
        request.form.get("nombres", "").strip(),
        request.form.get("apellidos", "").strip(),
        request.form.get("fecha_nacimiento", "").strip(),
        equipo["categoria"],
        request.form.get("numero_camiseta", "").strip(),
        foto=foto,
        cedula_frontal=cedula_frontal,
        cedula_reverso=cedula_reverso,
    )
    if error:
        flash(error)
    else:
        flash("Jugador registrado correctamente.", "ok")
    return redirect(url_for("equipos.detalle_equipo", equipo_id=equipo_id))


# (Asegúrate de que esta ruta esté en tu app.py)
@bp.route("/equipo/<int:equipo_id>/jugador/nuevo", methods=["GET"])
@login_required # Usamos login_required en vez de admin_required para que el delegado también pueda entrar
def nuevo_jugador_vista(equipo_id):
    # Validamos permisos (solo admin o el propio delegado del equipo)
    if session.get('rol') != 'admin' and session.get('equipo_id') != equipo_id:
        flash("No tienes permiso para inscribir jugadores en este equipo.")
        return redirect(url_for('main.index'))

    db = get_db()
    equipo = db.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    if not equipo:
        flash("Equipo no encontrado.")
        return redirect(url_for('inscripcion.inscripcion'))

    # Se necesita la edad_minima para las validaciones del frontend
    edad_minima = _edad_minima_categoria(db, equipo["categoria"])

    return render_template(
        "equipos/nuevo_jugador.html", 
        equipo=equipo, 
        categoria=equipo['categoria'],
        edad_minima=edad_minima
    )
