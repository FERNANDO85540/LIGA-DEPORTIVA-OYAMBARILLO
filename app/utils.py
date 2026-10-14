"""Utilidades genéricas (conversión de números y textos, cálculo de edad)."""
from datetime import date


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
