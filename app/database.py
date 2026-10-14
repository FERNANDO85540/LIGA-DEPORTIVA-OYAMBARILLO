"""Conexión a la base de datos (SQLite o PostgreSQL) y creación/migración del esquema.

Se mantiene SQL puro con db.execute(): DBWrapper traduce los placeholders '?'
de SQLite a '%s' de psycopg2 para que las mismas consultas sirvan en ambos motores.
"""
import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime

from flask import g

from config import (
    BASE_DIR, CUPO_MAXIMO_JUVENIL, DATA_DIR, DATABASE_URL, DB_PATH, EQUIPOS_INICIALES, FOTOS_DIR,
    STATIC_DIR, USANDO_POSTGRES,
)
from app.services.equipos import _renombrar_equipo_cascada
from app.utils import ZONA_LIGA, _mayuscula, ahora_ecuador

if USANDO_POSTGRES:
    import psycopg2
    import psycopg2.extras
    IntegrityError = psycopg2.IntegrityError
else:
    IntegrityError = sqlite3.IntegrityError


def preparar_directorios_de_datos():
    """Crea la carpeta de fotos y, si el disco persistente está recién montado
    y todavía no tiene datos, copia una sola vez los datos viejos que existan
    en la carpeta efímera del proyecto (de antes de tener disco persistente)."""
    os.makedirs(FOTOS_DIR, exist_ok=True)

    if DATA_DIR != BASE_DIR:
        _db_vieja = os.path.join(BASE_DIR, "liga.db")
        if not os.path.exists(DB_PATH) and os.path.exists(_db_vieja):
            shutil.copy2(_db_vieja, DB_PATH)

        _fotos_viejas = os.path.join(STATIC_DIR, "fotos_jugadores")
        if os.path.isdir(_fotos_viejas):
            for _nombre in os.listdir(_fotos_viejas):
                _destino = os.path.join(FOTOS_DIR, _nombre)
                if not os.path.exists(_destino):
                    try:
                        shutil.copy2(os.path.join(_fotos_viejas, _nombre), _destino)
                    except OSError:
                        pass


class DBWrapper:
    """Traduce placeholders '?' (estilo sqlite) a '%s' (estilo psycopg2)
    y adapta fetchone()/fetchall() para devolver dicts en ambos motores."""

    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, params=()):
        cur = self.conn.cursor()
        if USANDO_POSTGRES:
            query = re.sub(r"\?", "%s", query)
            query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        cur.execute(query, params)
        return CursorWrapper(cur)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


class CursorWrapper:
    def __init__(self, cur):
        self.cur = cur

    def fetchone(self):
        row = self.cur.fetchone()
        return row

    def fetchall(self):
        return self.cur.fetchall()

    @property
    def lastrowid(self):
        if USANDO_POSTGRES:
            try:
                return self.cur.fetchone()[0]
            except Exception:
                return None
        return self.cur.lastrowid


def _conectar():
    if USANDO_POSTGRES:
        return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    if "db" not in g:
        g.db = DBWrapper(_conectar())
    return g.db


def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _columnas_existentes(db, tabla):
    if USANDO_POSTGRES:
        filas = db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", (tabla,)
        ).fetchall()
        return [f["column_name"] for f in filas]
    filas = db.execute(f"PRAGMA table_info({tabla})").fetchall()
    return [f[1] for f in filas]


