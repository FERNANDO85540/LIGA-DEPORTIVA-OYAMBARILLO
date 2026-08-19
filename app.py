import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, g

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")

DB_PATH = os.path.join(os.path.dirname(__file__), "liga.db")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "Oyambarillo2026")

CUPO_MAXIMO_EQUIPO = 35
CATEGORIA_ACTIVA = "Sub 45"

EQUIPOS_INICIALES = [
    "San Juan", "El Progreso", "La Union", "Santa Rosa",
    "Los Andes", "Independiente", "Deportivo Central", "Juventud",
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("""
        CREATE TABLE IF NOT EXISTS jugadores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cedula TEXT NOT NULL UNIQUE,
            nombres TEXT NOT NULL,
            apellidos TEXT NOT NULL,
            fecha_nacimiento TEXT,
            equipo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            telefono TEXT,
            fecha_registro TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS equipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE
        )
    """)
    count = db.execute("SELECT COUNT(*) c FROM equipos").fetchone()[0]
    if count == 0:
        for nombre in EQUIPOS_INICIALES:
            db.execute("INSERT INTO equipos (nombre) VALUES (?)", (nombre,))
    db.commit()
    db.close()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("usuario", "")
        pw = request.form.get("clave", "")
        if user == ADMIN_USER and pw == ADMIN_PASS:
            session["logged_in"] = True
            return redirect(url_for("inscripcion"))
        flash("Usuario o clave incorrectos")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return redirect(url_for("inscripcion")) if session.get("logged_in") else redirect(url_for("login"))


@app.route("/equipos/agregar", methods=["POST"])
@login_required
def agregar_equipo():
    db = get_db()
    nombre = request.form.get("nombre", "").strip()
    if nombre:
        try:
            db.execute("INSERT INTO equipos (nombre) VALUES (?)", (nombre,))
            db.commit()
            flash(f"Equipo '{nombre}' agregado.")
        except sqlite3.IntegrityError:
            flash(f"Ya existe un equipo llamado '{nombre}'.")
    return redirect(url_for("inscripcion"))


@app.route("/equipos/<int:equipo_id>/renombrar", methods=["POST"])
@login_required
def renombrar_equipo(equipo_id):
    db = get_db()
    nuevo_nombre = request.form.get("nombre", "").strip()
    if nuevo_nombre:
        actual = db.execute("SELECT nombre FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
        if actual:
            try:
                db.execute("UPDATE equipos SET nombre = ? WHERE id = ?", (nuevo_nombre, equipo_id))
                db.execute("UPDATE jugadores SET equipo = ? WHERE equipo = ?", (nuevo_nombre, actual["nombre"]))
                db.commit()
                flash(f"Equipo renombrado a '{nuevo_nombre}'.")
            except sqlite3.IntegrityError:
                flash(f"Ya existe un equipo llamado '{nuevo_nombre}'.")
    return redirect(url_for("inscripcion"))


@app.route("/equipos/<int:equipo_id>/eliminar", methods=["POST"])
@login_required
def eliminar_equipo(equipo_id):
    db = get_db()
    equipo = db.execute("SELECT nombre FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    if equipo:
        jugadores_count = db.execute(
            "SELECT COUNT(*) c FROM jugadores WHERE equipo = ?", (equipo["nombre"],)
        ).fetchone()["c"]
        if jugadores_count > 0:
            flash(f"No se puede eliminar '{equipo['nombre']}': tiene {jugadores_count} jugador(es) inscritos.")
        else:
            db.execute("DELETE FROM equipos WHERE id = ?", (equipo_id,))
            db.commit()
            flash(f"Equipo '{equipo['nombre']}' eliminado.")
    return redirect(url_for("inscripcion"))


@app.route("/inscripcion", methods=["GET", "POST"])
@login_required
def inscripcion():
    db = get_db()

    if request.method == "POST":
        cedula = request.form.get("cedula", "").strip()
        nombres = request.form.get("nombres", "").strip()
        apellidos = request.form.get("apellidos", "").strip()
        fecha_nacimiento = request.form.get("fecha_nacimiento", "").strip()
        equipo = request.form.get("equipo", "").strip()
        telefono = request.form.get("telefono", "").strip()

        if not (cedula and nombres and apellidos and equipo):
            flash("Cédula, nombres, apellidos y equipo son obligatorios.")
        else:
            count = db.execute(
                "SELECT COUNT(*) c FROM jugadores WHERE equipo = ? AND categoria = ?",
                (equipo, CATEGORIA_ACTIVA),
            ).fetchone()["c"]

            if count >= CUPO_MAXIMO_EQUIPO:
                flash(f"El equipo {equipo} ya alcanzó el cupo máximo de {CUPO_MAXIMO_EQUIPO} jugadores en {CATEGORIA_ACTIVA}.")
            else:
                try:
                    db.execute(
                        """INSERT INTO jugadores
                           (cedula, nombres, apellidos, fecha_nacimiento, equipo, categoria, telefono, fecha_registro)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (cedula, nombres, apellidos, fecha_nacimiento, equipo, CATEGORIA_ACTIVA,
                         telefono, datetime.now().strftime("%Y-%m-%d %H:%M")),
                    )
                    db.commit()
                    flash(f"Jugador {nombres} {apellidos} inscrito correctamente en {equipo}.")
                except sqlite3.IntegrityError:
                    flash(f"Ya existe un jugador registrado con la cédula {cedula}.")

        return redirect(url_for("inscripcion"))

    jugadores = db.execute(
        "SELECT * FROM jugadores WHERE categoria = ? ORDER BY equipo, apellidos", (CATEGORIA_ACTIVA,)
    ).fetchall()

    equipos_rows = db.execute("SELECT * FROM equipos ORDER BY nombre").fetchall()

    cupos = {}
    for equipo in equipos_rows:
        c = db.execute(
            "SELECT COUNT(*) c FROM jugadores WHERE equipo = ? AND categoria = ?",
            (equipo["nombre"], CATEGORIA_ACTIVA),
        ).fetchone()["c"]
        cupos[equipo["nombre"]] = c

    return render_template(
        "inscripcion.html",
        jugadores=jugadores,
        equipos=equipos_rows,
        cupos=cupos,
        cupo_maximo=CUPO_MAXIMO_EQUIPO,
        categoria=CATEGORIA_ACTIVA,
    )


@app.route("/jugador/<int:jugador_id>/eliminar", methods=["POST"])
@login_required
def eliminar_jugador(jugador_id):
    db = get_db()
    db.execute("DELETE FROM jugadores WHERE id = ?", (jugador_id,))
    db.commit()
    flash("Jugador eliminado.")
    return redirect(url_for("inscripcion"))


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
