import io
import os
import sqlite3
import uuid
from datetime import datetime, date
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, g, send_file
from openpyxl import Workbook, load_workbook
from PIL import Image, ImageDraw, ImageFont, ImageOps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "liga.db")
FOTOS_DIR = os.path.join(BASE_DIR, "static", "fotos_jugadores")
os.makedirs(FOTOS_DIR, exist_ok=True)

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "Oyambarillo2026")

CUPO_MAXIMO_EQUIPO = 35
CUPO_MAXIMO_JUVENIL = 3
CATEGORIA_ACTIVA = "Sub 45"
SUBCATEGORIAS = ["Sub 45", "Juvenil"]

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
            subcategoria TEXT NOT NULL DEFAULT 'Sub 45',
            numero_camiseta TEXT,
            foto TEXT,
            fecha_registro TEXT NOT NULL
        )
    """)
    jcols = [r[1] for r in db.execute("PRAGMA table_info(jugadores)").fetchall()]
    if "subcategoria" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN subcategoria TEXT NOT NULL DEFAULT 'Sub 45'")
    if "numero_camiseta" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN numero_camiseta TEXT")
    if "foto" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN foto TEXT")
    if "foto_token" not in jcols:
        db.execute("ALTER TABLE jugadores ADD COLUMN foto_token TEXT")
        for row in db.execute("SELECT id FROM jugadores").fetchall():
            db.execute("UPDATE jugadores SET foto_token = ? WHERE id = ?", (uuid.uuid4().hex, row[0]))
    db.execute("""
        CREATE TABLE IF NOT EXISTS equipos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            valor_inscripcion REAL NOT NULL DEFAULT 0,
            abono REAL NOT NULL DEFAULT 0,
            usuario TEXT UNIQUE,
            clave TEXT
        )
    """)
    cols = [r[1] for r in db.execute("PRAGMA table_info(equipos)").fetchall()]
    if "valor_inscripcion" not in cols:
        db.execute("ALTER TABLE equipos ADD COLUMN valor_inscripcion REAL NOT NULL DEFAULT 0")
    if "abono" not in cols:
        db.execute("ALTER TABLE equipos ADD COLUMN abono REAL NOT NULL DEFAULT 0")
    if "usuario" not in cols:
        db.execute("ALTER TABLE equipos ADD COLUMN usuario TEXT")
    if "clave" not in cols:
        db.execute("ALTER TABLE equipos ADD COLUMN clave TEXT")
    count = db.execute("SELECT COUNT(*) c FROM equipos").fetchone()[0]
    if count == 0:
        for nombre in EQUIPOS_INICIALES:
            db.execute("INSERT INTO equipos (nombre) VALUES (?)", (nombre,))
    db.commit()
    db.close()


def _to_float(value):
    try:
        return round(float(str(value).replace(",", ".").strip()), 2)
    except (TypeError, ValueError):
        return 0.0


def _contar_juveniles(db, equipo):
    return db.execute(
        "SELECT COUNT(*) c FROM jugadores WHERE equipo = ? AND categoria = ? AND subcategoria = 'Juvenil'",
        (equipo, CATEGORIA_ACTIVA),
    ).fetchone()["c"]


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        if session.get("rol") != "admin":
            flash("Esta acción requiere acceso de administrador.")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


def equipo_permitido(equipo_id):
    if session.get("rol") == "admin":
        return True
    return session.get("equipo_id") == equipo_id


def jugador_permitido(db, jugador):
    if session.get("rol") == "admin":
        return True
    fila = db.execute("SELECT id FROM equipos WHERE nombre = ?", (jugador["equipo"],)).fetchone()
    return fila is not None and session.get("equipo_id") == fila["id"]


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("usuario", "").strip()
        pw = request.form.get("clave", "").strip()

        if user == ADMIN_USER and pw == ADMIN_PASS:
            session.clear()
            session["logged_in"] = True
            session["rol"] = "admin"
            return redirect(url_for("inscripcion"))

        db = get_db()
        equipo = db.execute(
            "SELECT * FROM equipos WHERE usuario = ? AND clave = ?", (user, pw)
        ).fetchone()
        if equipo:
            session.clear()
            session["logged_in"] = True
            session["rol"] = "equipo"
            session["equipo_id"] = equipo["id"]
            session["equipo_nombre"] = equipo["nombre"]
            return redirect(url_for("detalle_equipo", equipo_id=equipo["id"]))

        flash("Usuario o clave incorrectos")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if session.get("rol") == "equipo":
        db = get_db()
        equipo = db.execute("SELECT id FROM equipos WHERE id = ?", (session.get("equipo_id"),)).fetchone()
        if not equipo:
            session.clear()
            flash("Tu sesión ya no es válida. Ingresa nuevamente.")
            return redirect(url_for("login"))
        return redirect(url_for("detalle_equipo", equipo_id=equipo["id"]))
    return redirect(url_for("inscripcion"))


@app.route("/equipos/agregar", methods=["POST"])
@admin_required
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
@admin_required
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
@admin_required
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


@app.route("/equipos/<int:equipo_id>/credenciales", methods=["POST"])
@admin_required
def credenciales_equipo(equipo_id):
    db = get_db()
    usuario = request.form.get("usuario", "").strip().lower()
    clave = request.form.get("clave", "").strip()
    if not (usuario and clave):
        flash("Usuario y clave son obligatorios.")
    else:
        try:
            db.execute("UPDATE equipos SET usuario = ?, clave = ? WHERE id = ?", (usuario, clave, equipo_id))
            db.commit()
            flash(f"Acceso del equipo actualizado: usuario '{usuario}'.")
        except sqlite3.IntegrityError:
            flash(f"El usuario '{usuario}' ya está en uso por otro equipo.")
    return redirect(url_for("detalle_equipo", equipo_id=equipo_id))


@app.route("/equipo/<int:equipo_id>", methods=["GET"])
@login_required
def detalle_equipo(equipo_id):
    db = get_db()
    equipo = db.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    if not equipo:
        flash("Equipo no encontrado.")
        return redirect(url_for("index"))

    if not equipo_permitido(equipo_id):
        flash("No tienes acceso a ese equipo.")
        return redirect(url_for("index"))

    jugadores = db.execute(
        "SELECT * FROM jugadores WHERE equipo = ? AND categoria = ? ORDER BY apellidos",
        (equipo["nombre"], CATEGORIA_ACTIVA),
    ).fetchall()

    saldo = equipo["valor_inscripcion"] - equipo["abono"]
    juveniles_count = _contar_juveniles(db, equipo["nombre"])

    return render_template(
        "detalle_equipo.html",
        equipo=equipo,
        jugadores=jugadores,
        saldo=saldo,
        cupo_maximo=CUPO_MAXIMO_EQUIPO,
        categoria=CATEGORIA_ACTIVA,
        juveniles_count=juveniles_count,
        cupo_maximo_juvenil=CUPO_MAXIMO_JUVENIL,
    )


def _exportar_jugadores_excel(jugadores, nombre_archivo, incluir_equipo=False):
    wb = Workbook()
    ws = wb.active
    ws.title = "Jugadores"
    encabezados = ["Cédula", "Nombres", "Apellidos", "Fecha nacimiento", "Categoría"]
    if incluir_equipo:
        encabezados.insert(0, "Equipo")
    encabezados += ["Número camiseta", "Registrado"]
    ws.append(encabezados)

    for j in jugadores:
        categoria = j["categoria"] + (" - Juvenil" if j["subcategoria"] == "Juvenil" else "")
        fila = [j["cedula"], j["nombres"], j["apellidos"], j["fecha_nacimiento"] or "", categoria]
        if incluir_equipo:
            fila.insert(0, j["equipo"])
        fila += [j["numero_camiseta"] or "", j["fecha_registro"]]
        ws.append(fila)

    for i, _ in enumerate(encabezados, start=1):
        ws.column_dimensions[chr(64 + i)].width = 18

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=nombre_archivo,
    )


@app.route("/equipo/<int:equipo_id>/exportar")
@login_required
def exportar_equipo(equipo_id):
    db = get_db()
    equipo = db.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    if not equipo:
        flash("Equipo no encontrado.")
        return redirect(url_for("index"))
    if not equipo_permitido(equipo_id):
        flash("No tienes acceso a ese equipo.")
        return redirect(url_for("index"))

    jugadores = db.execute(
        "SELECT * FROM jugadores WHERE equipo = ? AND categoria = ? ORDER BY apellidos",
        (equipo["nombre"], CATEGORIA_ACTIVA),
    ).fetchall()
    nombre_archivo = f"jugadores_{equipo['nombre'].replace(' ', '_')}.xlsx"
    return _exportar_jugadores_excel(jugadores, nombre_archivo)


@app.route("/exportar_general")
@admin_required
def exportar_general():
    db = get_db()
    jugadores = db.execute(
        "SELECT * FROM jugadores WHERE categoria = ? ORDER BY equipo, apellidos", (CATEGORIA_ACTIVA,)
    ).fetchall()
    return _exportar_jugadores_excel(jugadores, "jugadores_liga_oyambarillo.xlsx", incluir_equipo=True)


@app.route("/equipo/<int:equipo_id>/pago", methods=["POST"])
@admin_required
def actualizar_pago_equipo(equipo_id):
    db = get_db()
    valor_inscripcion = _to_float(request.form.get("valor_inscripcion", "0"))
    abono = _to_float(request.form.get("abono", "0"))
    db.execute(
        "UPDATE equipos SET valor_inscripcion = ?, abono = ? WHERE id = ?",
        (valor_inscripcion, abono, equipo_id),
    )
    db.commit()
    flash("Datos de pago actualizados.")
    return redirect(url_for("detalle_equipo", equipo_id=equipo_id))


def _insertar_jugador(db, equipo_nombre, cedula, nombres, apellidos, fecha_nacimiento, subcategoria, numero_camiseta=""):
    if subcategoria not in SUBCATEGORIAS:
        subcategoria = "Sub 45"

    if not (cedula and nombres and apellidos):
        return None, "Cédula, nombres y apellidos son obligatorios."

    count = db.execute(
        "SELECT COUNT(*) c FROM jugadores WHERE equipo = ? AND categoria = ?",
        (equipo_nombre, CATEGORIA_ACTIVA),
    ).fetchone()["c"]
    if count >= CUPO_MAXIMO_EQUIPO:
        return None, f"El equipo {equipo_nombre} ya alcanzó el cupo máximo de {CUPO_MAXIMO_EQUIPO} jugadores."

    if subcategoria == "Juvenil" and _contar_juveniles(db, equipo_nombre) >= CUPO_MAXIMO_JUVENIL:
        return None, f"El equipo {equipo_nombre} ya alcanzó el cupo máximo de {CUPO_MAXIMO_JUVENIL} jugadores Juvenil."

    try:
        cur = db.execute(
            """INSERT INTO jugadores
               (cedula, nombres, apellidos, fecha_nacimiento, equipo, categoria, subcategoria, numero_camiseta, foto_token, fecha_registro)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cedula, nombres, apellidos, fecha_nacimiento, equipo_nombre, CATEGORIA_ACTIVA,
             subcategoria, numero_camiseta, uuid.uuid4().hex, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        db.commit()
        return cur.lastrowid, None
    except sqlite3.IntegrityError:
        return None, f"Ya existe un jugador registrado con la cédula {cedula}."