def init_db():
    _respaldar_antes_de_migrar()
    db = DBWrapper(_conectar())

    tipo_id = "SERIAL PRIMARY KEY" if USANDO_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS jugadores (
            id {tipo_id},
            cedula TEXT NOT NULL,
            nombres TEXT NOT NULL,
            apellidos TEXT NOT NULL,
            fecha_nacimiento TEXT,
            equipo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            subcategoria TEXT NOT NULL DEFAULT 'Sub 45',
            numero_camiseta TEXT,
            foto TEXT,
            foto_confirmada INTEGER NOT NULL DEFAULT 0,
            cedula_frontal TEXT,
            cedula_reverso TEXT,
            calificado INTEGER NOT NULL DEFAULT 0,
            fecha_registro TEXT NOT NULL
        )
    """)
    jcols = _columnas_existentes(db, "jugadores")
    if "subcategoria" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN subcategoria TEXT NOT NULL DEFAULT 'Sub 45'")
    if "numero_camiseta" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN numero_camiseta TEXT")
    if "foto" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN foto TEXT")
    if "foto_confirmada" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN foto_confirmada INTEGER NOT NULL DEFAULT 0")
    if "cedula_frontal" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN cedula_frontal TEXT")
    if "cedula_reverso" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN cedula_reverso TEXT")
    if "calificado" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN calificado INTEGER NOT NULL DEFAULT 0")
    if "foto_token" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN foto_token TEXT")
        for row in db.execute("SELECT id FROM jugadores").fetchall():
            db.execute("UPDATE jugadores SET foto_token = ? WHERE id = ?", (uuid.uuid4().hex, row["id"]))
    if "carnet_impreso" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN carnet_impreso INTEGER NOT NULL DEFAULT 0")
    if "carnet_valor" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN carnet_valor REAL")
    if "carnet_fecha" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN carnet_fecha TEXT")
    if "documentos_fecha" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN documentos_fecha TEXT")
    if "division" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN division TEXT NOT NULL DEFAULT ''")

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS equipos (
            id {tipo_id},
            nombre TEXT NOT NULL UNIQUE,
            valor_inscripcion REAL NOT NULL DEFAULT 0,
            abono REAL NOT NULL DEFAULT 0,
            forma_pago TEXT,
            comprobante_pago TEXT,
            usuario TEXT UNIQUE,
            clave TEXT
        )
    """)
    cols = _columnas_existentes(db, "equipos")
    if "valor_inscripcion" not in cols:
        db.execute("ALTER TABLE equipos ADD COLUMN valor_inscripcion REAL NOT NULL DEFAULT 0")
    if "abono" not in cols:
        db.execute("ALTER TABLE equipos ADD COLUMN abono REAL NOT NULL DEFAULT 0")
    if "forma_pago" not in cols:
        db.execute("ALTER TABLE equipos ADD COLUMN forma_pago TEXT")
    if "comprobante_pago" not in cols:
        db.execute("ALTER TABLE equipos ADD COLUMN comprobante_pago TEXT")
    if "usuario" not in cols:
        db.execute("ALTER TABLE equipos ADD COLUMN usuario TEXT")
    if "clave" not in cols:
        db.execute("ALTER TABLE equipos ADD COLUMN clave TEXT")
    if "categoria" not in cols:
        db.execute("ALTER TABLE equipos ADD COLUMN categoria TEXT NOT NULL DEFAULT 'Sub 45'")

    count_row = db.execute("SELECT COUNT(*) c FROM equipos").fetchone()
    count = count_row["c"]
    if count == 0:
        for nombre in EQUIPOS_INICIALES:
            db.execute("INSERT INTO equipos (nombre) VALUES (?)", (nombre,))

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS jornadas (
            id {tipo_id},
            numero INTEGER NOT NULL,
            fecha TEXT,
            categoria TEXT NOT NULL DEFAULT 'Sub 45'
        )
    """)
    if "categoria" not in _columnas_existentes(db, "jornadas"):
        db.execute("ALTER TABLE jornadas ADD COLUMN categoria TEXT NOT NULL DEFAULT 'Sub 45'")

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS partidos (
            id {tipo_id},
            jornada_id INTEGER NOT NULL,
            equipo_local TEXT NOT NULL,
            equipo_visitante TEXT NOT NULL,
            hora TEXT,
            fecha TEXT
        )
    """)
    if "fecha" not in _columnas_existentes(db, "partidos"):
        db.execute("ALTER TABLE partidos ADD COLUMN fecha TEXT")
    # 1. Nuevas columnas para ganar por escritorio (mesa)
    pcols = _columnas_existentes(db, "partidos")
    if "ganador_escritorio" not in pcols:
        # Guardará el nombre del equipo ganador por sanción (ej. jugó con sancionados)
        db.execute("ALTER TABLE partidos ADD COLUMN ganador_escritorio TEXT")
    
    # 2. Nueva tabla para quitar puntos en la tabla de posiciones
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS puntos_sancion (
            id {tipo_id},
            equipo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            division TEXT NOT NULL DEFAULT '',
            puntos_descontar INTEGER NOT NULL DEFAULT 0,
            motivo TEXT NOT NULL,
            fecha TEXT NOT NULL
        )
    """)
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS descansos (
            id {tipo_id},
            jornada_id INTEGER NOT NULL,
            equipo TEXT NOT NULL
        )
    """)

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS tarjetas (
            id {tipo_id},
            jugador_id INTEGER NOT NULL,
            jornada_id INTEGER,
            tipo TEXT NOT NULL,
            valor_multa REAL,
            observacion TEXT,
            fecha TEXT NOT NULL
        )
    """)
    if "partido_id" not in _columnas_existentes(db, "tarjetas"):
        db.execute("ALTER TABLE tarjetas ADD COLUMN partido_id INTEGER")
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS sanciones (
            id {tipo_id},
            jugador_id INTEGER NOT NULL,
            motivo TEXT,
            jornadas_sancionado INTEGER NOT NULL DEFAULT 1,
            jornada_desde_id INTEGER,
            valor_multa REAL,
            pagada INTEGER NOT NULL DEFAULT 0,
            fecha TEXT NOT NULL
        )
    """)
    scols = _columnas_existentes(db, "sanciones")
    if "origen" not in scols:
        db.execute("ALTER TABLE sanciones ADD COLUMN origen TEXT NOT NULL DEFAULT 'manual'")
    if "catalogo_id" not in scols:
        db.execute("ALTER TABLE sanciones ADD COLUMN catalogo_id INTEGER")
    if "categoria" not in scols:
        db.execute("ALTER TABLE sanciones ADD COLUMN categoria TEXT")
    if "division" not in scols:
        db.execute("ALTER TABLE sanciones ADD COLUMN division TEXT")
    if "tarjeta_id" not in scols:
        db.execute("ALTER TABLE sanciones ADD COLUMN tarjeta_id INTEGER")
    sanciones_necesita_backfill = "jornada_desde_numero" not in scols
    if sanciones_necesita_backfill:
        db.execute("ALTER TABLE sanciones ADD COLUMN jornada_desde_numero INTEGER")

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS sanciones_catalogo (
            id {tipo_id},
            articulo TEXT,
            descripcion_motivo TEXT NOT NULL,
            cantidad_fechas_suspension INTEGER NOT NULL DEFAULT 1,
            aplica_multa INTEGER NOT NULL DEFAULT 0,
            valor_multa_sugerido REAL
        )
    """)

    pcols = _columnas_existentes(db, "partidos")
    if "goles_local" not in pcols:
        db.execute("ALTER TABLE partidos ADD COLUMN goles_local INTEGER")
    if "goles_visitante" not in pcols:
        db.execute("ALTER TABLE partidos ADD COLUMN goles_visitante INTEGER")
    if "jugado" not in pcols:
        db.execute("ALTER TABLE partidos ADD COLUMN jugado INTEGER NOT NULL DEFAULT 0")
    if "en_vivo" not in pcols:
        db.execute("ALTER TABLE partidos ADD COLUMN en_vivo INTEGER NOT NULL DEFAULT 0")
    if "arbitro" not in pcols:
        db.execute("ALTER TABLE partidos ADD COLUMN arbitro TEXT")
    if "informe_arbitro" not in pcols:
        db.execute("ALTER TABLE partidos ADD COLUMN informe_arbitro TEXT")
    if "informe_vocalia" not in pcols:
        db.execute("ALTER TABLE partidos ADD COLUMN informe_vocalia TEXT")
    if "hoja_editada" not in pcols:
        db.execute("ALTER TABLE partidos ADD COLUMN hoja_editada INTEGER NOT NULL DEFAULT 0")

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS goles (
            id {tipo_id},
            jugador_id INTEGER NOT NULL,
            partido_id INTEGER,
            cantidad INTEGER NOT NULL DEFAULT 1,
            fecha TEXT NOT NULL
        )
    """)

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS categorias (
            id {tipo_id},
            nombre TEXT NOT NULL UNIQUE,
            edad_minima INTEGER
        )
    """)
    ccols = _columnas_existentes(db, "categorias")
    if "limite_juveniles" not in ccols:
        db.execute("ALTER TABLE categorias ADD COLUMN limite_juveniles INTEGER")
        # Se preserva el tope global que regía antes (3) para los campeonatos ya
        # existentes; Senior queda sin límite (ver más abajo), tal como se definió
        # para permitir inscribir a todos los juveniles de 14 a 17 años.
        db.execute("UPDATE categorias SET limite_juveniles = ? WHERE nombre != 'Senior'", (CUPO_MAXIMO_JUVENIL,))

    if db.execute("SELECT COUNT(*) c FROM categorias").fetchone()["c"] == 0:
        db.execute(
            "INSERT INTO categorias (nombre, edad_minima, limite_juveniles) VALUES (?, ?, ?)",
            ("Sub 45", 45, CUPO_MAXIMO_JUVENIL),
        )
        db.execute(
            "INSERT INTO categorias (nombre, edad_minima, limite_juveniles) VALUES (?, ?, ?)",
            ("Senior", 14, None),
        )
    else:
        # Senior (Máxima y Primera) se juega desde los 14 años; los de 14 a 17
        # quedan marcados como Juvenil con cupo aparte (ver _subcategoria_por_nacimiento).
        db.execute("UPDATE categorias SET edad_minima = 14 WHERE nombre = 'Senior' AND edad_minima IS NULL")

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS divisiones (
            id {tipo_id},
            categoria TEXT NOT NULL,
            nombre TEXT NOT NULL
        )
    """)

    ecols = _columnas_existentes(db, "equipos")
    if "division" not in ecols:
        db.execute("ALTER TABLE equipos ADD COLUMN division TEXT NOT NULL DEFAULT ''")
    jocols = _columnas_existentes(db, "jornadas")
    if "division" not in jocols:
        db.execute("ALTER TABLE jornadas ADD COLUMN division TEXT NOT NULL DEFAULT ''")

    if sanciones_necesita_backfill:
        for fila in db.execute(
            "SELECT s.id AS sid, jo.numero AS numero, jo.categoria AS categoria, jo.division AS division "
            "FROM sanciones s JOIN jornadas jo ON jo.id = s.jornada_desde_id WHERE s.jornada_desde_id IS NOT NULL"
        ).fetchall():
            db.execute(
                "UPDATE sanciones SET jornada_desde_numero = ?, categoria = ?, division = ? WHERE id = ?",
                (fila["numero"], fila["categoria"], fila["division"], fila["sid"]),
            )

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS alineaciones (
            id {tipo_id},
            partido_id INTEGER NOT NULL,
            equipo TEXT NOT NULL,
            formacion TEXT NOT NULL,
            fecha_registro TEXT
        )
    """)
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS alineacion_jugadores (
            id {tipo_id},
            alineacion_id INTEGER NOT NULL,
            jugador_id INTEGER NOT NULL,
            posicion TEXT NOT NULL,
            titular INTEGER NOT NULL DEFAULT 1
        )
    """)

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS vocalia_asistencia (
            id {tipo_id},
            partido_id INTEGER NOT NULL,
            jugador_id INTEGER NOT NULL,
            participo INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS vocalia_incidentes (
            id {tipo_id},
            partido_id INTEGER NOT NULL,
            descripcion TEXT NOT NULL,
            fecha TEXT NOT NULL
        )
    """)
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS vocalia_cambios (
            id {tipo_id},
            partido_id INTEGER NOT NULL,
            equipo TEXT NOT NULL,
            jugador_sale_id INTEGER NOT NULL,
            jugador_entra_id INTEGER NOT NULL,
            minuto TEXT,
            fecha TEXT NOT NULL
        )
    """)

    _normalizar_mayusculas_existentes(db)
    db.commit()

    _aplicar_migraciones(db)

    db.commit()
    db.close()


