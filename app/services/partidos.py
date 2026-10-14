"""Fixture: jornadas, partidos y descansos."""
from config import CATEGORIA_ACTIVA


def _fixture_completo(db, categoria=CATEGORIA_ACTIVA, division=""):
    jornadas_rows = db.execute(
        "SELECT * FROM jornadas WHERE categoria = ? AND division = ? ORDER BY numero, id",
        (categoria, division),
    ).fetchall()
    jornadas = []
    for jr in jornadas_rows:
        partidos = db.execute(
            "SELECT * FROM partidos WHERE jornada_id = ? ORDER BY id", (jr["id"],)
        ).fetchall()
        descansos = db.execute(
            "SELECT * FROM descansos WHERE jornada_id = ? ORDER BY id", (jr["id"],)
        ).fetchall()
        jornadas.append({"jornada": jr, "partidos": partidos, "descansos": descansos})
    return jornadas


def _categoria_de_partido(db, partido_id):
    fila = db.execute(
        "SELECT jo.categoria AS categoria, jo.division AS division "
        "FROM partidos p JOIN jornadas jo ON jo.id = p.jornada_id WHERE p.id = ?",
        (partido_id,),
    ).fetchone()
    return (fila["categoria"], fila["division"]) if fila else (CATEGORIA_ACTIVA, "")


def _partidos_en_vivo(db):
    return db.execute(
        """SELECT p.*, jo.numero AS jornada_numero
           FROM partidos p JOIN jornadas jo ON jo.id = p.jornada_id
           WHERE p.en_vivo = 1 ORDER BY p.id DESC"""
    ).fetchall()
