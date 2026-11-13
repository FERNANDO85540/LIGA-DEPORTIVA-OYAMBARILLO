"""Fixture: jornadas, partidos y descansos."""
from config import CATEGORIA_ACTIVA
from app.services.fases import filtro_jornadas_fase


def _fixture_completo(db, categoria=CATEGORIA_ACTIVA, division="", fase=None):
    """Jornadas del torneo. Con `fase`, solo las de esa fase; sin ella, las de
    todas las fases (cada jornada trae `fase_nombre`), como necesita Vocalía."""
    if fase is not None:
        filtro, params_fase = filtro_jornadas_fase(fase, alias="jornadas")
        filtro = f" AND {filtro}"
    else:
        filtro, params_fase = "", ()
    jornadas_rows = db.execute(
        f"SELECT * FROM jornadas WHERE categoria = ? AND division = ?{filtro} ORDER BY numero, id",
        (categoria, division, *params_fase),
    ).fetchall()
    nombres_fase = {
        f["id"]: f["nombre"] for f in
        db.execute("SELECT id, nombre FROM fases WHERE categoria = ? AND division = ?", (categoria, division)).fetchall()
    }
    jornadas = []
    for jr in jornadas_rows:
        partidos = db.execute(
            "SELECT * FROM partidos WHERE jornada_id = ? ORDER BY id", (jr["id"],)
        ).fetchall()
        descansos = db.execute(
            "SELECT * FROM descansos WHERE jornada_id = ? ORDER BY id", (jr["id"],)
        ).fetchall()
        fase_nombre = nombres_fase.get(jr["fase_id"], "Fase Regular")
        jornadas.append({"jornada": jr, "partidos": partidos, "descansos": descansos, "fase_nombre": fase_nombre})
    return jornadas


def _categoria_de_partido(db, partido_id):
    fila = db.execute(
        "SELECT jo.categoria AS categoria, jo.division AS division "
        "FROM partidos p JOIN jornadas jo ON jo.id = p.jornada_id WHERE p.id = ?",
        (partido_id,),
    ).fetchone()
    return (fila["categoria"], fila["division"]) if fila else (CATEGORIA_ACTIVA, "")