def _normalizar_mayusculas_existentes(db):
    """Migración (corre cada arranque, es barata e idempotente): pasa a
    MAYÚSCULAS los nombres de jugadores y equipos ya guardados, para que se
    vean uniformes sin importar si se registraron a mano o por el
    importador de Excel. Si dos equipos quedarían con el mismo nombre en
    mayúsculas, ese caso se deja intacto para resolverlo a mano (no se
    puede adivinar cuál de los dos es el correcto)."""
    for fila in db.execute("SELECT id, nombres, apellidos FROM jugadores").fetchall():
        nuevos_nombres = _mayuscula(fila["nombres"])
        nuevos_apellidos = _mayuscula(fila["apellidos"])
        if nuevos_nombres != fila["nombres"] or nuevos_apellidos != fila["apellidos"]:
            db.execute(
                "UPDATE jugadores SET nombres = ?, apellidos = ? WHERE id = ?",
                (nuevos_nombres, nuevos_apellidos, fila["id"]),
            )

    for fila in db.execute("SELECT id, nombre FROM equipos").fetchall():
        nuevo_nombre = _mayuscula(fila["nombre"])
        if nuevo_nombre == fila["nombre"]:
            continue
        colision = db.execute(
            "SELECT 1 FROM equipos WHERE nombre = ? AND id != ?", (nuevo_nombre, fila["id"])
        ).fetchone()
        if colision:
            continue
        db.execute("UPDATE equipos SET nombre = ? WHERE id = ?", (nuevo_nombre, fila["id"]))
        _renombrar_equipo_cascada(db, fila["nombre"], nuevo_nombre)