@app.route("/equipo/<int:equipo_id>/agregar_jugador", methods=["POST"])
@login_required
def agregar_jugador_equipo(equipo_id):
    db = get_db()
    equipo = db.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    if not equipo:
        flash("Equipo no encontrado.")
        return redirect(url_for("index"))
    if not equipo_permitido(equipo_id):
        flash("No tienes acceso a ese equipo.")
        return redirect(url_for("index"))

    jugador_id, error = _insertar_jugador(
        db,
        equipo["nombre"],
        request.form.get("cedula", "").strip(),
        request.form.get("nombres", "").strip(),
        request.form.get("apellidos", "").strip(),
        request.form.get("fecha_nacimiento", "").strip(),
        request.form.get("subcategoria", "Sub 45").strip(),
        request.form.get("numero_camiseta", "").strip(),
    )
    if error:
        flash(error)
    else:
        flash("Jugador registrado. Completa su ficha y envíale el link de foto.")
        return redirect(url_for("ficha_jugador", jugador_id=jugador_id))

    return redirect(url_for("detalle_equipo", equipo_id=equipo_id))


@app.route("/equipo/<int:equipo_id>/subir_nomina", methods=["POST"])
@login_required
def subir_nomina(equipo_id):
    db = get_db()
    equipo = db.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    if not equipo:
        flash("Equipo no encontrado.")
        return redirect(url_for("index"))

    if not equipo_permitido(equipo_id):
        flash("No tienes acceso a ese equipo.")
        return redirect(url_for("index"))

    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo Excel (.xlsx) para subir.")
        return redirect(url_for("detalle_equipo", equipo_id=equipo_id))

    if not archivo.filename.lower().endswith(".xlsx"):
        flash("El archivo debe ser formato .xlsx (Excel).")
        return redirect(url_for("detalle_equipo", equipo_id=equipo_id))

    try:
        wb = load_workbook(archivo, data_only=True)
        ws = wb.active
    except Exception:
        flash("No se pudo leer el archivo. Verifica que sea un Excel válido.")
        return redirect(url_for("detalle_equipo", equipo_id=equipo_id))

    cupo_actual = db.execute(
        "SELECT COUNT(*) c FROM jugadores WHERE equipo = ? AND categoria = ?",
        (equipo["nombre"], CATEGORIA_ACTIVA),
    ).fetchone()["c"]

    agregados = 0
    duplicados = 0
    incompletos = 0
    omitidos_cupo_juvenil = 0
    juveniles_actuales = _contar_juveniles(db, equipo["nombre"])
    filas = list(ws.iter_rows(min_row=2, values_only=True))

    for fila in filas:
        if cupo_actual + agregados >= CUPO_MAXIMO_EQUIPO:
            flash(f"Se alcanzó el cupo máximo de {CUPO_MAXIMO_EQUIPO}. No se cargaron todas las filas.")
            break

        if not fila or all(c is None or str(c).strip() == "" for c in fila):
            continue

        cedula = str(fila[0]).strip() if len(fila) > 0 and fila[0] is not None else ""
        nombres = str(fila[1]).strip() if len(fila) > 1 and fila[1] is not None else ""
        apellidos = str(fila[2]).strip() if len(fila) > 2 and fila[2] is not None else ""
        fecha_nac = fila[3] if len(fila) > 3 else None

        if hasattr(fecha_nac, "strftime"):
            fecha_nac = fecha_nac.strftime("%Y-%m-%d")
        elif fecha_nac is not None:
            fecha_nac = str(fecha_nac).strip()
        else:
            fecha_nac = ""

        if not (cedula and nombres and apellidos):
            incompletos += 1
            continue

        subcategoria = "Juvenil" if fecha_nac.startswith("1982") else "Sub 45"

        if subcategoria == "Juvenil":
            if juveniles_actuales >= CUPO_MAXIMO_JUVENIL:
                omitidos_cupo_juvenil += 1
                continue
            juveniles_actuales += 1

        try:
            db.execute(
                """INSERT INTO jugadores
                   (cedula, nombres, apellidos, fecha_nacimiento, equipo, categoria, subcategoria, foto_token, fecha_registro)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cedula, nombres, apellidos, fecha_nac, equipo["nombre"], CATEGORIA_ACTIVA,
                 subcategoria, uuid.uuid4().hex, datetime.now().strftime("%Y-%m-%d %H:%M")),
            )
            agregados += 1
        except sqlite3.IntegrityError:
            duplicados += 1

    db.commit()

    mensaje = f"{agregados} jugador(es) cargado(s) correctamente."
    if duplicados:
        mensaje += f" {duplicados} omitido(s) por cédula ya registrada."
    if incompletos:
        mensaje += f" {incompletos} fila(s) omitida(s) por datos incompletos."
    if omitidos_cupo_juvenil:
        mensaje += f" {omitidos_cupo_juvenil} omitido(s) por superar el cupo máximo de {CUPO_MAXIMO_JUVENIL} Juvenil."
    flash(mensaje)

    return redirect(url_for("detalle_equipo", equipo_id=equipo_id))


@app.route("/inscripcion", methods=["GET", "POST"])
@admin_required
def inscripcion():
    db = get_db()

    if request.method == "POST":
        cedula = request.form.get("cedula", "").strip()
        nombres = request.form.get("nombres", "").strip()
        apellidos = request.form.get("apellidos", "").strip()
        fecha_nacimiento = request.form.get("fecha_nacimiento", "").strip()
        equipo = request.form.get("equipo", "").strip()
        subcategoria = request.form.get("subcategoria", "Sub 45").strip()
        if subcategoria not in SUBCATEGORIAS:
            subcategoria = "Sub 45"

        if not (cedula and nombres and apellidos and equipo):
            flash("Cédula, nombres, apellidos y equipo son obligatorios.")
        else:
            count = db.execute(
                "SELECT COUNT(*) c FROM jugadores WHERE equipo = ? AND categoria = ?",
                (equipo, CATEGORIA_ACTIVA),
            ).fetchone()["c"]

            if count >= CUPO_MAXIMO_EQUIPO:
                flash(f"El equipo {equipo} ya alcanzó el cupo máximo de {CUPO_MAXIMO_EQUIPO} jugadores en {CATEGORIA_ACTIVA}.")
            elif subcategoria == "Juvenil" and _contar_juveniles(db, equipo) >= CUPO_MAXIMO_JUVENIL:
                flash(f"El equipo {equipo} ya alcanzó el cupo máximo de {CUPO_MAXIMO_JUVENIL} jugadores Juvenil.")
            else:
                try:
                    db.execute(
                        """INSERT INTO jugadores
                           (cedula, nombres, apellidos, fecha_nacimiento, equipo, categoria, subcategoria, foto_token, fecha_registro)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (cedula, nombres, apellidos, fecha_nacimiento, equipo, CATEGORIA_ACTIVA,
                         subcategoria, uuid.uuid4().hex, datetime.now().strftime("%Y-%m-%d %H:%M")),
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
        subcategorias=SUBCATEGORIAS,
    )


