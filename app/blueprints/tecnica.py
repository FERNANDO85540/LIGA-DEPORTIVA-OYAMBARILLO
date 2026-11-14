"""Comisión Técnica: fixture por fase, oficialización de resultados, mesa,
ajuste de puntos y generación de fases (Liguillas y Finales)."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from config import CATEGORIA_ACTIVA, USANDO_POSTGRES
from app.database import get_db
from app.decorators import tecnica_required
from app.services.estadisticas import _ajustes_de_fase, _calcular_goleadores, _calcular_tabla_posiciones
from app.services.fases import (
    DESTINOS_POR_ORIGEN, REGULAR, TIPOS_FASE, config_fases, crear_fase, equipos_de_fase, fase_seleccionada,
    numero_minimo_jornada, obtener_fase, propuesta_de_clasificacion, siguiente_numero_jornada,
)
from app.services.liga import _categoria_y_division, _categorias_liga, _divisiones_de_categoria
from app.services.partidos import _categoria_de_partido, _fixture_completo
from app.utils import ahora_ecuador, volver_a

bp = Blueprint("tecnica", __name__)


def _url_modulo(categoria, division, fase=None):
    if fase is None:
        return url_for("tecnica.tecnica_modulo", categoria=categoria, division=division)
    return url_for("tecnica.tecnica_modulo", categoria=categoria, division=division, fase=fase["clave"])


def _fase_del_formulario(db, categoria, division):
    fase, _ = fase_seleccionada(db, categoria, division, request.form.get("fase", ""), por_defecto=REGULAR)
    return fase


@bp.route("/tecnica/jornada/agregar", methods=["POST"])
@tecnica_required
def agregar_jornada():
    db = get_db()
    categoria, division = _categoria_y_division(
        db, request.form.get("categoria", CATEGORIA_ACTIVA), request.form.get("division", "")
    )
    fase = _fase_del_formulario(db, categoria, division)
    destino = _url_modulo(categoria, division, fase)
    numero = request.form.get("numero", "").strip()
    fecha = request.form.get("fecha", "").strip()
    if not numero.isdigit():
        flash("Ingresa un número de jornada válido.")
        return volver_a(destino)
    minimo = numero_minimo_jornada(db, categoria, division, fase)
    if int(numero) < minimo:
        flash(f"Las jornadas de {fase['nombre']} continúan la numeración del campeonato: "
              f"usa un número desde {minimo} (las suspensiones y la acumulación de tarjetas siguen ese orden).")
        return volver_a(destino)

    equipos_fase = set(equipos_de_fase(db, categoria, division, fase))
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
            return volver_a(destino)
        if local not in equipos_fase or visitante not in equipos_fase:
            flash(f"Solo pueden jugar en {fase['nombre']} los equipos clasificados a esa fase.")
            return volver_a(destino)
        if local in equipos_usados or visitante in equipos_usados:
            flash("Hay un equipo asignado a más de un partido en la misma jornada.")
            return volver_a(destino)
        equipos_usados.add(local)
        equipos_usados.add(visitante)
        partidos_validos.append((local, visitante, hora, fecha_partido))

    for equipo in descansos:
        if equipo in equipos_usados:
            flash(f"'{equipo}' no puede descansar y jugar en la misma jornada.")
            return volver_a(destino)
        if equipo not in equipos_fase:
            flash(f"'{equipo}' no participa en {fase['nombre']}.")
            return volver_a(destino)

    if not partidos_validos and not descansos:
        flash("Agrega al menos un partido o un equipo que descansa.")
        return volver_a(destino)

    returning = " RETURNING id" if USANDO_POSTGRES else ""
    cur = db.execute(
        f"INSERT INTO jornadas (numero, fecha, categoria, division, fase_id) VALUES (?, ?, ?, ?, ?){returning}",
        (int(numero), fecha or None, categoria, division, fase["id"]),
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
    flash(f"Jornada {numero} agregada a {fase['nombre']}.", "ok")
    return volver_a(destino)


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
    fase, fases = fase_seleccionada(db, categoria, division, request.args.get("fase", ""))
    equipos = [{"nombre": n} for n in equipos_de_fase(db, categoria, division, fase)]
    jornadas = _fixture_completo(db, categoria, division, fase)
    tabla = _calcular_tabla_posiciones(db, categoria, division, fase)
    goleadores = _calcular_goleadores(db, categoria, division, limite=10)
    ajustes_puntos = _ajustes_de_fase(db, categoria, division, fase)

    # Generación de la siguiente fase a partir de la tabla de la fase actual.
    tipos_creados = {f["tipo"] for f in fases}
    # Solo se ofrece cuando la fase ya tiene partidos oficializados (evita generarla por error).
    ya_se_jugo = any(f["pj"] for f in tabla)
    destinos = [t for t in DESTINOS_POR_ORIGEN.get(fase["tipo"], ()) if t not in tipos_creados] if ya_se_jugo else []
    config = config_fases(db, categoria, division)
    propuesta = propuesta_de_clasificacion(tabla, fase["tipo"], config) if destinos else {}
    propuesta = {e: (d if d in destinos else "") for e, d in propuesta.items()}
    fases_derivadas = [f for f in fases if fase["id"] is not None and f["fase_origen_id"] == fase["id"]]
    puede_eliminarse = (
        fase["id"] is not None and not jornadas and not fases_derivadas
    )

    return render_template(
        "tecnica/tecnica_modulo.html",
        categoria=categoria,
        categorias_liga=_categorias_liga(db),
        division=division,
        divisiones=_divisiones_de_categoria(db, categoria),
        fase=fase,
        fases=fases,
        equipos=equipos,
        siguiente_numero=siguiente_numero_jornada(db, categoria, division, fase),
        jornadas=jornadas,
        tabla=tabla,
        goleadores=goleadores,
        ajustes_puntos=ajustes_puntos,
        destinos=[(t, TIPOS_FASE[t]["nombre"]) for t in destinos],
        propuesta=propuesta,
        config=config,
        puede_eliminarse=puede_eliminarse,
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


@bp.route("/tecnica/ajuste_puntos", methods=["POST"])
@tecnica_required
def tecnica_ajuste_puntos():
    """Ajuste de Puntos de una fase: negativo = sanción (Comisión de Penas),
    positivo = bonificación (ej. puntos de arrastre al entrar a una Liguilla)."""
    db = get_db()
    categoria, division = _categoria_y_division(
        db, request.form.get("categoria", CATEGORIA_ACTIVA), request.form.get("division", "")
    )
    fase = _fase_del_formulario(db, categoria, division)
    destino = _url_modulo(categoria, division, fase)
    equipo = request.form.get("equipo", "").strip()
    puntos_raw = request.form.get("puntos", "").strip()
    motivo = request.form.get("motivo", "").strip()

    try:
        puntos = int(puntos_raw)
    except ValueError:
        puntos = 0
    if puntos == 0 or not motivo:
        flash("Ingresa un ajuste distinto de cero (negativo para restar, positivo para sumar) y un motivo.")
        return volver_a(destino)
    if equipo not in equipos_de_fase(db, categoria, division, fase):
        flash(f"Selecciona un equipo que participe en {fase['nombre']}.")
        return volver_a(destino)

    db.execute(
        """INSERT INTO puntos_sancion (equipo, categoria, division, puntos_descontar, puntos_ajuste, fase_id, motivo, fecha)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (equipo, categoria, division, max(-puntos, 0), puntos, fase["id"], motivo,
         ahora_ecuador().strftime("%Y-%m-%d %H:%M")),
    )
    db.commit()
    if puntos < 0:
        flash(f"Se restaron {-puntos} puntos a {equipo} en {fase['nombre']}.", "ok")
    else:
        flash(f"Se sumaron {puntos} puntos a {equipo} en {fase['nombre']}.", "ok")
    return volver_a(destino)


