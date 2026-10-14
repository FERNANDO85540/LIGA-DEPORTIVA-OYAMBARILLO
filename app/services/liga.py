"""Campeonatos (categorías) y sus divisiones/series."""
from config import CATEGORIA_ACTIVA


def _categorias_liga(db):
    """Lista de nombres de categorías, en el orden en que se crearon.
    Editable por el admin desde /categorias -- no está fija en el código."""
    return [f["nombre"] for f in db.execute("SELECT nombre FROM categorias ORDER BY id").fetchall()]


def _categoria_valida(db, categoria):
    return categoria if categoria in _categorias_liga(db) else CATEGORIA_ACTIVA


def _edad_minima_categoria(db, categoria):
    fila = db.execute("SELECT edad_minima FROM categorias WHERE nombre = ?", (categoria,)).fetchone()
    return fila["edad_minima"] if fila else None


def _limite_juveniles_categoria(db, categoria):
    """Tope de jugadores Juvenil por equipo en este campeonato. None = sin límite (ilimitado)."""
    fila = db.execute("SELECT limite_juveniles FROM categorias WHERE nombre = ?", (categoria,)).fetchone()
    return fila["limite_juveniles"] if fila else None


def _divisiones_de_categoria(db, categoria):
    """Nombres de las divisiones/series de una categoría (ej. Senior -> Máxima,
    Primera), en el orden en que se crearon. Lista vacía si esa categoría no
    se divide en series (ej. Sub 45)."""
    return [
        f["nombre"] for f in
        db.execute("SELECT nombre FROM divisiones WHERE categoria = ? ORDER BY id", (categoria,)).fetchall()
    ]


def _categoria_y_division(db, categoria_arg, division_arg):
    """Valida la categoría pedida y, si esa categoría tiene divisiones, la
    división pedida (o la primera por defecto). Si la categoría no tiene
    divisiones, la división siempre es '' (no aplica)."""
    categoria = _categoria_valida(db, categoria_arg)
    divisiones = _divisiones_de_categoria(db, categoria)
    if not divisiones:
        return categoria, ""
    division = division_arg if division_arg in divisiones else divisiones[0]
    return categoria, division


def _contar_juveniles(db, equipo, categoria=CATEGORIA_ACTIVA):
    return db.execute(
        "SELECT COUNT(*) c FROM jugadores WHERE equipo = ? AND categoria = ? AND subcategoria = 'Juvenil'",
        (equipo, categoria),
    ).fetchone()["c"]
