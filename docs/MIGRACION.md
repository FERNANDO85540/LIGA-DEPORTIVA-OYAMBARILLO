# Plan de migración, respaldo y rollback

## Paso 1 — Respaldo antes de desplegar

En el servidor (Render → *Shell* del servicio), **antes** de desplegar la versión nueva:

```bash
python scripts/backup_db.py --con-fotos
```

- SQLite (disco persistente `/data`): deja `/data/backups/liga-AAAAMMDD-HHMMSS.db`
  (copia en caliente con la API de respaldo de SQLite, verificada con `PRAGMA integrity_check`)
  y `/data/backups/fotos-AAAAMMDD-HHMMSS.tar.gz`.
- PostgreSQL (si existe `DATABASE_URL`): `pg_dump` a `.sql`, o volcado `.json` si `pg_dump` no está instalado.

Además, la app hace **un respaldo automático** de la base SQLite antes de aplicar
cualquier migración de esquema pendiente (`/data/backups/liga-pre-migracion-*.db`),
así que aunque se olvide el paso manual, siempre queda una copia del estado previo.

## Rollback

### Código

El último commit antes de esta migración es `b51ac78`. Para volver a esa versión:
en Render → *Manual Deploy* → *Deploy a specific commit* → `b51ac78`
(o `git revert` de los commits de la migración y desplegar).

> El comando de arranque cambió de `gunicorn app:app` a `gunicorn wsgi:app`
> (ya está en `render.yaml`). Si se vuelve a `b51ac78`, el comando debe volver a
> ser `gunicorn app:app`. La versión nueva también acepta `gunicorn app:app`
> por compatibilidad, así que no hace falta tocar el panel de Render para desplegarla.

### Datos

```bash
python scripts/restore_db.py /data/backups/liga-AAAAMMDD-HHMMSS.db
```

Antes de pisar la base actual guarda una copia de ella
(`liga-antes-de-restaurar-*.db`), por lo que el propio rollback se puede deshacer.
Detén el servicio (o hazlo antes de que arranque) para que nadie escriba durante la restauración.

Para PostgreSQL con respaldo `.sql`:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f /ruta/al/respaldo.sql
```
