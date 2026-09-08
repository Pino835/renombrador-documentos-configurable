# -*- coding: utf-8 -*-
"""
ocr_engine.py
-------------------------------------------------------------------------
Todo lo que tiene que ver con "hablar" con Tesseract y con convertir PDFs
a imagenes: no sabe nada de "codigo de cliente" ni "factura" (eso vive en
extractores.py) -- solo sabe leer texto con su posicion en la pagina.

Mejora sobre la version 1: "pdf_a_imagenes" ahora puede devolver VARIAS
paginas del PDF (antes solo se leia la primera). Algunas facturas
escaneadas traen una hoja de "caratula" o el sello en la segunda pagina;
si la primera pagina no trae los datos, en la version 1 el archivo se
mandaba directo a revision manual sin siquiera mirar el resto del PDF.
-------------------------------------------------------------------------
"""

import os
import shutil

import pymupdf as fitz  # PyMuPDF
import pytesseract
from PIL import Image

from .config import CFG

_CANDIDATOS_TESSERACT = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Tesseract-OCR", "tesseract.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
]


def localizar_tesseract():
    """Devuelve la ruta de tesseract.exe si se encuentra, o None."""
    encontrado = shutil.which("tesseract")
    if encontrado:
        return encontrado
    for ruta_candidata in _CANDIDATOS_TESSERACT:
        if ruta_candidata and os.path.exists(ruta_candidata):
            return ruta_candidata
    return None


def preparar_tesseract():
    """
    Configura pytesseract para usar el tesseract.exe encontrado, y avisa
    (sin detener el programa) si falta el idioma Español.
    Devuelve la ruta encontrada, o None si no se encontro ninguna.
    """
    ruta = localizar_tesseract()
    if ruta:
        pytesseract.pytesseract.tesseract_cmd = ruta
        ruta_spa = os.path.join(os.path.dirname(ruta), "tessdata", "spa.traineddata")
        if not os.path.exists(ruta_spa):
            print("ADVERTENCIA: no se encontro el idioma Español para el OCR")
            print(f"  ({ruta_spa})")
            print("  La lectura de las facturas va a ser menos precisa de lo normal.")
            print("  Vuelva a ejecutar 'ejecutar_1_instalar_dependencias.bat' para instalarlo.")
    return ruta


def pdf_a_imagenes(ruta_pdf, max_paginas=3):
    """
    Convierte hasta 'max_paginas' paginas de un PDF a imagenes PIL de alta
    resolucion (en orden), empezando desde la primera pagina. La mayoria
    de las facturas son de una sola pagina, asi que en el caso normal esto
    devuelve una lista de un solo elemento.
    """
    return imagenes_de_rango(ruta_pdf, 0, max_paginas - 1)


def imagenes_de_rango(ruta_pdf, pagina_inicio, pagina_fin):
    """
    Convierte el rango de paginas [pagina_inicio, pagina_fin] (0-based,
    inclusive) de un PDF a imagenes PIL de alta resolucion. Se usa para
    los documentos logicos que resultan de separar un PDF combinado (ver
    division_documentos.py) -- pdf_a_imagenes() siempre parte desde la
    pagina 0 porque asume que el PDF ya es un solo documento.
    """
    zoom = CFG.dpi_render / 72  # 72 es el DPI base de PDF
    matriz = fitz.Matrix(zoom, zoom)
    imagenes = []
    documento = fitz.open(ruta_pdf)
    try:
        pagina_fin_real = min(pagina_fin, len(documento) - 1)
        for indice in range(pagina_inicio, pagina_fin_real + 1):
            pagina = documento[indice]
            pix = pagina.get_pixmap(matrix=matriz)
            modo = "RGB" if pix.alpha == 0 else "RGBA"
            imagen = Image.frombytes(modo, (pix.width, pix.height), pix.samples)
            imagenes.append(imagen.convert("RGB"))
    finally:
        documento.close()
    return imagenes


def _superposicion_vertical(a_top, a_bottom, b_top, b_bottom):
    inicio = max(a_top, b_top)
    fin = min(a_bottom, b_bottom)
    return max(0, fin - inicio)


