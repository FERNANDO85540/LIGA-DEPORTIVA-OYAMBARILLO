"""Inicio (redirección según rol) y archivos de fotos de jugadores."""
from flask import Blueprint, flash, redirect, send_from_directory, session, url_for

from config import FOTOS_DIR
from app.database import get_db

bp = Blueprint("main", __name__)


@bp.route("/fotos_jugadores/<path:filename>")
def fotos_jugadores(filename):
    return send_from_directory(FOTOS_DIR, filename)


@bp.route("/")
def index():
    if not session.get("logged_in"):
        return redirect(url_for("auth.login"))
    if session.get("rol") == "equipo":
        db = get_db()
        equipo = db.execute("SELECT id FROM equipos WHERE id = ?", (session.get("equipo_id"),)).fetchone()
        if not equipo:
            session.clear()
            flash("Tu sesión ya no es válida. Ingresa nuevamente.")
            return redirect(url_for("auth.login"))
        return redirect(url_for("equipos.detalle_equipo", equipo_id=equipo["id"]))
    if session.get("rol") == "imprenta":
        return redirect(url_for("carnets.carnets_modulo"))
    if session.get("rol") == "calificacion":
        return redirect(url_for("comision.comision_modulo"))
    if session.get("rol") == "sanciones":
        return redirect(url_for("sanciones.sanciones_modulo"))
    if session.get("rol") == "tecnica":
        return redirect(url_for("tecnica.tecnica_modulo"))
    if session.get("rol") == "vocalia":
        return redirect(url_for("vocalia.vocalia_modulo"))
    return redirect(url_for("inscripcion.inscripcion"))
