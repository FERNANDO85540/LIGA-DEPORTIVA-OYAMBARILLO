"""Exportación de listas de jugadores a Excel."""
import io

from flask import send_file
from openpyxl import Workbook


def _exportar_jugadores_excel(jugadores, nombre_archivo, incluir_equipo=False):
    wb = Workbook()
    ws = wb.active
    ws.title = "Jugadores"
    encabezados = ["Cédula", "Nombres", "Apellidos", "Fecha nacimiento", "Campeonato"]
    if incluir_equipo:
        encabezados.insert(0, "Equipo")
    encabezados += ["Número camiseta", "Registrado"]
    ws.append(encabezados)

    for j in jugadores:
        categoria = j["categoria"] + (" - Juvenil" if j["subcategoria"] == "Juvenil" else "")
        fila = [j["cedula"], j["nombres"], j["apellidos"], j["fecha_nacimiento"] or "", categoria]
        if incluir_equipo:
            fila.insert(0, j["equipo"])
        fila += [j["numero_camiseta"] or "", j["fecha_registro"]]
        ws.append(fila)

    for i, _ in enumerate(encabezados, start=1):
        ws.column_dimensions[chr(64 + i)].width = 18

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=nombre_archivo,
    )
