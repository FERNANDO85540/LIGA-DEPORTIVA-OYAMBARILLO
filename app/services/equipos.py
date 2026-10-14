"""Operaciones sobre equipos."""


def _renombrar_equipo_cascada(db, nombre_viejo, nombre_nuevo):
    """El nombre del equipo se guarda como texto (no hay llave foránea real)
    en varias tablas además de equipos.nombre. Actualiza todas para que no
    queden partidos/alineaciones/etc. huérfanos del nombre anterior."""
    if nombre_viejo == nombre_nuevo:
        return
    db.execute("UPDATE jugadores SET equipo = ? WHERE equipo = ?", (nombre_nuevo, nombre_viejo))
    db.execute("UPDATE partidos SET equipo_local = ? WHERE equipo_local = ?", (nombre_nuevo, nombre_viejo))
    db.execute("UPDATE partidos SET equipo_visitante = ? WHERE equipo_visitante = ?", (nombre_nuevo, nombre_viejo))
    db.execute("UPDATE descansos SET equipo = ? WHERE equipo = ?", (nombre_nuevo, nombre_viejo))
    db.execute("UPDATE alineaciones SET equipo = ? WHERE equipo = ?", (nombre_nuevo, nombre_viejo))
    db.execute("UPDATE vocalia_cambios SET equipo = ? WHERE equipo = ?", (nombre_nuevo, nombre_viejo))
