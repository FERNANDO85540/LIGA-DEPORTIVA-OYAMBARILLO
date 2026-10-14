"""Utilidades genéricas (conversión de números y textos, fechas y edad)."""
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    ZONA_LIGA = ZoneInfo("America/Guayaquil")
except Exception:  # sin base de zonas horarias: Ecuador continental es UTC-5 fijo (sin horario de verano)
    ZONA_LIGA = timezone(timedelta(hours=-5), "America/Guayaquil")


def ahora_ecuador():
    """Fecha y hora actual en Quito/Guayaquil (sin tzinfo, para guardarla como
    texto igual que antes). El servidor corre en UTC, por eso no se usa datetime.now()."""
    return datetime.now(ZONA_LIGA).replace(tzinfo=None)


def formatear_fecha_hora(texto):
    """'2026-10-14 15:30' -> '14/10/2026 15:30' (texto vacío si no hay fecha)."""
    if not texto:
        return ""
    try:
        return datetime.strptime(texto[:16], "%Y-%m-%d %H:%M").strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return texto


def _to_float(value):
    try:
        return round(float(str(value).replace(",", ".").strip()), 2)
    except (TypeError, ValueError):
        return 0.0


def _mayuscula(texto):
    """MAYÚSCULAS respetando tildes/ñ (str.upper() de Python maneja Unicode
    bien; el UPPER() de SQL no, por eso esto se hace siempre en Python)."""
    return (texto or "").strip().upper()


def _calcular_edad(fecha_nacimiento):
    try:
        y, m, d = [int(p) for p in fecha_nacimiento.split("-")]
        nacimiento = date(y, m, d)
    except (ValueError, AttributeError):
        return None
    hoy = date.today()
    edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
    return edad


def volver_a(url_por_defecto):
    """Redirección "de vuelta a donde estaba el usuario".

    Los formularios POST llevan un campo oculto `next` (lo agrega base.html
    automáticamente) con la ruta y los filtros de la vista desde la que se
    enviaron (ej. /tecnica?categoria=Senior&division=Máxima). Si viene y es
    una ruta interna, se vuelve ahí; si no, a `url_por_defecto`."""
    from flask import redirect, request

    destino = (request.form.get("next") or "").strip()
    if destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return redirect(destino)
    return redirect(url_por_defecto)