# ---------- Migraciones con registro (se aplican una sola vez) ----------
#
# A diferencia de los ALTER TABLE "si falta la columna" de init_db, estas
# migraciones transforman datos o constraints, así que se anotan en la tabla
# `migraciones` para no repetirse. Antes de aplicar cualquiera pendiente se
# guarda un respaldo de la base SQLite (ver _respaldar_antes_de_migrar).

MIGRACIONES = [
    "2026_10_columnas_sanciones_y_reemplazo",
    "2026_10_cedula_unica_por_torneo",
    "2026_10_fecha_registro_hora_ecuador",
    "2026_10_quitar_estado_en_vivo",
]


def _migraciones_aplicadas(db):
    db.execute("CREATE TABLE IF NOT EXISTS migraciones (nombre TEXT PRIMARY KEY, aplicada TEXT NOT NULL)")
    return {f["nombre"] for f in db.execute("SELECT nombre FROM migraciones").fetchall()}


def _respaldar_antes_de_migrar():
    """Si hay migraciones pendientes y la base es SQLite con datos, deja una
    copia en DATA_DIR/backups/liga-pre-migracion-<fecha>.db antes de tocarla."""
    if USANDO_POSTGRES or not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        existe_tabla = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'migraciones'"
        ).fetchone()
        aplicadas = {f[0] for f in conn.execute("SELECT nombre FROM migraciones")} if existe_tabla else set()
        tiene_datos = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jugadores'"
        ).fetchone()
        if not tiene_datos or set(MIGRACIONES) <= aplicadas:
            return None
        carpeta = os.path.join(DATA_DIR, "backups")
        os.makedirs(carpeta, exist_ok=True)
        destino = os.path.join(carpeta, f"liga-pre-migracion-{ahora_ecuador():%Y%m%d-%H%M%S}.db")
        copia = sqlite3.connect(destino)
        with copia:
            conn.backup(copia)
        copia.close()
        print(f"Respaldo previo a migraciones: {destino}")
        return destino
    finally:
        conn.close()