@bp.route("/tecnica/ajuste_puntos/<int:ajuste_id>/eliminar", methods=["POST"])
@tecnica_required
def tecnica_eliminar_ajuste_puntos(ajuste_id):
    db = get_db()
    ajuste = db.execute("SELECT categoria, division, fase_id FROM puntos_sancion WHERE id = ?", (ajuste_id,)).fetchone()
    if ajuste:
        db.execute("DELETE FROM puntos_sancion WHERE id = ?", (ajuste_id,))
        db.commit()
        flash("Ajuste de puntos eliminado. La tabla ha sido recalculada.", "ok")
        fase = obtener_fase(db, ajuste["fase_id"])
        return volver_a(_url_modulo(ajuste["categoria"], ajuste["division"], fase))
    return volver_a(url_for("tecnica.tecnica_modulo"))


@bp.route("/tecnica/fases/generar", methods=["POST"])
@tecnica_required
def generar_fase():
    """Genera la(s) siguiente(s) fase(s) a partir de la tabla de la fase de
    origen. No toca nada de la fase de origen: solo crea fases nuevas con sus
    equipos; sus tablas arrancan de cero."""
    db = get_db()
    categoria, division = _categoria_y_division(
        db, request.form.get("categoria", CATEGORIA_ACTIVA), request.form.get("division", "")
    )
    origen = _fase_del_formulario(db, categoria, division)
    destino_url = _url_modulo(categoria, division, origen)
    tipos_creados = {
        f["tipo"] for f in
        db.execute("SELECT tipo FROM fases WHERE categoria = ? AND division = ?", (categoria, division)).fetchall()
    }
    permitidos = [t for t in DESTINOS_POR_ORIGEN.get(origen["tipo"], ()) if t not in tipos_creados]
    if not permitidos:
        flash(f"No hay fases pendientes por generar desde {origen['nombre']}.")
        return volver_a(destino_url)

    tabla = _calcular_tabla_posiciones(db, categoria, division, origen)
    posiciones = {f["equipo"]: i + 1 for i, f in enumerate(tabla)}
    grupos = {}
    for equipo, destino in zip(request.form.getlist("equipo"), request.form.getlist("destino")):
        if not destino:
            continue
        if equipo not in posiciones or destino not in permitidos:
            flash("La clasificación enviada no es válida. Revisa los equipos y las fases elegidas.")
            return volver_a(destino_url)
        grupos.setdefault(destino, []).append((equipo, posiciones[equipo]))

    if not grupos:
        flash("Asigna al menos dos equipos a la nueva fase.")
        return volver_a(destino_url)
    for tipo, equipos in grupos.items():
        if len(equipos) < 2:
            flash(f"{TIPOS_FASE[tipo]['nombre']} necesita al menos 2 equipos.")
            return volver_a(destino_url)

    creadas = []
    primera_id = None
    for tipo in permitidos:  # orden estable: Liguilla Final, No Descenso, Finales
        if tipo in grupos:
            equipos = sorted(grupos[tipo], key=lambda e: e[1])
            fase_id = crear_fase(db, categoria, division, tipo, equipos, fase_origen_id=origen["id"])
            primera_id = primera_id or fase_id
            creadas.append(f"{TIPOS_FASE[tipo]['nombre']} ({len(equipos)} equipos)")
    db.commit()
    flash("Fase(s) generada(s): " + ", ".join(creadas) + f". La tabla de {origen['nombre']} se conserva intacta.", "ok")
    return volver_a(_url_modulo(categoria, division, obtener_fase(db, primera_id)))


