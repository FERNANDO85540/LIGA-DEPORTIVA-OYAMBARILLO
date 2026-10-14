"""Normalización de los datos leídos del Excel de importación de jugadores."""
import re
from datetime import datetime, date


def _normalizar_nombre_equipo(nombre):
    return re.sub(r"\s+", " ", (nombre or "").strip()).upper()


def _normalizar_cedula_importada(valor):
    """Recupera cédulas que Excel guardó como número y les comió el 0 inicial
    (ej. 803434299 -> 0803434299). Devuelve None si no son 10 dígitos válidos."""
    if valor is None:
        return None
    if isinstance(valor, float):
        if not valor.is_integer():
            return None
        valor = int(valor)
    texto = str(valor).strip()
    if not texto.isdigit():
        return None
    if len(texto) < 10:
        texto = texto.zfill(10)
    return texto if len(texto) == 10 else None


def _normalizar_fecha_importada(valor):
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d")
    if isinstance(valor, date):
        return valor.strftime("%Y-%m-%d")
    texto = str(valor or "").strip()
    if not texto:
        return ""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _normalizar_numero_camiseta_importado(valor):
    if valor is None:
        return ""
    if isinstance(valor, float):
        return str(int(valor)) if valor.is_integer() else str(valor).strip()
    return str(valor).strip()
