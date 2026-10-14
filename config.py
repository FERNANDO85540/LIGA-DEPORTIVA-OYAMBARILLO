"""Configuración y constantes de la liga.

Todo lo que antes estaba como constante suelta al inicio de app.py vive aquí:
rutas de datos, credenciales de las comisiones (desde variables de entorno)
y las reglas fijas del campeonato (cupos, categoría por defecto, etc.).
"""
import os

# Raíz del proyecto (donde está este archivo).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, "app")
STATIC_DIR = os.path.join(APP_DIR, "static")
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")

# En Render, /data es el disco persistente (sobrevive a los despliegues).
# Si no existe (ej. en una máquina local), se usa la carpeta del proyecto como antes.
# LIGA_DATA_DIR permite apuntar a otra carpeta (útil para pruebas).
DATA_DIR = os.environ.get("LIGA_DATA_DIR") or ("/data" if os.path.isdir("/data") else BASE_DIR)
DB_PATH = os.path.join(DATA_DIR, "liga.db")
FOTOS_DIR = os.path.join(DATA_DIR, "fotos_jugadores")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USANDO_POSTGRES = bool(DATABASE_URL)

# Credenciales de acceso por rol (las de las comisiones quedan deshabilitadas
# mientras su clave esté vacía).
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "Oyambarillo2026")
IMPRENTA_USER = os.environ.get("IMPRENTA_USER", "carnets")
IMPRENTA_PASS = os.environ.get("IMPRENTA_PASS", "")
CALIFICACION_USER = os.environ.get("CALIFICACION_USER", "comision")
CALIFICACION_PASS = os.environ.get("CALIFICACION_PASS", "")
SANCIONES_USER = os.environ.get("SANCIONES_USER", "sanciones")
SANCIONES_PASS = os.environ.get("SANCIONES_PASS", "")
TECNICA_USER = os.environ.get("TECNICA_USER", "tecnica")
TECNICA_PASS = os.environ.get("TECNICA_PASS", "")
VOCALIA_USER = os.environ.get("VOCALIA_USER", "vocalia")
VOCALIA_PASS = os.environ.get("VOCALIA_PASS", "")

# Reglas del campeonato.
CUPO_MAXIMO_EQUIPO = 35
CUPO_MAXIMO_JUVENIL = 3
CATEGORIA_ACTIVA = "Sub 45"
SUBCATEGORIAS = ["Sub 45", "Juvenil"]

EQUIPOS_INICIALES = [
    "San Juan", "El Progreso", "La Union", "Santa Rosa",
    "Los Andes", "Independiente", "Deportivo Central", "Juventud",
]

FORMAS_PAGO_VALIDAS = {"Efectivo", "Depósito", "Transferencia"}
CAMPOS_FOTO_VALIDOS = {"foto", "cedula_frontal", "cedula_reverso"}
COLUMNAS_IMPORTACION_ESPERADAS = ["Equipo", "Número/Dorsal", "NOMBRES", "APELLIDOS", "Cédula", "Fecha"]

# Carnets: proporción 93x64mm (tamaño real de la lámina de laminado).
CARNET_ANCHO_MM = 93
CARNET_ALTO_MM = 64
CARNET_PDF_DPI = 120


class Config:
    """Configuración que se carga en app.config dentro del Application Factory."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")
    DB_PATH = DB_PATH
    FOTOS_DIR = FOTOS_DIR
    DATABASE_URL = DATABASE_URL
