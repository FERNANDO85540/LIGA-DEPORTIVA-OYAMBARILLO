import io
import os
import re
import sqlite3
import uuid
from datetime import datetime, date
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, g, send_file, jsonify
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont, ImageOps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "liga.db")
FOTOS_DIR = os.path.join(BASE_DIR, "static", "fotos_jugadores")
os.makedirs(FOTOS_DIR, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USANDO_POSTGRES = bool(DATABASE_URL)

if USANDO_POSTGRES:
    import psycopg2
    import psycopg2.extras
    IntegrityError = psycopg2.IntegrityError
else:
    IntegrityError = sqlite3.IntegrityError


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


@app.teardown_appcontext
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
    db = DBWrapper(_conectar())

    tipo_id = "SERIAL PRIMARY KEY" if USANDO_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

    db.execute(f"""
        CREATE TABLE IF NOT EXISTS jugadores (
            id {tipo_id},
            cedula TEXT NOT NULL UNIQUE,
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

    count_row = db.execute("SELECT COUNT(*) c FROM equipos").fetchone()
    count = count_row["c"]
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
            flash(f"Equipo '{nombre}' agregado.", "ok")
        except IntegrityError:
            db.rollback()
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
                flash(f"Equipo renombrado a '{nuevo_nombre}'.", "ok")
            except IntegrityError:
                db.rollback()
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
            flash(f"Equipo '{equipo['nombre']}' eliminado.", "ok")
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
            flash(f"Acceso del equipo actualizado: usuario '{usuario}'.", "ok")
        except IntegrityError:
            db.rollback()
            flash(f"El usuario '{usuario}' ya está en uso por otro equipo.")
    return redirect(url_for("detalle_equipo", equipo_id=equipo_id))


@app.route("/mi_equipo/cambiar_clave", methods=["POST"])
@login_required
def cambiar_clave_equipo():
    """El delegado del equipo cambia su propia clave de acceso, a la que
    prefiera. El administrador conserva acceso total de todas formas (puede
    ver y volver a cambiar la clave de cualquier equipo desde su panel)."""
    if session.get("rol") != "equipo":
        flash("Esta opción es solo para el acceso de delegado de equipo.")
        return redirect(url_for("index"))

    equipo_id = session.get("equipo_id")
    nueva_clave = request.form.get("nueva_clave", "").strip()
    confirmar_clave = request.form.get("confirmar_clave", "").strip()

    if not nueva_clave or len(nueva_clave) < 4:
        flash("La nueva clave debe tener al menos 4 caracteres.")
    elif nueva_clave != confirmar_clave:
        flash("Las dos claves no coinciden.")
    else:
        db = get_db()
        db.execute("UPDATE equipos SET clave = ? WHERE id = ?", (nueva_clave, equipo_id))
        db.commit()
        flash("Tu clave de acceso se actualizó correctamente.", "ok")

    return redirect(url_for("detalle_equipo", equipo_id=equipo_id))


@app.route("/equipos/<int:equipo_id>/credenciales/quitar", methods=["POST"])
@admin_required
def quitar_credenciales_equipo(equipo_id):
    db = get_db()
    db.execute("UPDATE equipos SET usuario = NULL, clave = NULL WHERE id = ?", (equipo_id,))
    db.commit()
    flash("Se quitó el acceso del delegado para este equipo.", "ok")
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


@app.route("/jugadores_liga")
@login_required
def jugadores_liga():
    """Lista de todos los jugadores inscritos en la liga, de todos los
    equipos, visible tanto para el admin como para los delegados -- para
    que cualquiera pueda revisar quién está inscrito y en qué equipo."""
    db = get_db()
    jugadores = db.execute(
        "SELECT * FROM jugadores WHERE categoria = ? ORDER BY equipo, apellidos", (CATEGORIA_ACTIVA,)
    ).fetchall()
    equipos_distintos = sorted(set(j["equipo"] for j in jugadores))
    return render_template(
        "jugadores_liga.html", jugadores=jugadores, categoria=CATEGORIA_ACTIVA, total_equipos=len(equipos_distintos)
    )


@app.route("/exportar_general")
@admin_required
def exportar_general():
    db = get_db()
    jugadores = db.execute(
        "SELECT * FROM jugadores WHERE categoria = ? ORDER BY equipo, apellidos", (CATEGORIA_ACTIVA,)
    ).fetchall()
    return _exportar_jugadores_excel(jugadores, "jugadores_liga_oyambarillo.xlsx", incluir_equipo=True)


FORMAS_PAGO_VALIDAS = {"Efectivo", "Depósito", "Transferencia"}


@app.route("/equipo/<int:equipo_id>/pago", methods=["POST"])
@admin_required
def actualizar_pago_equipo(equipo_id):
    db = get_db()
    valor_inscripcion = _to_float(request.form.get("valor_inscripcion", "0"))
    abono = _to_float(request.form.get("abono", "0"))
    forma_pago = request.form.get("forma_pago", "Efectivo").strip()
    if forma_pago not in FORMAS_PAGO_VALIDAS:
        forma_pago = "Efectivo"
    comprobante_pago = request.form.get("comprobante_pago", "").strip()
    db.execute(
        "UPDATE equipos SET valor_inscripcion = ?, abono = ?, forma_pago = ?, comprobante_pago = ? WHERE id = ?",
        (valor_inscripcion, abono, forma_pago, comprobante_pago, equipo_id),
    )
    db.commit()
    flash("Datos de pago actualizados.", "ok")
    return redirect(url_for("detalle_equipo", equipo_id=equipo_id))


def _guardar_imagen_subida(archivo):
    if not archivo or not archivo.filename:
        return None
    ext = os.path.splitext(archivo.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        return None
    nuevo_nombre = f"{uuid.uuid4().hex}.jpg"
    try:
        img = Image.open(archivo)
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.save(os.path.join(FOTOS_DIR, nuevo_nombre), format="JPEG", quality=88)
    except Exception:
        return None
    return nuevo_nombre


def _subcategoria_por_nacimiento(fecha_nacimiento):
    return "Juvenil" if (fecha_nacimiento or "").strip().startswith("1982") else "Sub 45"


def _jugador_califica(fecha_nacimiento):
    """Solo califica quien nace en 1982 (Juvenil, cupo aparte) o cumple 45
    años en el año actual de la temporada (Sub 45). Nacer despues de 1982
    y no cumplir 45 este año no corresponde a ninguna categoria."""
    fecha_nacimiento = (fecha_nacimiento or "").strip()
    if fecha_nacimiento.startswith("1982"):
        return True
    try:
        anio_nacimiento = int(fecha_nacimiento[:4])
    except (ValueError, IndexError):
        return False
    return (date.today().year - anio_nacimiento) >= 45


def _insertar_jugador(db, equipo_nombre, cedula, nombres, apellidos, fecha_nacimiento, subcategoria,
                       numero_camiseta="", foto=None, cedula_frontal=None, cedula_reverso=None):
    subcategoria = _subcategoria_por_nacimiento(fecha_nacimiento)

    if not (cedula and nombres and apellidos):
        return None, "Cédula, nombres y apellidos son obligatorios."

    if not _jugador_califica(fecha_nacimiento):
        return None, ("Cédula no califica: según la fecha de nacimiento, no cumple 45 años este año "
                       "ni nació en 1982 (Juvenil). No corresponde a ninguna categoría de esta liga.")

    count = db.execute(
        "SELECT COUNT(*) c FROM jugadores WHERE equipo = ? AND categoria = ?",
        (equipo_nombre, CATEGORIA_ACTIVA),
    ).fetchone()["c"]
    if count >= CUPO_MAXIMO_EQUIPO:
        return None, f"El equipo {equipo_nombre} ya alcanzó el cupo máximo de {CUPO_MAXIMO_EQUIPO} jugadores."

    if subcategoria == "Juvenil" and _contar_juveniles(db, equipo_nombre) >= CUPO_MAXIMO_JUVENIL:
        return None, f"El equipo {equipo_nombre} ya alcanzó el cupo máximo de {CUPO_MAXIMO_JUVENIL} jugadores Juvenil."

    returning = " RETURNING id" if USANDO_POSTGRES else ""
    try:
        cur = db.execute(
            f"""INSERT INTO jugadores
               (cedula, nombres, apellidos, fecha_nacimiento, equipo, categoria, subcategoria, numero_camiseta,
                foto, cedula_frontal, cedula_reverso, foto_token, fecha_registro)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?){returning}""",
            (cedula, nombres, apellidos, fecha_nacimiento, equipo_nombre, CATEGORIA_ACTIVA,
             subcategoria, numero_camiseta, foto, cedula_frontal, cedula_reverso,
             uuid.uuid4().hex, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        db.commit()
        if USANDO_POSTGRES:
            return cur.fetchone()["id"], None
        return cur.lastrowid, None
    except IntegrityError:
        db.rollback()
        return None, f"Ya existe un jugador registrado con la cédula {cedula}."


@app.route("/api/cedula_existe")
@login_required
def api_cedula_existe():
    """Consulta rápida (para avisar en el formulario antes de guardar) si
    ya existe un jugador registrado con esa cédula, en cualquier equipo —
    la cédula es única en todo el sistema."""
    cedula = request.args.get("cedula", "").strip()
    if not cedula:
        return jsonify({"existe": False})
    db = get_db()
    jugador = db.execute(
        "SELECT nombres, apellidos, equipo FROM jugadores WHERE cedula = ?", (cedula,)
    ).fetchone()
    if not jugador:
        return jsonify({"existe": False})
    return jsonify({
        "existe": True,
        "nombres": jugador["nombres"],
        "apellidos": jugador["apellidos"],
        "equipo": jugador["equipo"],
    })


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

    foto = _guardar_imagen_subida(request.files.get("foto"))
    cedula_frontal = _guardar_imagen_subida(request.files.get("cedula_frontal"))
    cedula_reverso = _guardar_imagen_subida(request.files.get("cedula_reverso"))

    jugador_id, error = _insertar_jugador(
        db,
        equipo["nombre"],
        request.form.get("cedula", "").strip(),
        request.form.get("nombres", "").strip(),
        request.form.get("apellidos", "").strip(),
        request.form.get("fecha_nacimiento", "").strip(),
        request.form.get("subcategoria", "Sub 45").strip(),
        request.form.get("numero_camiseta", "").strip(),
        foto=foto,
        cedula_frontal=cedula_frontal,
        cedula_reverso=cedula_reverso,
    )
    if error:
        flash(error)
    else:
        flash("Jugador registrado correctamente.", "ok")
        return redirect(url_for("ficha_jugador", jugador_id=jugador_id))

    return redirect(url_for("detalle_equipo", equipo_id=equipo_id))


@app.route("/inscripcion", methods=["GET"])
@admin_required
def inscripcion():
    db = get_db()

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
    equipo_row = db.execute("SELECT id FROM equipos WHERE nombre = ?", (jugador["equipo"],)).fetchone()
    equipo_id = equipo_row["id"] if equipo_row else None
    return render_template("ficha_jugador.html", jugador=jugador, edad=edad, subcategorias=SUBCATEGORIAS, equipo_id=equipo_id)


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

    if jugador["calificado"] and session.get("rol") != "admin":
        flash("Este jugador ya fue calificado y no se puede modificar. Contacta a la Comisión de Calificación.")
        return redirect(url_for("ficha_jugador", jugador_id=jugador_id))

    nombres = request.form.get("nombres", "").strip() or jugador["nombres"]
    apellidos = request.form.get("apellidos", "").strip() or jugador["apellidos"]
    fecha_nacimiento = request.form.get("fecha_nacimiento", "").strip() or jugador["fecha_nacimiento"]
    numero_camiseta = request.form.get("numero_camiseta", "").strip()
    subcategoria = _subcategoria_por_nacimiento(fecha_nacimiento)

    if not _jugador_califica(fecha_nacimiento):
        flash("Cédula no califica: según la fecha de nacimiento, no cumple 45 años este año ni nació en 1982 (Juvenil).")
        return redirect(url_for("ficha_jugador", jugador_id=jugador_id))

    if (subcategoria == "Juvenil" and jugador["subcategoria"] != "Juvenil"
            and _contar_juveniles(db, jugador["equipo"]) >= CUPO_MAXIMO_JUVENIL):
        flash(f"No se puede cambiar la fecha: el equipo ya alcanzó el cupo máximo de {CUPO_MAXIMO_JUVENIL} jugadores Juvenil.")
        return redirect(url_for("ficha_jugador", jugador_id=jugador_id))

    foto_nombre = _guardar_imagen_subida(request.files.get("foto")) or jugador["foto"]
    cedula_frontal = _guardar_imagen_subida(request.files.get("cedula_frontal")) or jugador["cedula_frontal"]
    cedula_reverso = _guardar_imagen_subida(request.files.get("cedula_reverso")) or jugador["cedula_reverso"]

    db.execute(
        """UPDATE jugadores SET nombres = ?, apellidos = ?, fecha_nacimiento = ?, subcategoria = ?,
           numero_camiseta = ?, foto = ?, cedula_frontal = ?, cedula_reverso = ? WHERE id = ?""",
        (nombres, apellidos, fecha_nacimiento, subcategoria, numero_camiseta, foto_nombre,
         cedula_frontal, cedula_reverso, jugador_id),
    )
    db.commit()
    flash("Ficha del jugador actualizada.", "ok")
    return redirect(url_for("ficha_jugador", jugador_id=jugador_id))


CAMPOS_FOTO_VALIDOS = {"foto", "cedula_frontal", "cedula_reverso"}


@app.route("/jugador/<int:jugador_id>/quitar_foto/<campo>", methods=["POST"])
@login_required
def quitar_foto_jugador(jugador_id, campo):
    if campo not in CAMPOS_FOTO_VALIDOS:
        flash("Documento no válido.")
        return redirect(url_for("index"))

    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("index"))
    if not jugador_permitido(db, jugador):
        flash("No tienes acceso a ese jugador.")
        return redirect(url_for("index"))

    if jugador["calificado"] and session.get("rol") != "admin":
        flash("Este jugador ya fue calificado y no se puede modificar. Contacta a la Comisión de Calificación.")
        return redirect(url_for("ficha_jugador", jugador_id=jugador_id))

    db.execute(f"UPDATE jugadores SET {campo} = NULL WHERE id = ?", (jugador_id,))
    db.commit()
    flash("Documento eliminado.", "ok")
    return redirect(url_for("ficha_jugador", jugador_id=jugador_id))


@app.route("/jugador/<int:jugador_id>/calificar", methods=["POST"])
@admin_required
def calificar_jugador(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("index"))
    nuevo_estado = 0 if jugador["calificado"] else 1
    db.execute("UPDATE jugadores SET calificado = ? WHERE id = ?", (nuevo_estado, jugador_id))
    db.commit()
    flash("Jugador calificado correctamente." if nuevo_estado else "Se quitó la calificación del jugador.", "ok")
    return redirect(request.referrer or url_for("ficha_jugador", jugador_id=jugador_id))


def _font(size, bold=False):
    candidatos = ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    for nombre in candidatos:
        try:
            return ImageFont.truetype(nombre, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _texto_centrado(draw, cx, y, texto, font, fill):
    bbox = draw.textbbox((0, 0), texto, font=font)
    ancho_texto = bbox[2] - bbox[0]
    draw.text((cx - ancho_texto / 2, y), texto, font=font, fill=fill)


def _generar_carnet(jugador):
    ancho, alto = 900, 566
    logo_path = os.path.join(BASE_DIR, "static", "logo_ldbo.png")

    # ---------- FRENTE ----------
    frente = Image.new("RGB", (ancho, alto), "#eef6f0")
    draw = ImageDraw.Draw(frente)

    for y in range(130, alto):
        t = (y - 130) / (alto - 130)
        color = (
            int(240 + (214 - 240) * t),
            int(248 + (232 - 248) * t),
            int(242 + (220 - 242) * t),
        )
        draw.line([(0, y), (ancho, y)], fill=color)

    draw.rectangle([0, 0, ancho, 130], fill="#ffffff")
    draw.rectangle([0, 127, ancho, 130], fill="#14532d")

    f_titulo = _font(32, bold=True)
    f_sub = _font(22, bold=True)
    _texto_centrado(draw, ancho / 2, 18, "LIGA DEPORTIVA OYAMBARILLO", f_titulo, "#14532d")
    _texto_centrado(draw, ancho / 2, 62, "CAMPEONATO OFICIAL 2026", f_sub, "#b45309")

    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((120, 120))
        frente.paste(logo, (18, 5), logo)

    foto_x, foto_y, foto_w, foto_h = 610, 155, 250, 280
    if jugador["foto"]:
        foto_path = os.path.join(FOTOS_DIR, jugador["foto"])
        if os.path.exists(foto_path):
            foto = Image.open(foto_path).convert("RGB")
            foto = ImageOps.fit(foto, (foto_w, foto_h))
            frente.paste(foto, (foto_x, foto_y))
    draw.rectangle([foto_x, foto_y, foto_x + foto_w, foto_y + foto_h], outline="#14532d", width=4)

    if jugador["numero_camiseta"]:
        f_num = _font(64, bold=True)
        _texto_centrado(draw, foto_x + foto_w / 2, foto_y + foto_h + 14, f"# {jugador['numero_camiseta']}", f_num, "#14532d")

    f_label = _font(24, bold=True)
    f_valor = _font(34, bold=True)

    y0 = 165
    draw.text((30, y0), "EQUIPO:", font=f_label, fill="#b45309")
    draw.text((30, y0 + 32), jugador["equipo"].upper(), font=f_valor, fill="#14532d")

    y1 = y0 + 105
    draw.text((30, y1), "JUGADOR:", font=f_label, fill="#b45309")
    draw.text((30, y1 + 32), jugador["apellidos"].upper(), font=f_valor, fill="#111111")
    draw.text((30, y1 + 72), jugador["nombres"].upper(), font=f_valor, fill="#111111")

    y2 = y1 + 130
    draw.text((30, y2), "C.I.:", font=f_label, fill="#b45309")
    draw.text((115, y2 - 5), jugador["cedula"], font=f_valor, fill="#111111")

    subcat = jugador["subcategoria"] or "Sub 45"
    f_cat = _font(26, bold=True)
    draw.text((30, y2 + 45), subcat.upper(), font=f_cat, fill="#14532d")

    # ---------- REVERSO ----------
    reverso = Image.new("RGB", (ancho, alto), "white")
    rdraw = ImageDraw.Draw(reverso)

    edad = _calcular_edad(jugador["fecha_nacimiento"])
    f_rlabel = _font(30, bold=True)
    f_rvalor = _font(30)

    rdraw.text((50, 70), "Categoría:", font=f_rlabel, fill="#14532d")
    rdraw.text((300, 70), (jugador["categoria"] or "") + (f" - {subcat}" if subcat == "Juvenil" else ""), font=f_rvalor, fill="black")

    rdraw.text((50, 130), "Edad:", font=f_rlabel, fill="black")
    rdraw.text((300, 130), str(edad) if edad is not None else "-", font=f_rvalor, fill="black")

    rdraw.text((50, 190), "F. Nacimiento:", font=f_rlabel, fill="black")
    rdraw.text((50, 232), jugador["fecha_nacimiento"] or "-", font=f_rvalor, fill="#14532d")

    if os.path.exists(logo_path):
        sello = Image.open(logo_path).convert("RGBA")
        sello.thumbnail((220, 220))
        sello_alpha = sello.split()[3].point(lambda p: p * 0.5)
        sello.putalpha(sello_alpha)
        reverso.paste(sello, (ancho - sello.width - 60, 280), sello)

    rdraw.line([(50, 490), (380, 490)], fill="black", width=2)
    f_firma = _font(24, bold=True)
    rdraw.text((50, 498), "PRESIDENTE", font=f_firma, fill="black")

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
    equipo_id = db.execute("SELECT id FROM equipos WHERE nombre = ?", (jugador["equipo"],)).fetchone()["id"]
    if jugador["calificado"] and session.get("rol") != "admin":
        flash("Este jugador ya fue calificado y no se puede eliminar. Contacta a la Comisión de Calificación.")
        return redirect(url_for("detalle_equipo", equipo_id=equipo_id))
    db.execute("DELETE FROM jugadores WHERE id = ?", (jugador_id,))
    db.commit()
    flash("Jugador eliminado.", "ok")
    return redirect(url_for("detalle_equipo", equipo_id=equipo_id))


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