@bp.route("/tecnica/fases/<int:fase_id>/eliminar", methods=["POST"])
@tecnica_required
def eliminar_fase(fase_id):
    """Deshace una fase generada por error, solo si todavía no tiene jornadas
    ni otras fases generadas a partir de ella. La Fase Regular no se elimina."""
    db = get_db()
    fila = db.execute("SELECT * FROM fases WHERE id = ?", (fase_id,)).fetchone()
    if not fila:
        flash("Fase no encontrada.")
        return volver_a(url_for("tecnica.tecnica_modulo"))
    categoria, division = fila["categoria"], fila["division"]
    tiene_jornadas = db.execute("SELECT 1 FROM jornadas WHERE fase_id = ?", (fase_id,)).fetchone()
    tiene_derivadas = db.execute("SELECT 1 FROM fases WHERE fase_origen_id = ?", (fase_id,)).fetchone()
    if tiene_jornadas or tiene_derivadas:
        flash(f"No se puede eliminar {fila['nombre']}: ya tiene jornadas o fases generadas a partir de ella.")
        return volver_a(_url_modulo(categoria, division, obtener_fase(db, fase_id)))
    db.execute("DELETE FROM puntos_sancion WHERE fase_id = ?", (fase_id,))
    db.execute("DELETE FROM fase_equipos WHERE fase_id = ?", (fase_id,))
    db.execute("DELETE FROM fases WHERE id = ?", (fase_id,))
    db.commit()
    flash(f"{fila['nombre']} eliminada.", "ok")
    # Se vuelve sin `next`: la vista de origen apuntaba a la fase eliminada.
    return redirect(_url_modulo(categoria, division))
