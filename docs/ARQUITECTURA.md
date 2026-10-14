# Arquitectura

```
config.py                 Constantes y configuración (rutas, credenciales por rol, cupos)
wsgi.py                   Punto de entrada: gunicorn wsgi:app  /  python wsgi.py
app/
  __init__.py             Application Factory: create_app()
  database.py             Conexión SQLite/PostgreSQL (DBWrapper), get_db, init_db (esquema y migraciones)
  decorators.py           login_required, admin_required, ... y chequeos de acceso a equipo/jugador
  utils.py                Utilidades genéricas
  services/               Lógica de negocio sin rutas (SQL puro con db.execute)
    liga.py               Campeonatos y divisiones
    partidos.py           Fixture
    sanciones.py          Suspensiones, rojas, acumulación de amarillas
    estadisticas.py       Tabla de posiciones y goleadores
    jugadores.py          Inscripción y validaciones
    carnets.py            Generación de carnets (Pillow)
    exportacion.py / importacion.py   Excel
    alineaciones.py, equipos.py
  blueprints/             Rutas, un Blueprint por área
    main, auth, inscripcion, equipos, jugadores, categorias, carnets,
    comision, tecnica, sanciones, vocalia, publico
  templates/<blueprint>/  Plantillas agrupadas por área; base.html y partials/ comunes
  static/
```

Los endpoints llevan el prefijo de su blueprint: `url_for("sanciones.sanciones_modulo")`.
Las URLs públicas no cambiaron.

## Cómo se validó la refactorización

Las funciones se movieron textualmente con un script basado en `ast` (solo cambió
`@app.route` → `@bp.route` y los nombres de endpoints/plantillas). Luego se corrieron
la app original y la refactorizada sobre copias de la misma base de prueba, con 259
peticiones (todas las vistas con cada rol y todas las acciones POST, incluidos casos de
error): el HTML, las redirecciones, los archivos generados (carnets, Excel) y el volcado
final de la base resultaron idénticos.

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest tests
```

Cubren las reglas de negocio: suspensiones contadas solo sobre partidos jugados,
fecha de inicio manual, levantar sanciones, acumulación de 5 amarillas en ambos
sentidos, exclusividad de cédula por torneo, dorsal único, solicitud de reemplazo,
hora de Ecuador, redirección segura de vuelta a la vista y la migración del esquema viejo.
