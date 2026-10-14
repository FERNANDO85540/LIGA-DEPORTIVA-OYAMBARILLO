"""Rollback: restaura un respaldo hecho con scripts/backup_db.py.

Uso:
    python scripts/restore_db.py /data/backups/liga-20261014-153000.db

- SQLite: antes de pisar la base actual guarda una copia de seguridad de ella
  (liga-antes-de-restaurar-<fecha>.db), así el propio rollback es reversible.
  Detén la app (o haz el rollback antes de que arranque) para que no haya
  escrituras a mitad de la restauración.
- PostgreSQL: un respaldo .sql se restaura con psql (se imprime el comando
  exacto); un respaldo .json se restaura a mano, tabla por tabla.
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = "/data" if os.path.isdir("/data") else RAIZ
DB_PATH = os.path.join(DATA_DIR, "liga.db")


def restaurar_sqlite(respaldo, db_path=DB_PATH):
    verif = sqlite3.connect(respaldo)
    resultado = verif.execute("PRAGMA integrity_check").fetchone()[0]
    verif.close()
    if resultado != "ok":
        raise SystemExit(f"El respaldo {respaldo} está dañado ({resultado}); no se restaura.")

    if os.path.exists(db_path):
        marca = datetime.now().strftime("%Y%m%d-%H%M%S")
        seguridad = os.path.join(os.path.dirname(db_path), "backups", f"liga-antes-de-restaurar-{marca}.db")
        os.makedirs(os.path.dirname(seguridad), exist_ok=True)
        actual = sqlite3.connect(db_path)
        copia = sqlite3.connect(seguridad)
        with copia:
            actual.backup(copia)
        copia.close()
        actual.close()
        print(f"Copia de seguridad de la base actual: {seguridad}")

    shutil.copy2(respaldo, db_path)
    print(f"Base restaurada desde {respaldo} -> {db_path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Restaura un respaldo de la base de datos.")
    parser.add_argument("respaldo", help="Archivo de respaldo (.db, .sql o .json).")
    args = parser.parse_args(argv)

    if not os.path.exists(args.respaldo):
        raise SystemExit(f"No existe el archivo {args.respaldo}")

    if args.respaldo.endswith(".db"):
        restaurar_sqlite(args.respaldo)
    elif args.respaldo.endswith(".sql"):
        print("Respaldo PostgreSQL. Restaurar con:")
        print(f'  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f {args.respaldo}')
        print("(en una base vacía, o tras DROP SCHEMA public CASCADE; CREATE SCHEMA public;)")
    else:
        raise SystemExit("Formato no soportado para restauración automática; ver docs/MIGRACION.md.")


if __name__ == "__main__":
    sys.exit(main())
