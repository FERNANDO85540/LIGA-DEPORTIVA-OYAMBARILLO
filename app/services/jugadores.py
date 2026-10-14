"""Inscripción de jugadores: validación de edad/cupos, subcategoría y fotos."""
import os
import uuid
from datetime import date

from PIL import Image, ImageOps

from config import CATEGORIA_ACTIVA, CUPO_MAXIMO_EQUIPO, FOTOS_DIR, USANDO_POSTGRES
from app.database import IntegrityError
from app.services.liga import (
    _categoria_valida, _contar_juveniles, _edad_minima_categoria, _limite_juveniles_categoria,
)
from app.utils import _mayuscula, ahora_ecuador


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
        img.thumbnail((1600, 1600), Image.LANCZOS)
        img.save(os.path.join(FOTOS_DIR, nuevo_nombre), format="JPEG", quality=88)
    except Exception:
        return None
    return nuevo_nombre


def _subcategoria_por_nacimiento(fecha_nacimiento, categoria=CATEGORIA_ACTIVA):
    # "Juvenil" marca una excepción de edad con cupo aparte dentro de la categoría:
    # - Sub 45: histórico, exclusivo de nacidos en 1982.
    # - Senior: menores de edad (14 a 17 años) admitidos con cupo aparte.
    # Cualquier otra categoría que arme el admin no tiene sub-tier.
    fecha_nacimiento = (fecha_nacimiento or "").strip()
    if categoria == "Sub 45":
        return "Juvenil" if fecha_nacimiento.startswith("1982") else "Sub 45"
    if categoria == "Senior":
        try:
            edad = date.today().year - int(fecha_nacimiento[:4])
        except (ValueError, IndexError):
            return categoria
        return "Juvenil" if 14 <= edad <= 17 else categoria
    return categoria


def _jugador_califica(db, fecha_nacimiento, categoria=CATEGORIA_ACTIVA):
    """Sub 45: solo califica quien nace en 1982 (Juvenil, cupo aparte) o cumple
    la edad mínima de la categoría en el año actual de la temporada. Las demás
    categorías usan la edad mínima configurada (o ninguna, si no se definió)."""
    fecha_nacimiento = (fecha_nacimiento or "").strip()
    if categoria == "Sub 45" and fecha_nacimiento.startswith("1982"):
        return True

    edad_minima = _edad_minima_categoria(db, categoria)
    if edad_minima is None:
        return True

    try:
        anio_nacimiento = int(fecha_nacimiento[:4])
    except (ValueError, IndexError):
        return False
    return (date.today().year - anio_nacimiento) >= edad_minima


def _validar_cedula_en_torneo(db, cedula, categoria, excluir_id=None):
    """Un jugador puede inscribirse en varios campeonatos (ej. Sub 45 y Senior),
    pero en un mismo campeonato solo en UN equipo. Devuelve el error o None."""
    fila = db.execute(
        "SELECT id, equipo, division FROM jugadores WHERE cedula = ? AND categoria = ?", (cedula, categoria)
    ).fetchone()
    if fila and fila["id"] != excluir_id:
        serie = f" - {fila['division']}" if fila["division"] else ""
        return (f"La cédula {cedula} ya está inscrita en el campeonato {categoria}{serie} con el equipo "
                f"{fila['equipo']}. Un jugador solo puede estar en un equipo por campeonato.")
    return None


def _normalizar_dorsal(numero):
    numero = (numero or "").strip()
    return str(int(numero)) if numero.isdigit() else numero.upper()


def _validar_dorsal_unico(db, equipo_nombre, categoria, numero_camiseta, excluir_id=None):
    """No puede haber dos jugadores con el mismo número de camiseta en un equipo
    ("7" y "07" se consideran el mismo). Sin número no se valida."""
    dorsal = _normalizar_dorsal(numero_camiseta)
    if not dorsal:
        return None
    for fila in db.execute(
        "SELECT id, nombres, apellidos, numero_camiseta FROM jugadores WHERE equipo = ? AND categoria = ?",
        (equipo_nombre, categoria),
    ).fetchall():
        if fila["id"] != excluir_id and _normalizar_dorsal(fila["numero_camiseta"]) == dorsal:
            return (f"El dorsal {numero_camiseta.strip()} ya lo usa {fila['apellidos']} {fila['nombres']} "
                    f"en {equipo_nombre}. Elige otro número.")
    return None


