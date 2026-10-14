"""Sección pública: consulta libre, sin necesidad de cuenta."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from config import CATEGORIA_ACTIVA
from app.database import get_db
from app.services.estadisticas import _calcular_goleadores, _calcular_tabla_posiciones
from app.services.liga import _categoria_y_division, _categorias_liga, _divisiones_de_categoria
from app.services.partidos import _fixture_completo
from app.services.sanciones import estado_sancion

bp = Blueprint("publico", __name__)


@bp.route("/publico/partido/<int:partido_id>/alineaciones")
def publico_alineaciones(partido_id):
    db = get_db()
    partido = db.execute("SELECT * FROM partidos WHERE id = ?", (partido_id,)).fetchone()
    if not partido:
        flash("Partido no encontrado.")
        return redirect(url_for("publico.publico_inicio"))
    jornada = db.execute("SELECT * FROM jornadas WHERE id = ?", (partido["jornada_id"],)).fetchone()

    def _goles(equipo_nombre):
        return db.execute(
            """SELECT j.id, j.nombres, j.apellidos, j.numero_camiseta, SUM(g.cantidad) AS goles
               FROM goles g JOIN jugadores j ON j.id = g.jugador_id
               WHERE g.partido_id = ? AND j.equipo = ?
               GROUP BY j.id, j.nombres, j.apellidos, j.numero_camiseta
               ORDER BY goles DESC""",
            (partido_id, equipo_nombre),
        ).fetchall()

    def _tarjetas(equipo_nombre):
        # Cada equipo juega a lo más un partido por jornada, así que las
        # tarjetas de esa jornada para jugadores de este equipo son,
        # necesariamente, las de este encuentro.
        if not jornada:
            return []
        return db.execute(
            """SELECT t.tipo, j.nombres, j.apellidos, j.numero_camiseta
               FROM tarjetas t JOIN jugadores j ON j.id = t.jugador_id
               WHERE t.jornada_id = ? AND j.equipo = ?
               ORDER BY t.fecha""",
            (jornada["id"], equipo_nombre),
        ).fetchall()

    asistencia_local = db.execute(
        """SELECT j.nombres, j.apellidos, j.numero_camiseta
           FROM vocalia_asistencia va JOIN jugadores j ON j.id = va.jugador_id
           WHERE va.partido_id = ? AND va.participo = 1 AND j.equipo = ?
           ORDER BY j.apellidos, j.nombres""",
        (partido_id, partido["equipo_local"]),
    ).fetchall()
    asistencia_visitante = db.execute(
        """SELECT j.nombres, j.apellidos, j.numero_camiseta
           FROM vocalia_asistencia va JOIN jugadores j ON j.id = va.jugador_id
           WHERE va.partido_id = ? AND va.participo = 1 AND j.equipo = ?
           ORDER BY j.apellidos, j.nombres""",
        (partido_id, partido["equipo_visitante"]),
    ).fetchall()
    incidentes = db.execute(
        "SELECT * FROM vocalia_incidentes WHERE partido_id = ? ORDER BY fecha", (partido_id,)
    ).fetchall()
    cambios = db.execute(
        """SELECT c.*, js.apellidos AS sale_apellidos, js.nombres AS sale_nombres, js.numero_camiseta AS sale_numero,
                  je.apellidos AS entra_apellidos, je.nombres AS entra_nombres, je.numero_camiseta AS entra_numero
           FROM vocalia_cambios c
           JOIN jugadores js ON js.id = c.jugador_sale_id
           JOIN jugadores je ON je.id = c.jugador_entra_id
           WHERE c.partido_id = ? ORDER BY c.fecha""",
        (partido_id,),
    ).fetchall()

    return render_template(
        "publico/publico_alineaciones.html",
        partido=partido, jornada=jornada,
        goles_local=_goles(partido["equipo_local"]), goles_visitante=_goles(partido["equipo_visitante"]),
        tarjetas_local=_tarjetas(partido["equipo_local"]),
        tarjetas_visitante=_tarjetas(partido["equipo_visitante"]),
        asistencia_local=asistencia_local, asistencia_visitante=asistencia_visitante,
        incidentes=incidentes, cambios=cambios,
    )


@bp.route("/publico")
def publico_inicio():
    return render_template("publico/publico_inicio.html")


@bp.route("/publico/tabla")
def publico_tabla():
    db = get_db()
    categoria, division = _categoria_y_division(
        db, request.args.get("categoria", CATEGORIA_ACTIVA), request.args.get("division", "")
    )
    tabla = _calcular_tabla_posiciones(db, categoria, division)
    goleadores = _calcular_goleadores(db, categoria, division)
    return render_template(
        "publico/publico_tabla.html", tabla=tabla, goleadores=goleadores, categoria=categoria,
        categorias_liga=_categorias_liga(db), division=division, divisiones=_divisiones_de_categoria(db, categoria),
    )


@bp.route("/publico/calendario")
def publico_calendario():
    db = get_db()
    categoria, division = _categoria_y_division(
        db, request.args.get("categoria", CATEGORIA_ACTIVA), request.args.get("division", "")
    )
    jornadas = _fixture_completo(db, categoria, division)
    return render_template(
        "publico/publico_calendario.html", jornadas=jornadas, categoria=categoria,
        categorias_liga=_categorias_liga(db), division=division, divisiones=_divisiones_de_categoria(db, categoria),
    )


@bp.route("/publico/equipos")
def publico_equipos():
    db = get_db()
    categoria, division = _categoria_y_division(
        db, request.args.get("categoria", CATEGORIA_ACTIVA), request.args.get("division", "")
    )
    equipos = db.execute(
        "SELECT * FROM equipos WHERE categoria = ? AND division = ? ORDER BY nombre", (categoria, division)
    ).fetchall()
    conteos = {}
    for e in equipos:
        conteos[e["nombre"]] = db.execute(
            "SELECT COUNT(*) c FROM jugadores WHERE equipo = ? AND categoria = ?",
            (e["nombre"], categoria),
        ).fetchone()["c"]
    return render_template(
        "publico/publico_equipos.html", equipos=equipos, conteos=conteos, categoria=categoria,
        categorias_liga=_categorias_liga(db), division=division, divisiones=_divisiones_de_categoria(db, categoria),
    )


@bp.route("/publico/jugadores")
def publico_jugadores():
    db = get_db()
    categoria, division = _categoria_y_division(
        db, request.args.get("categoria", CATEGORIA_ACTIVA), request.args.get("division", "")
    )
    # Solo datos que pueden verse públicamente: sin cédula.
    jugadores = db.execute(
        """SELECT nombres, apellidos, equipo, categoria, subcategoria, numero_camiseta, calificado, foto
           FROM jugadores WHERE categoria = ? AND division = ? ORDER BY equipo, apellidos, nombres""",
        (categoria, division),
    ).fetchall()
    return render_template(
        "publico/publico_jugadores.html", jugadores=jugadores, categoria=categoria,
        categorias_liga=_categorias_liga(db), division=division, divisiones=_divisiones_de_categoria(db, categoria),
    )


@bp.route("/publico/sancionados")
def publico_sancionados():
    db = get_db()
    categoria, division = _categoria_y_division(
        db, request.args.get("categoria", CATEGORIA_ACTIVA), request.args.get("division", "")
    )
    sanciones = db.execute(
        """SELECT s.*, j.nombres AS j_nombres, j.apellidos AS j_apellidos, j.equipo AS j_equipo
           FROM sanciones s
           JOIN jugadores j ON j.id = s.jugador_id
           WHERE s.categoria = ? AND s.division = ?
           ORDER BY s.jornada_desde_numero DESC, s.id DESC""",
        (categoria, division),
    ).fetchall()
    estados = {s["id"]: estado_sancion(db, s, equipo=s["j_equipo"]) for s in sanciones}
    sancionados_activos = [s for s in sanciones if estados[s["id"]]["activa"]]
    return render_template(
        "publico/publico_sancionados.html", sancionados=sancionados_activos, estados=estados, categoria=categoria,
        categorias_liga=_categorias_liga(db), division=division, divisiones=_divisiones_de_categoria(db, categoria),
    )