def _aplicar_migraciones(db):
    aplicadas = _migraciones_aplicadas(db)
    pasos = {
        "2026_10_columnas_sanciones_y_reemplazo": _migrar_columnas_sanciones_y_reemplazo,
        "2026_10_cedula_unica_por_torneo": _migrar_cedula_unica_por_torneo,
        "2026_10_fecha_registro_hora_ecuador": _migrar_fecha_registro_hora_ecuador,
        "2026_10_quitar_estado_en_vivo": _migrar_quitar_estado_en_vivo,
    }
    for nombre in MIGRACIONES:
        if nombre in aplicadas:
            continue
        pasos[nombre](db)
        db.execute(
            "INSERT INTO migraciones (nombre, aplicada) VALUES (?, ?)",
            (nombre, ahora_ecuador().strftime("%Y-%m-%d %H:%M")),
        )
        db.commit()


def _migrar_columnas_sanciones_y_reemplazo(db):
    scols = _columnas_existentes(db, "sanciones")
    # Fecha (AAAA-MM-DD) desde la que corre la suspensión, definida a mano por la Comisión.
    if "fecha_inicio" not in scols:
        db.execute("ALTER TABLE sanciones ADD COLUMN fecha_inicio TEXT")
    # Sanción levantada a mano: queda en el historial pero ya no suspende.
    if "anulada" not in scols:
        db.execute("ALTER TABLE sanciones ADD COLUMN anulada INTEGER NOT NULL DEFAULT 0")
    jcols = _columnas_existentes(db, "jugadores")
    # Bandera de "Solicitud de reemplazo" que levanta el delegado.
    if "reemplazo_solicitado" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN reemplazo_solicitado INTEGER NOT NULL DEFAULT 0")
    if "reemplazo_fecha" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN reemplazo_fecha TEXT")


