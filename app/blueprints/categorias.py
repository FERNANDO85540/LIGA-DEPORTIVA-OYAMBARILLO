"""Gestión de campeonatos (categorías) y sus divisiones."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.database import IntegrityError, get_db
from app.decorators import admin_required
from app.services.liga import _categorias_liga

bp = Blueprint("categorias", __name__)


@bp.route("/categorias")
@admin_required
def categorias_modulo():
    db = get_db()
    filas = db.execute("SELECT * FROM categorias ORDER BY id").fetchall()
    categorias = []
    for f in filas:
        equipos_count = db.execute(
            "SELECT COUNT(*) c FROM equipos WHERE categoria = ?", (f["nombre"],)
        ).fetchone()["c"]
        divisiones_rows = db.execute(
            "SELECT * FROM divisiones WHERE categoria = ? ORDER BY id", (f["nombre"],)
        ).fetchall()
        divisiones = []
        for d in divisiones_rows:
            d_equipos_count = db.execute(
                "SELECT COUNT(*) c FROM equipos WHERE categoria = ? AND division = ?",
                (f["nombre"], d["nombre"]),
            ).fetchone()["c"]
            divisiones.append({"fila": d, "equipos_count": d_equipos_count})
        categorias.append({"fila": f, "equipos_count": equipos_count, "divisiones": divisiones})
    return render_template("categorias/categorias_modulo.html", categorias=categorias)


@bp.route("/categorias/agregar", methods=["POST"])
@admin_required
def agregar_categoria():
    db = get_db()
    nombre = request.form.get("nombre", "").strip()
    edad_minima_raw = request.form.get("edad_minima", "").strip()
    edad_minima = int(edad_minima_raw) if edad_minima_raw.isdigit() else None
    limite_juveniles_raw = request.form.get("limite_juveniles", "").strip()
    limite_juveniles = int(limite_juveniles_raw) if limite_juveniles_raw.isdigit() else None

    if not nombre:
        flash("Ingresa un nombre para el campeonato.")
        return redirect(url_for("categorias.categorias_modulo"))

    try:
        db.execute(
            "INSERT INTO categorias (nombre, edad_minima, limite_juveniles) VALUES (?, ?, ?)",
            (nombre, edad_minima, limite_juveniles),
        )
        db.commit()
        flash(f"Campeonato '{nombre}' agregado.", "ok")
    except IntegrityError:
        db.rollback()
        flash(f"Ya existe un campeonato llamado '{nombre}'.")
    return redirect(url_for("categorias.categorias_modulo"))


@bp.route("/categorias/<int:categoria_id>/editar", methods=["POST"])
@admin_required
def editar_categoria(categoria_id):
    db = get_db()
    edad_minima_raw = request.form.get("edad_minima", "").strip()
    edad_minima = int(edad_minima_raw) if edad_minima_raw.isdigit() else None
    limite_juveniles_raw = request.form.get("limite_juveniles", "").strip()
    limite_juveniles = int(limite_juveniles_raw) if limite_juveniles_raw.isdigit() else None
    db.execute(
        "UPDATE categorias SET edad_minima = ?, limite_juveniles = ? WHERE id = ?",
        (edad_minima, limite_juveniles, categoria_id),
    )
    db.commit()
    flash("Campeonato actualizado.", "ok")
    return redirect(url_for("categorias.categorias_modulo"))


@bp.route("/categorias/<int:categoria_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_categoria(categoria_id):
    db = get_db()
    categoria = db.execute("SELECT * FROM categorias WHERE id = ?", (categoria_id,)).fetchone()
    if not categoria:
        flash("Campeonato no encontrado.")
        return redirect(url_for("categorias.categorias_modulo"))

    equipos_count = db.execute(
        "SELECT COUNT(*) c FROM equipos WHERE categoria = ?", (categoria["nombre"],)
    ).fetchone()["c"]
    if equipos_count > 0:
        flash(f"No se puede eliminar '{categoria['nombre']}': todavía tiene {equipos_count} equipo(s). Elimina o cambia esos equipos primero.")
        return redirect(url_for("categorias.categorias_modulo"))

    if len(_categorias_liga(db)) <= 1:
        flash("No se puede eliminar el último campeonato de la liga.")
        return redirect(url_for("categorias.categorias_modulo"))

    db.execute("DELETE FROM divisiones WHERE categoria = ?", (categoria["nombre"],))
    db.execute("DELETE FROM categorias WHERE id = ?", (categoria_id,))
    db.commit()
    flash(f"Campeonato '{categoria['nombre']}' eliminado.", "ok")
    return redirect(url_for("categorias.categorias_modulo"))


@bp.route("/categorias/<int:categoria_id>/divisiones/agregar", methods=["POST"])
@admin_required
def agregar_division(categoria_id):
    db = get_db()
    categoria = db.execute("SELECT * FROM categorias WHERE id = ?", (categoria_id,)).fetchone()
    if not categoria:
        flash("Campeonato no encontrado.")
        return redirect(url_for("categorias.categorias_modulo"))

    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("Ingresa un nombre para la categoría.")
        return redirect(url_for("categorias.categorias_modulo"))

    ya_existe = db.execute(
        "SELECT 1 FROM divisiones WHERE categoria = ? AND nombre = ?", (categoria["nombre"], nombre)
    ).fetchone()
    if ya_existe:
        flash(f"'{categoria['nombre']}' ya tiene una categoría llamada '{nombre}'.")
        return redirect(url_for("categorias.categorias_modulo"))

    db.execute("INSERT INTO divisiones (categoria, nombre) VALUES (?, ?)", (categoria["nombre"], nombre))
    db.commit()
    flash(f"Categoría '{nombre}' agregada a {categoria['nombre']}.", "ok")
    return redirect(url_for("categorias.categorias_modulo"))


@bp.route("/divisiones/<int:division_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_division(division_id):
    db = get_db()
    division = db.execute("SELECT * FROM divisiones WHERE id = ?", (division_id,)).fetchone()
    if not division:
        flash("Categoría no encontrada.")
        return redirect(url_for("categorias.categorias_modulo"))

    equipos_count = db.execute(
        "SELECT COUNT(*) c FROM equipos WHERE categoria = ? AND division = ?",
        (division["categoria"], division["nombre"]),
    ).fetchone()["c"]
    if equipos_count > 0:
        flash(f"No se puede eliminar '{division['nombre']}': todavía tiene {equipos_count} equipo(s).")
        return redirect(url_for("categorias.categorias_modulo"))

    db.execute("DELETE FROM divisiones WHERE id = ?", (division_id,))
    db.commit()
    flash(f"Categoría '{division['nombre']}' eliminada.", "ok")
    return redirect(url_for("categorias.categorias_modulo"))