def _insertar_jugador(db, equipo_nombre, cedula, nombres, apellidos, fecha_nacimiento, categoria,
                       numero_camiseta="", foto=None, cedula_frontal=None, cedula_reverso=None,
                       omitir_validacion_edad=False):
    categoria = _categoria_valida(db, categoria)
    nombres = _mayuscula(nombres)
    apellidos = _mayuscula(apellidos)
    subcategoria = _subcategoria_por_nacimiento(fecha_nacimiento, categoria)

    if not (cedula and nombres and apellidos):
        return None, "Cédula, nombres y apellidos son obligatorios."

    if not omitir_validacion_edad and not _jugador_califica(db, fecha_nacimiento, categoria):
        edad_minima = _edad_minima_categoria(db, categoria)
        if categoria == "Sub 45":
            return None, ("Cédula no califica: según la fecha de nacimiento, no cumple 45 años este año "
                           "ni nació en 1982 (Juvenil). No corresponde a ningún campeonato de esta liga.")
        return None, (f"Cédula no califica: el campeonato {categoria} exige {edad_minima} años cumplidos "
                       "este año. No corresponde a este campeonato.")

    error = _validar_cedula_en_torneo(db, cedula, categoria)
    if error:
        return None, error
    error = _validar_dorsal_unico(db, equipo_nombre, categoria, numero_camiseta)
    if error:
        return None, error

    count = db.execute(
        "SELECT COUNT(*) c FROM jugadores WHERE equipo = ? AND categoria = ?",
        (equipo_nombre, categoria),
    ).fetchone()["c"]
    if count >= CUPO_MAXIMO_EQUIPO:
        return None, f"El equipo {equipo_nombre} ya alcanzó el cupo máximo de {CUPO_MAXIMO_EQUIPO} jugadores."

    limite_juveniles = _limite_juveniles_categoria(db, categoria)
    if (subcategoria == "Juvenil" and limite_juveniles is not None
            and _contar_juveniles(db, equipo_nombre, categoria) >= limite_juveniles):
        return None, f"El equipo {equipo_nombre} ya alcanzó el cupo máximo de {limite_juveniles} jugadores Juvenil."

    ahora = ahora_ecuador().strftime("%Y-%m-%d %H:%M")
    documentos_fecha = ahora if (foto or cedula_frontal or cedula_reverso) else None
    equipo_row = db.execute("SELECT division FROM equipos WHERE nombre = ?", (equipo_nombre,)).fetchone()
    division = equipo_row["division"] if equipo_row else ""

    returning = " RETURNING id" if USANDO_POSTGRES else ""
    try:
        cur = db.execute(
            f"""INSERT INTO jugadores
               (cedula, nombres, apellidos, fecha_nacimiento, equipo, categoria, division, subcategoria, numero_camiseta,
                foto, cedula_frontal, cedula_reverso, foto_token, fecha_registro, documentos_fecha)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?){returning}""",
            (cedula, nombres, apellidos, fecha_nacimiento, equipo_nombre, categoria, division,
             subcategoria, numero_camiseta, foto, cedula_frontal, cedula_reverso,
             uuid.uuid4().hex, ahora, documentos_fecha),
        )
        db.commit()
        if USANDO_POSTGRES:
            return cur.fetchone()["id"], None
        return cur.lastrowid, None
    except IntegrityError:
        db.rollback()
        return None, f"La cédula {cedula} ya está inscrita en el campeonato {categoria}."


def _ordenar_por_numero_camiseta(jugadores):
    """Ordena por # de camiseta (ascendente, sin camiseta al final) para que
    la hoja de Vocalía coincida con el orden físico de los carnets."""
    def clave(j):
        numero = (j["numero_camiseta"] or "").strip()
        valor = int(numero) if numero.isdigit() else 9999
        return (valor, j["apellidos"] or "", j["nombres"] or "")
    return sorted(jugadores, key=clave)


def _jugadores_que_ya_jugaron(db, jugador_ids):
    """Ids (de entre `jugador_ids`) que ya disputaron al menos un partido:
    marcados como "Participó" en una hoja de Vocalía o con goles registrados."""
    ids = [int(i) for i in jugador_ids]
    if not ids:
        return set()
    marcas = ",".join("?" * len(ids))
    filas = db.execute(
        f"""SELECT jugador_id FROM vocalia_asistencia WHERE participo = 1 AND jugador_id IN ({marcas})
            UNION SELECT jugador_id FROM goles WHERE jugador_id IN ({marcas})""",
        (*ids, *ids),
    ).fetchall()
    return {f["jugador_id"] for f in filas}