def obtener_lineas_ocr(imagen: Image.Image, config: str = ""):
    """
    Corre el OCR palabra por palabra (con su posicion) y reconstruye las
    filas reales de la pagina segun la posicion vertical de cada palabra,
    en vez de usar el agrupamiento de "linea" que entrega Tesseract.

    Necesario porque en facturas con columnas (datos del cliente a la
    izquierda, datos de la factura a la derecha, en la misma fila visual)
    Tesseract a veces separa esa fila en "lineas" internas distintas
    aunque esten a la misma altura.

    Devuelve una lista de filas ordenadas de arriba hacia abajo, cada una
    con su texto, posicion (bbox), palabras individuales y confianza
    promedio del OCR.
    """
    datos = pytesseract.image_to_data(
        imagen, lang=CFG.idiomas_ocr, config=config, output_type=pytesseract.Output.DICT
    )

    palabras = []
    total = len(datos["text"])
    for i in range(total):
        texto = datos["text"][i].strip()
        if not texto:
            continue
        try:
            conf = float(datos["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        palabras.append({
            "texto": texto,
            "left": datos["left"][i],
            "top": datos["top"][i],
            "width": datos["width"][i],
            "height": datos["height"][i],
            "conf": conf,
        })

    palabras.sort(key=lambda p: p["top"])

    filas = []
    for p in palabras:
        p_top, p_bottom = p["top"], p["top"] + p["height"]
        fila_encontrada = None
        for fila in filas:
            alto_menor = min(p["height"], fila["bottom"] - fila["top"])
            if alto_menor <= 0:
                continue
            solapado = _superposicion_vertical(p_top, p_bottom, fila["top"], fila["bottom"])
            if solapado / alto_menor >= 0.4:
                fila_encontrada = fila
                break
        if fila_encontrada is None:
            filas.append({"top": p_top, "bottom": p_bottom, "palabras": [p]})
        else:
            fila_encontrada["palabras"].append(p)
            fila_encontrada["top"] = min(fila_encontrada["top"], p_top)
            fila_encontrada["bottom"] = max(fila_encontrada["bottom"], p_bottom)

    resultado = []
    for fila in filas:
        ps = sorted(fila["palabras"], key=lambda p: p["left"])

        offset = 0
        for p in ps:
            p["char_inicio"] = offset
            p["char_fin"] = offset + len(p["texto"])
            offset = p["char_fin"] + 1  # +1 por el espacio separador del join

        texto_fila = " ".join(p["texto"] for p in ps)
        top = min(p["top"] for p in ps)
        bottom = max(p["top"] + p["height"] for p in ps)
        left = min(p["left"] for p in ps)
        right = max(p["left"] + p["width"] for p in ps)
        confs = [p["conf"] for p in ps if p["conf"] >= 0]
        confianza = (sum(confs) / len(confs)) if confs else None
        resultado.append({
            "texto": texto_fila,
            "palabras": ps,
            "top": top, "bottom": bottom, "left": left, "right": right,
            "confianza": confianza,
        })

    resultado.sort(key=lambda l: l["top"])
    return resultado


def bbox_de(linea):
    return (linea["left"], linea["top"], linea["right"], linea["bottom"])


def bbox_de_rango(linea, inicio_char, fin_char):
    """
    Bbox de solo las palabras de la linea que caen dentro del rango de
    caracteres [inicio_char, fin_char) de linea["texto"]. Evita que el
    recorte de una coincidencia incluya el resto de la fila (ej. una
    columna vecina).
    """
    palabras_en_rango = [
        p for p in linea["palabras"]
        if p["char_fin"] > inicio_char and p["char_inicio"] < fin_char
    ]
    if not palabras_en_rango:
        return bbox_de(linea)
    izquierda = min(p["left"] for p in palabras_en_rango)
    arriba = min(p["top"] for p in palabras_en_rango)
    derecha = max(p["left"] + p["width"] for p in palabras_en_rango)
    abajo = max(p["top"] + p["height"] for p in palabras_en_rango)
    return (izquierda, arriba, derecha, abajo)


def recorte_desde_bbox(imagen: Image.Image, bbox, margen=30):
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    ancho, alto = imagen.size
    izquierda = max(0, left - margen)
    arriba = max(0, top - margen)
    derecha = min(ancho, right + margen)
    abajo = min(alto, bottom + margen)
    return imagen.crop((izquierda, arriba, derecha, abajo))


def agrandar_recorte(recorte: Image.Image, factor=4, lado_maximo=3500):
    """
    Agranda un recorte pequeno para que Tesseract tenga mas pixeles con
    que trabajar. Se limita el tamano final para no volverlo lento si el
    recorte de partida ya era grande.
    """
    ancho, alto = recorte.size
    nuevo_ancho, nuevo_alto = ancho * factor, alto * factor
    if max(nuevo_ancho, nuevo_alto) > lado_maximo:
        ajuste = lado_maximo / max(ancho, alto)
        nuevo_ancho, nuevo_alto = int(ancho * ajuste), int(alto * ajuste)
    nuevo_ancho, nuevo_alto = max(1, nuevo_ancho), max(1, nuevo_alto)
    return recorte.resize((nuevo_ancho, nuevo_alto), Image.LANCZOS)