def _migrar_cedula_unica_por_torneo(db):
    """La cédula deja de ser única en toda la liga: un jugador puede estar en un
    equipo de Sub 45 y en otro de Senior. La exclusividad pasa a ser por torneo
    (cédula + categoría), con un índice único."""
    if USANDO_POSTGRES:
        for f in db.execute(
            "SELECT conname, pg_get_constraintdef(oid) AS definicion FROM pg_constraint "
            "WHERE conrelid = 'jugadores'::regclass AND contype = 'u'"
        ).fetchall():
            if f["definicion"].replace(" ", "").upper() == "UNIQUE(CEDULA)":
                db.execute(f'ALTER TABLE jugadores DROP CONSTRAINT "{f["conname"]}"')
    else:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'jugadores'").fetchone()["sql"]
        sql_nuevo = re.sub(r"(cedula\s+TEXT\s+NOT\s+NULL)\s+UNIQUE", r"\1", sql, flags=re.IGNORECASE)
        if sql_nuevo != sql:
            # SQLite no permite quitar un UNIQUE con ALTER: se reconstruye la tabla
            # con las mismas columnas y datos (y los mismos ids).
            seq = db.execute("SELECT seq FROM sqlite_sequence WHERE name = 'jugadores'").fetchone()
            db.commit()
            db.execute(re.sub(r"CREATE TABLE\s+\"?jugadores\"?", "CREATE TABLE jugadores_nueva", sql_nuevo, count=1))
            db.execute("INSERT INTO jugadores_nueva SELECT * FROM jugadores")
            db.execute("DROP TABLE jugadores")
            db.execute("ALTER TABLE jugadores_nueva RENAME TO jugadores")
            if seq:
                # Conserva el contador AUTOINCREMENT: así no se reutilizan ids de
                # jugadores eliminados (que aún tienen tarjetas/goles históricos).
                db.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'jugadores'", (seq["seq"],))
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_jugadores_cedula_categoria ON jugadores (cedula, categoria)")


def _migrar_fecha_registro_hora_ecuador(db):
    """Las fechas de inscripción se guardaban con la hora local del servidor
    (UTC en Render). Se convierten una sola vez a la hora de Quito/Guayaquil."""
    for f in db.execute("SELECT id, fecha_registro FROM jugadores").fetchall():
        try:
            original = datetime.strptime(f["fecha_registro"], "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            continue
        convertida = original.astimezone(ZONA_LIGA).strftime("%Y-%m-%d %H:%M")
        if convertida != f["fecha_registro"]:
            db.execute("UPDATE jugadores SET fecha_registro = ? WHERE id = ?", (convertida, f["id"]))


def _migrar_quitar_estado_en_vivo(db):
    """El estado "en vivo" se eliminó del sistema: ningún partido queda marcado así."""
    db.execute("UPDATE partidos SET en_vivo = 0 WHERE en_vivo = 1")
