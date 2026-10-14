"""Respaldo de la base de datos de la liga (Paso 1 del plan de migración).

Uso:
    python scripts/backup_db.py                 # respaldo con fecha y hora
    python scripts/backup_db.py --con-fotos     # además empaqueta las fotos
    python scripts/backup_db.py --destino /ruta/a/carpeta

Funciona sin levantar la aplicación (no importa Flask), así que se puede
correr ANTES de desplegar una versión nueva:

- SQLite (por defecto): usa la API de respaldo en caliente de sqlite3, que
  produce una copia consistente aunque la app esté atendiendo pedidos.
- PostgreSQL (si existe la variable DATABASE_URL): intenta `pg_dump`; si no
  está instalado, hace un volcado JSON tabla por tabla con psycopg2.

El archivo resultante es lo que se usa para el rollback con
scripts/restore_db.py (ver docs/MIGRACION.md).
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = "/data" if os.path.isdir("/data") else RAIZ
DB_PATH = os.path.join(DATA_DIR, "liga.db")
FOTOS_DIR = os.path.join(DATA_DIR, "fotos_jugadores")
DESTINO_POR_DEFECTO = os.path.join(DATA_DIR, "backups")


def _marca_tiempo():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def respaldar_sqlite(destino, db_path=DB_PATH):
    if not os.path.exists(db_path):
        raise SystemExit(f"No existe la base SQLite en {db_path}: no hay nada que respaldar.")
    archivo = os.path.join(destino, f"liga-{_marca_tiempo()}.db")
    origen = sqlite3.connect(db_path)
    copia = sqlite3.connect(archivo)
    with copia:
        origen.backup(copia)
    copia.close()
    origen.close()

    # Verificación: la copia debe abrir y pasar el chequeo de integridad.
    verif = sqlite3.connect(archivo)
    resultado = verif.execute("PRAGMA integrity_check").fetchone()[0]
    tablas = verif.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
    verif.close()
    if resultado != "ok":
        raise SystemExit(f"El respaldo {archivo} no pasó el chequeo de integridad: {resultado}")
    print(f"Respaldo SQLite OK: {archivo} ({tablas} tablas, integridad: {resultado})")
    return archivo


def respaldar_postgres(destino, database_url):
    base = os.path.join(destino, f"liga-{_marca_tiempo()}")
    if shutil.which("pg_dump"):
        archivo = base + ".sql"
        subprocess.run(["pg_dump", "--no-owner", "--file", archivo, database_url], check=True)
        print(f"Respaldo PostgreSQL (pg_dump) OK: {archivo}")
        return archivo

    import psycopg2
    import psycopg2.extras

    archivo = base + ".json"
    conn = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
    )
    volcado = {}
    for fila in cur.fetchall():
        tabla = fila["table_name"]
        cur.execute(f'SELECT * FROM "{tabla}"')
        volcado[tabla] = [dict(r) for r in cur.fetchall()]
    conn.close()
    with open(archivo, "w", encoding="utf-8") as f:
        json.dump(volcado, f, ensure_ascii=False, default=str, indent=1)
    print(f"Respaldo PostgreSQL (JSON, sin pg_dump) OK: {archivo} ({len(volcado)} tablas)")
    return archivo


def respaldar_fotos(destino):
    if not os.path.isdir(FOTOS_DIR):
        print("No hay carpeta de fotos para respaldar.")
        return None
    archivo = os.path.join(destino, f"fotos-{_marca_tiempo()}.tar.gz")
    with tarfile.open(archivo, "w:gz") as tar:
        tar.add(FOTOS_DIR, arcname="fotos_jugadores")
    print(f"Respaldo de fotos OK: {archivo}")
    return archivo


def main(argv=None):
    parser = argparse.ArgumentParser(description="Respalda la base de datos de la liga.")
    parser.add_argument("--destino", default=DESTINO_POR_DEFECTO, help="Carpeta donde guardar el respaldo.")
    parser.add_argument("--con-fotos", action="store_true", help="Empaquetar también las fotos de jugadores.")
    args = parser.parse_args(argv)

    os.makedirs(args.destino, exist_ok=True)
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        respaldar_postgres(args.destino, database_url)
    else:
        respaldar_sqlite(args.destino)
    if args.con_fotos:
        respaldar_fotos(args.destino)


if __name__ == "__main__":
    sys.exit(main())
