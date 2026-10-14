"""Módulo de carnets (imprenta): estado de impresión y PDF por lote."""
import io

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from config import CARNET_PDF_DPI
from app.database import get_db
from app.decorators import imprenta_required
from app.services.carnets import _armar_paginas_carnets
from app.utils import _to_float, ahora_ecuador

bp = Blueprint("carnets", __name__)


@bp.route("/carnets")
@imprenta_required
def carnets_modulo():
    db = get_db()
    
    # 1. Obtenemos los equipos (convertidos a diccionarios normales por si se ocupan)
    equipos_raw = db.execute("SELECT * FROM equipos ORDER BY categoria, division, nombre").fetchall()
    equipos = [dict(e) for e in equipos_raw]
    
    # 2. Obtenemos TODOS los jugadores. 
    # El nuevo frontend con Tabulator se encargará de filtrarlos y buscarlos sin recargar la página.
    jugadores_raw = db.execute("SELECT * FROM jugadores ORDER BY equipo, apellidos, nombres").fetchall()
    
    # 3. Formateamos los jugadores a una lista de diccionarios que el HTML pueda convertir a JSON
    jugadores = []
    for row in jugadores_raw:
        j = dict(row) # Convertimos el objeto Row de sqlite a diccionario normal
        
        # Formateo de categoría + subcategoría de forma segura
        categoria = j.get("categoria", "")
        subcategoria = j.get("subcategoria", "")
        if subcategoria == "Juvenil":
            categoria += " - Juvenil"
            
        # Limpieza de datos (booleanos y flotantes)
        carnet_impreso = bool(j.get("carnet_impreso"))
        
        carnet_valor = j.get("carnet_valor")
        try:
            carnet_valor = float(carnet_valor) if carnet_valor else None
        except (ValueError, TypeError):
            carnet_valor = None

        jugadores.append({
            "id": j.get("id"),
            "equipo": j.get("equipo"), # En tu base, esto guarda el nombre del equipo
            "categoria": categoria,
            "cedula": j.get("cedula"),
            "nombres": j.get("nombres"),
            "apellidos": j.get("apellidos"),
            "carnet_impreso": carnet_impreso,
            "carnet_valor": carnet_valor,
        })

    # 4. Cálculos estadísticos para las tarjetas del frontend
    total = len(jugadores)
    impresos = sum(1 for j in jugadores if j["carnet_impreso"])
    # Solo sumamos lo recaudado si el carnet está impreso (según la lógica de tu código original)
    recaudado = sum(j["carnet_valor"] or 0 for j in jugadores if j["carnet_impreso"])

    return render_template(
        "carnets/carnets_modulo.html",
        equipos=equipos,
        jugadores=jugadores,
        total=total,
        impresos=impresos,
        recaudado=recaudado
    )


@bp.route("/carnets/guardar_lote", methods=["POST"])
@imprenta_required
def carnets_estado_bulk():
    db = get_db()
    
    # Obtenemos la lista de IDs de todos los jugadores que estaban seleccionados
    jugadores_ids = request.form.getlist('jugador_id')
    
    for j_id in jugadores_ids:
        # Extraemos el valor del estado (1 o 0) y del costo para cada ID
        impreso_str = request.form.get(f'carnet_impreso_{j_id}')
        valor_str = request.form.get(f'carnet_valor_{j_id}')
        
        # Formateo de los datos
        impreso_bool = 1 if impreso_str == '1' else 0
        
        valor_float = None
        if valor_str and valor_str.strip() != '':
            try:
                valor_float = float(valor_str)
            except ValueError:
                valor_float = None
                
        # Actualizamos en la base de datos
        db.execute(
            "UPDATE jugadores SET carnet_impreso = ?, carnet_valor = ? WHERE id = ?",
            (impreso_bool, valor_float, j_id)
        )
        
    db.commit() # Guardamos todos los cambios juntos
    
    # Redirigimos de vuelta a la página principal de carnets
    return redirect(url_for('carnets.carnets_modulo'))


@bp.route("/carnets/<int:jugador_id>/estado", methods=["POST"])
@imprenta_required
def carnets_estado(jugador_id):
    db = get_db()
    jugador = db.execute("SELECT * FROM jugadores WHERE id = ?", (jugador_id,)).fetchone()
    if not jugador:
        flash("Jugador no encontrado.")
        return redirect(url_for("carnets.carnets_modulo"))

    impreso = 1 if request.form.get("carnet_impreso") == "on" else 0
    valor = _to_float(request.form.get("carnet_valor", "0"))
    fecha = jugador["carnet_fecha"]
    if impreso and not jugador["carnet_impreso"]:
        fecha = ahora_ecuador().strftime("%Y-%m-%d %H:%M")
    elif not impreso:
        fecha = None

    db.execute(
        "UPDATE jugadores SET carnet_impreso = ?, carnet_valor = ?, carnet_fecha = ? WHERE id = ?",
        (impreso, valor, fecha, jugador_id),
    )
    db.commit()
    flash("Carnet actualizado.", "ok")

    equipo = db.execute("SELECT id FROM equipos WHERE nombre = ?", (jugador["equipo"],)).fetchone()
    return redirect(url_for("carnets.carnets_modulo", equipo_id=equipo["id"] if equipo else ""))


@bp.route("/carnets/pdf")
@imprenta_required
def carnets_pdf():
    db = get_db()
    
    # 1. Obtenemos solo los IDs enviados desde el frontend (sin importar el equipo)
    jugador_ids = [int(x) for x in request.args.getlist("jugador_id") if x.isdigit()]

    if not jugador_ids:
        flash("Selecciona al menos un jugador en la tabla para generar los carnets.")
        return redirect(url_for("carnets.carnets_modulo"))

    # 2. Buscamos esos jugadores exactos en la base de datos
    placeholders = ",".join("?" * len(jugador_ids))
    jugadores = db.execute(
        f"SELECT * FROM jugadores WHERE id IN ({placeholders}) ORDER BY equipo, apellidos, nombres",
        (*jugador_ids,) # Pasamos la lista de IDs como parámetros para evitar inyecciones SQL
    ).fetchall()

    if not jugadores:
        flash("Hubo un error al buscar los jugadores seleccionados.")
        return redirect(url_for("carnets.carnets_modulo"))

    # 3. Generamos el PDF
    paginas = _armar_paginas_carnets(jugadores)
    buf = io.BytesIO()
    paginas[0].save(
        buf, format="PDF", save_all=True, append_images=paginas[1:], resolution=CARNET_PDF_DPI
    )
    buf.seek(0)
    
    # Nombre de archivo dinámico según la cantidad
    nombre_archivo = f"carnets_lote_{len(jugadores)}_jugadores.pdf"
    
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=nombre_archivo)
