"""Inicio y cierre de sesión."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from config import (
    ADMIN_PASS, ADMIN_USER, CALIFICACION_PASS, CALIFICACION_USER, IMPRENTA_PASS, IMPRENTA_USER,
    SANCIONES_PASS, SANCIONES_USER, TECNICA_PASS, TECNICA_USER, VOCALIA_PASS, VOCALIA_USER,
)
from app.database import get_db

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("usuario", "").strip()
        pw = request.form.get("clave", "").strip()

        if user == ADMIN_USER and pw == ADMIN_PASS:
            session.clear()
            session["logged_in"] = True
            session["rol"] = "admin"
            return redirect(url_for("inscripcion.inscripcion"))

        if IMPRENTA_PASS and user == IMPRENTA_USER and pw == IMPRENTA_PASS:
            session.clear()
            session["logged_in"] = True
            session["rol"] = "imprenta"
            return redirect(url_for("carnets.carnets_modulo"))

        if CALIFICACION_PASS and user == CALIFICACION_USER and pw == CALIFICACION_PASS:
            session.clear()
            session["logged_in"] = True
            session["rol"] = "calificacion"
            return redirect(url_for("comision.comision_modulo"))

        if SANCIONES_PASS and user == SANCIONES_USER and pw == SANCIONES_PASS:
            session.clear()
            session["logged_in"] = True
            session["rol"] = "sanciones"
            return redirect(url_for("sanciones.sanciones_modulo"))

        if TECNICA_PASS and user == TECNICA_USER and pw == TECNICA_PASS:
            session.clear()
            session["logged_in"] = True
            session["rol"] = "tecnica"
            return redirect(url_for("tecnica.tecnica_modulo"))

        if VOCALIA_PASS and user == VOCALIA_USER and pw == VOCALIA_PASS:
            session.clear()
            session["logged_in"] = True
            session["rol"] = "vocalia"
            return redirect(url_for("vocalia.vocalia_modulo"))

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
            return redirect(url_for("equipos.detalle_equipo", equipo_id=equipo["id"]))

        flash("Usuario o clave incorrectos")
    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
