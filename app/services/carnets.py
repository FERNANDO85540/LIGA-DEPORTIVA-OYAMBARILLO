"""Generación de carnets (imagen PNG y PDF) con Pillow."""
import io
import os

from flask import send_file
from PIL import Image, ImageDraw, ImageFont, ImageOps

from config import CARNET_ALTO_MM, CARNET_ANCHO_MM, CARNET_PDF_DPI, FOTOS_DIR, STATIC_DIR
from app.utils import _calcular_edad


def _font(size, bold=False):
    candidatos = ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    for nombre in candidatos:
        try:
            return ImageFont.truetype(nombre, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _texto_centrado(draw, cx, y, texto, font, fill):
    bbox = draw.textbbox((0, 0), texto, font=font)
    ancho_texto = bbox[2] - bbox[0]
    draw.text((cx - ancho_texto / 2, y), texto, font=font, fill=fill)


_LOGO_CACHE = {}


def _logo_thumb(tam):
    """Logo del carnet ya reducido de tamaño, cacheado en memoria para no
    reabrir y decodificar el PNG del disco en cada jugador (se generan
    hasta 35 carnets seguidos por equipo)."""
    if tam not in _LOGO_CACHE:
        logo_path = os.path.join(STATIC_DIR, "logo_ldbo.png")
        if os.path.exists(logo_path):
            img = Image.open(logo_path).convert("RGBA")
            img.thumbnail(tam)
            _LOGO_CACHE[tam] = img
        else:
            _LOGO_CACHE[tam] = None
    return _LOGO_CACHE[tam]


def _generar_carnet(jugador):
    # Proporción 93x64mm (tamaño real de la lámina de laminado que se usa para el carnet).
    ancho, alto = 900, 619

    # ---------- FRENTE ----------
    frente = Image.new("RGB", (ancho, alto), "#eef6f0")
    draw = ImageDraw.Draw(frente)

    for y in range(130, alto):
        t = (y - 130) / (alto - 130)
        color = (
            int(240 + (214 - 240) * t),
            int(248 + (232 - 248) * t),
            int(242 + (220 - 242) * t),
        )
        draw.line([(0, y), (ancho, y)], fill=color)

    draw.rectangle([0, 0, ancho, 130], fill="#ffffff")
    draw.rectangle([0, 127, ancho, 130], fill="#14532d")

    f_titulo = _font(32, bold=True)
    f_sub = _font(22, bold=True)
    _texto_centrado(draw, ancho / 2, 18, "LIGA DEPORTIVA OYAMBARILLO", f_titulo, "#14532d")
    _texto_centrado(draw, ancho / 2, 62, "CAMPEONATO OFICIAL 2026", f_sub, "#b45309")

    logo = _logo_thumb((120, 120))
    if logo:
        frente.paste(logo, (18, 5), logo)

    foto_x, foto_y, foto_w, foto_h = 610, 155, 250, 280
    if jugador["foto"]:
        foto_path = os.path.join(FOTOS_DIR, jugador["foto"])
        if os.path.exists(foto_path):
            foto = Image.open(foto_path)
            # Decodifica ya reducido (más rápido y con mucha menos memoria que
            # abrir la foto a su resolución completa solo para achicarla después).
            foto.draft("RGB", (foto_w * 2, foto_h * 2))
            foto = foto.convert("RGB")
            foto = ImageOps.fit(foto, (foto_w, foto_h))
            frente.paste(foto, (foto_x, foto_y))
    draw.rectangle([foto_x, foto_y, foto_x + foto_w, foto_y + foto_h], outline="#14532d", width=4)

    if jugador["numero_camiseta"]:
        f_num = _font(64, bold=True)
        _texto_centrado(draw, foto_x + foto_w / 2, foto_y + foto_h + 14, f"# {jugador['numero_camiseta']}", f_num, "#14532d")

    f_label = _font(24, bold=True)
    f_valor = _font(34, bold=True)

    y0 = 165
    draw.text((30, y0), "EQUIPO:", font=f_label, fill="#b45309")
    draw.text((30, y0 + 32), jugador["equipo"].upper(), font=f_valor, fill="#14532d")

    y1 = y0 + 105
    draw.text((30, y1), "JUGADOR:", font=f_label, fill="#b45309")
    draw.text((30, y1 + 32), jugador["apellidos"].upper(), font=f_valor, fill="#111111")
    draw.text((30, y1 + 72), jugador["nombres"].upper(), font=f_valor, fill="#111111")

    y2 = y1 + 130
    draw.text((30, y2), "C.I.:", font=f_label, fill="#b45309")
    draw.text((115, y2 - 5), jugador["cedula"], font=f_valor, fill="#111111")

    subcat = jugador["subcategoria"] or "Sub 45"
    f_cat = _font(26, bold=True)
    draw.text((30, y2 + 45), subcat.upper(), font=f_cat, fill="#14532d")

    # ---------- REVERSO ----------
    reverso = Image.new("RGB", (ancho, alto), "white")
    rdraw = ImageDraw.Draw(reverso)

    edad = _calcular_edad(jugador["fecha_nacimiento"])
    f_rlabel = _font(30, bold=True)
    f_rvalor = _font(30)

    rdraw.text((50, 70), "Campeonato:", font=f_rlabel, fill="#14532d")
    rdraw.text((300, 70), (jugador["categoria"] or "") + (f" - {subcat}" if subcat == "Juvenil" else ""), font=f_rvalor, fill="black")

    rdraw.text((50, 130), "Edad:", font=f_rlabel, fill="black")
    rdraw.text((300, 130), str(edad) if edad is not None else "-", font=f_rvalor, fill="black")

    rdraw.text((50, 190), "F. Nacimiento:", font=f_rlabel, fill="black")
    rdraw.text((50, 232), jugador["fecha_nacimiento"] or "-", font=f_rvalor, fill="#14532d")

    sello = _logo_thumb((220, 220))
    if sello:
        sello = sello.copy()
        sello_alpha = sello.split()[3].point(lambda p: p * 0.5)
        sello.putalpha(sello_alpha)
        reverso.paste(sello, (ancho - sello.width - 60, 280), sello)

    rdraw.line([(50, 490), (380, 490)], fill="black", width=2)
    f_firma = _font(24, bold=True)
    rdraw.text((50, 498), "PRESIDENTE", font=f_firma, fill="black")

    return frente, reverso


def _carnet_response(jugador):
    frente, reverso = _generar_carnet(jugador)

    lienzo = Image.new("RGB", (frente.width, frente.height * 2 + 20), "#dddddd")
    lienzo.paste(frente, (0, 0))
    lienzo.paste(reverso, (0, frente.height + 20))

    buf = io.BytesIO()
    lienzo.save(buf, format="PNG")
    buf.seek(0)
    nombre_archivo = f"carnet_{jugador['cedula']}.png"
    return send_file(buf, mimetype="image/png", as_attachment=False, download_name=nombre_archivo)


def _mm_a_px(mm, dpi=CARNET_PDF_DPI):
    return int(round(mm / 25.4 * dpi))


def _armar_paginas_carnets(jugadores, dpi=CARNET_PDF_DPI):
    """Arma páginas A4 con los carnets en cuadrícula. El reverso de cada jugador va a
    la izquierda y el frente a la derecha, uno al lado del otro y separados por una
    línea guía, para que no haya que buscar el reverso en otra página."""
    margen = _mm_a_px(8, dpi)
    espacio = _mm_a_px(4, dpi)
    espacio_interno = _mm_a_px(3, dpi)
    pagina_w, pagina_h = _mm_a_px(210, dpi), _mm_a_px(297, dpi)
    carnet_w, carnet_h = _mm_a_px(CARNET_ANCHO_MM, dpi), _mm_a_px(CARNET_ALTO_MM, dpi)
    unidad_w = carnet_w * 2 + espacio_interno
    unidad_h = carnet_h

    columnas = max(1, (pagina_w - 2 * margen + espacio) // (unidad_w + espacio))
    filas = max(1, (pagina_h - 2 * margen + espacio) // (unidad_h + espacio))
    por_pagina = columnas * filas

    paginas = []
    for inicio in range(0, len(jugadores), por_pagina):
        lote = jugadores[inicio:inicio + por_pagina]
        pagina = Image.new("RGB", (pagina_w, pagina_h), "white")
        draw = ImageDraw.Draw(pagina)
        for i, jugador in enumerate(lote):
            fila, col = divmod(i, columnas)
            x = margen + col * (unidad_w + espacio)
            y = margen + fila * (unidad_h + espacio)
            frente, reverso = _generar_carnet(jugador)
            pagina.paste(reverso.resize((carnet_w, carnet_h), Image.LANCZOS), (x, y))
            linea_x = x + carnet_w + espacio_interno // 2
            draw.line([(linea_x, y), (linea_x, y + carnet_h)], fill="#bbbbbb", width=2)
            pagina.paste(frente.resize((carnet_w, carnet_h), Image.LANCZOS), (x + carnet_w + espacio_interno, y))
        paginas.append(pagina)
    return paginas