def _calcular_edad(fecha_nacimiento):
    try:
        y, m, d = [int(p) for p in fecha_nacimiento.split("-")]
        nacimiento = date(y, m, d)
    except (ValueError, AttributeError):
        return None
    hoy = date.today()
    edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
    return edad


@app.route("/jugador/<int:jugador_id>", methods=["GET"])
@login_required
def ficha_jugador(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("index"))
    edad = _calcular_edad(jugador["fecha_nacimiento"])
    link_foto = url_for("autofoto", token=jugador["foto_token"], _external=True)
    return render_template("ficha_jugador.html", jugador=jugador, edad=edad, subcategorias=SUBCATEGORIAS, link_foto=link_foto)


@app.route("/jugador/<int:jugador_id>/actualizar", methods=["POST"])
@login_required
def actualizar_jugador(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("index"))

    nombres = request.form.get("nombres", "").strip() or jugador["nombres"]
    apellidos = request.form.get("apellidos", "").strip() or jugador["apellidos"]
    fecha_nacimiento = request.form.get("fecha_nacimiento", "").strip()
    numero_camiseta = request.form.get("numero_camiseta", "").strip()

    foto_nombre = jugador["foto"]
    archivo = request.files.get("foto")
    if archivo and archivo.filename:
        ext = os.path.splitext(archivo.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png"):
            flash("La foto debe ser .jpg o .png.")
            return redirect(url_for("ficha_jugador", jugador_id=jugador_id))
        nuevo_nombre = f"{uuid.uuid4().hex}{ext}"
        archivo.save(os.path.join(FOTOS_DIR, nuevo_nombre))
        foto_nombre = nuevo_nombre

    db.execute(
        """UPDATE jugadores SET nombres = ?, apellidos = ?, fecha_nacimiento = ?,
           numero_camiseta = ?, foto = ? WHERE id = ?""",
        (nombres, apellidos, fecha_nacimiento, numero_camiseta, foto_nombre, jugador_id),
    )
    db.commit()
    flash("Ficha del jugador actualizada.")
    return redirect(url_for("ficha_jugador", jugador_id=jugador_id))


def _font(size, bold=False):
    candidatos = ["arialbd.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]
    for nombre in candidatos:
        try:
            return ImageFont.truetype(nombre, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _generar_carnet(jugador):
    ancho, alto = 900, 566
    logo_path = os.path.join(BASE_DIR, "static", "logo_ldbo.png")

    # ---------- FRENTE ----------
    frente = Image.new("RGB", (ancho, alto), "#eef6f0")
    draw = ImageDraw.Draw(frente)

    for y in range(110, alto):
        t = (y - 110) / (alto - 110)
        color = (
            int(240 + (214 - 240) * t),
            int(248 + (232 - 248) * t),
            int(242 + (220 - 242) * t),
        )
        draw.line([(0, y), (ancho, y)], fill=color)

    draw.rectangle([0, 0, ancho, 110], fill="#14532d")
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((90, 90))
        frente.paste(logo, (18, 12), logo)

    f_titulo = _font(30, bold=True)
    f_sub = _font(20, bold=True)
    draw.text((120, 15), "LIGA DEPORTIVA OYAMBARILLO", font=f_titulo, fill="#ffffff")
    draw.text((120, 55), "CAMPEONATO OFICIAL 2026", font=f_sub, fill="#facc15")

    foto_x, foto_y, foto_w, foto_h = 640, 140, 220, 260
    if jugador["foto"]:
        foto_path = os.path.join(FOTOS_DIR, jugador["foto"])
        if os.path.exists(foto_path):
            foto = Image.open(foto_path).convert("RGB")
            foto = ImageOps.fit(foto, (foto_w, foto_h))
            frente.paste(foto, (foto_x, foto_y))
    draw.rectangle([foto_x, foto_y, foto_x + foto_w, foto_y + foto_h], outline="#14532d", width=4)

    f_label = _font(20, bold=True)
    f_valor = _font(26, bold=True)

    y0 = 140
    draw.text((30, y0), "EQUIPO:", font=f_label, fill="#b45309")
    draw.text((30, y0 + 28), jugador["equipo"].upper(), font=f_valor, fill="#14532d")

    y1 = y0 + 90
    draw.text((30, y1), "JUGADOR:", font=f_label, fill="#b45309")
    draw.text((30, y1 + 28), jugador["apellidos"].upper(), font=f_valor, fill="#111111")
    draw.text((30, y1 + 60), jugador["nombres"].upper(), font=f_valor, fill="#111111")

    y2 = y1 + 105
    draw.text((30, y2), "C.I.:", font=f_label, fill="#b45309")
    draw.text((110, y2 - 2), jugador["cedula"], font=f_valor, fill="#111111")

    subcat = jugador["subcategoria"] or "Sub 45"
    draw.text((30, y2 + 34), subcat.upper(), font=f_label, fill="#14532d")

    if jugador["numero_camiseta"]:
        f_num = _font(46, bold=True)
        draw.text((foto_x + foto_w - 90, foto_y + foto_h + 10), f"# {jugador['numero_camiseta']}", font=f_num, fill="#14532d")

    # ---------- REVERSO ----------
    reverso = Image.new("RGB", (ancho, alto), "white")
    rdraw = ImageDraw.Draw(reverso)

    edad = _calcular_edad(jugador["fecha_nacimiento"])
    f_rlabel = _font(24, bold=True)
    f_rvalor = _font(24)

    rdraw.text((40, 50), "Categoría:", font=f_rlabel, fill="#14532d")
    rdraw.text((230, 50), (jugador["categoria"] or "") + (f" - {subcat}" if subcat == "Juvenil" else ""), font=f_rvalor, fill="black")

    rdraw.text((40, 100), "Edad:", font=f_rlabel, fill="black")
    rdraw.text((230, 100), str(edad) if edad is not None else "-", font=f_rvalor, fill="black")

    rdraw.text((40, 150), "F. Nacimiento:", font=f_rlabel, fill="black")
    rdraw.text((40, 185), jugador["fecha_nacimiento"] or "-", font=f_rvalor, fill="#14532d")

    if os.path.exists(logo_path):
        sello = Image.open(logo_path).convert("RGBA")
        sello.thumbnail((190, 190))
        sello_alpha = sello.split()[3].point(lambda p: p * 0.5)
        sello.putalpha(sello_alpha)
        reverso.paste(sello, (ancho - sello.width - 60, 230), sello)

    rdraw.line([(40, 470), (340, 470)], fill="black", width=2)
    f_firma = _font(20, bold=True)
    rdraw.text((40, 478), "PRESIDENTE", font=f_firma, fill="black")

    return frente, reverso


def _carnet_response(jugador):
    frente, reverso = _generar_carnet(jugador)

    lienzo = Image.new("RGB", (frente.width, frente.height * 2 + 20), "#dddddd")
    lienzo.paste(frente, (0, 0))
    lienzo.paste(reverso, (0, frente.height + 20))

    buf = io.BytesIO()
    lienzo.save(buf, format="PNG")
    buf.seek(0)
    nombre_archivo = f"carnet_{jugador['cedula']}.png"
    return send_file(buf, mimetype="image/png", as_attachment=False, download_name=nombre_archivo)


@app.route("/jugador/<int:jugador_id>/carnet")
@login_required
def carnet_jugador(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("index"))
    return _carnet_response(jugador)


@app.route("/jugador/<int:jugador_id>/carnet.pdf")
@login_required
def carnet_jugador_pdf(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("index"))

    frente, reverso = _generar_carnet(jugador)
    buf = io.BytesIO()
    frente.save(buf, format="PDF", save_all=True, append_images=[reverso])
    buf.seek(0)
    nombre_archivo = f"carnet_{jugador['cedula']}.pdf"
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=nombre_archivo)


@app.route("/jugador/<int:jugador_id>/eliminar", methods=["POST"])
@login_required
def eliminar_jugador(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("index"))
    db.execute("DELETE FROM jugadores WHERE id = ?", (jugador_id,))
    db.commit()
    flash("Jugador eliminado.")
    return redirect(url_for("detalle_equipo", equipo_id=db.execute("SELECT id FROM equipos WHERE nombre = ?", (jugador["equipo"],)).fetchone()["id"]))


@app.route("/autofoto/<token>", methods=["GET", "POST"])
def autofoto(token):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE foto_token = ?", (token,)).fetchone()
    if not jugador:
        return render_template("autofoto.html", jugador=None), 404

    if request.method == "POST":
        archivo = request.files.get("foto")
        if not archivo or not archivo.filename:
            flash("No se recibió ninguna foto. Inténtalo de nuevo.")
            return redirect(url_for("autofoto", token=token))

        nuevo_nombre = f"{uuid.uuid4().hex}.jpg"
        try:
            img = Image.open(archivo)
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.save(os.path.join(FOTOS_DIR, nuevo_nombre), format="JPEG", quality=88)
        except Exception:
            flash("No se pudo procesar la foto. Inténtalo de nuevo.")
            return redirect(url_for("autofoto", token=token))

        db.execute("UPDATE jugadores SET foto = ? WHERE id = ?", (nuevo_nombre, jugador["id"]))
        db.commit()
        return redirect(url_for("autofoto_listo", token=token))

    return render_template("autofoto.html", jugador=jugador)


@app.route("/autofoto/<token>/listo")
def autofoto_listo(token):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE foto_token = ?", (token,)).fetchone()
    if not jugador:
        return render_template("autofoto.html", jugador=None), 404
    return render_template("autofoto_listo.html", jugador=jugador, token=token)


@app.route("/autofoto/<token>/carnet")
def autofoto_carnet(token):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE foto_token = ?", (token,)).fetchone()
    if not jugador:
        return render_template("autofoto.html", jugador=None), 404
    return _carnet_response(jugador)


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
