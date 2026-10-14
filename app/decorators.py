"""Decoradores de autenticación por rol y chequeos de acceso a equipos/jugadores."""
from functools import wraps

from flask import flash, redirect, session, url_for


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login"))
        if session.get("rol") != "admin":
            flash("Esta acción requiere acceso de administrador.")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def imprenta_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login"))
        if session.get("rol") not in ("admin", "imprenta"):
            flash("Esta acción requiere acceso al módulo de carnets.")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def calificacion_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login"))
        if session.get("rol") not in ("admin", "calificacion"):
            flash("Esta acción requiere acceso al módulo de la Comisión de Calificación.")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def sanciones_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login"))
        if session.get("rol") not in ("admin", "sanciones"):
            flash("Esta acción requiere acceso al módulo de Penas y Sanciones.")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def tecnica_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login"))
        if session.get("rol") not in ("admin", "tecnica"):
            flash("Esta acción requiere acceso al módulo de la Comisión Técnica.")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def vocalia_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login"))
        if session.get("rol") not in ("admin", "vocalia"):
            flash("Esta acción requiere acceso al módulo de Vocalía.")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return wrapper


def tecnica_o_vocalia_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login"))
        if session.get("rol") not in ("admin", "tecnica", "vocalia"):
            flash("Esta acción requiere acceso a Comisión Técnica o Vocalía.")
            return redirect(url_for("main.index"))
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
