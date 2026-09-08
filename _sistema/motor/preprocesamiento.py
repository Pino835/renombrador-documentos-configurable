# -*- coding: utf-8 -*-
"""
preprocesamiento.py
-------------------------------------------------------------------------
Mejoras a la IMAGEN antes de pasarsela al OCR. En la version 1 la imagen
del PDF se le pasaba a Tesseract tal cual (sin ningun ajuste), lo cual
funciona razonablemente bien pero deja precision sobre la mesa en
facturas escaneadas con poca luz, algo torcidas, o con manchas.

Todo aqui se hace SOLO con Pillow (la libreria que ya se instalaba en la
version 1) para no agregar dependencias nuevas (nada de numpy/OpenCV, que
complicarian la instalacion sin admin en equipos de oficina).

Dos mejoras concretas sobre la version 1:

  1. CORRECCION DE ORIENTACION: si el PDF se escaneo de lado o al reves,
     Tesseract lee muchisimo peor (o no lee nada). Se usa la deteccion de
     orientacion propia de Tesseract (OSD) para girar la imagen antes de
     leerla.

  2. BINARIZACION (blanco/negro) con umbral de Otsu: separa el texto del
     fondo de forma automatica segun el histograma de brillo de CADA
     imagen (no un numero fijo a ciegas), lo cual ayuda mucho en recortes
     pequenos con sombras o fondo amarillento (papel fotocopiado).
-------------------------------------------------------------------------
"""

import re
from PIL import Image, ImageOps, ImageFilter

import pytesseract


def a_escala_grises(imagen: Image.Image) -> Image.Image:
    return imagen.convert("L")


def autocontraste(imagen_gris: Image.Image) -> Image.Image:
    """Estira el histograma de brillo para que el texto mas claro/oscuro use todo el rango."""
    return ImageOps.autocontrast(imagen_gris, cutoff=1)


def _umbral_otsu(imagen_gris: Image.Image) -> int:
    """
    Calcula el umbral de Otsu (el punto de corte blanco/negro que mejor
    separa dos grupos de brillo -texto vs. fondo- segun el histograma de
    la imagen) usando solo el histograma de 256 valores que entrega
    Pillow. Es el mismo algoritmo que usan OpenCV/numpy, escrito a mano
    para no depender de esas librerias.
    """
    histograma = imagen_gris.histogram()
    total = sum(histograma)
    if total == 0:
        return 128

    suma_total = sum(i * histograma[i] for i in range(256))

    mejor_umbral = 128
    mejor_varianza = -1.0
    suma_acumulada = 0.0
    peso_fondo = 0

    for umbral in range(256):
        peso_fondo += histograma[umbral]
        if peso_fondo == 0:
            continue
        peso_texto = total - peso_fondo
        if peso_texto == 0:
            break

        suma_acumulada += umbral * histograma[umbral]
        media_fondo = suma_acumulada / peso_fondo
        media_texto = (suma_total - suma_acumulada) / peso_texto

        varianza_entre_grupos = peso_fondo * peso_texto * (media_fondo - media_texto) ** 2
        if varianza_entre_grupos > mejor_varianza:
            mejor_varianza = varianza_entre_grupos
            mejor_umbral = umbral

    return mejor_umbral


def binarizar(imagen_gris: Image.Image) -> Image.Image:
    """Convierte a blanco/negro puro usando el umbral de Otsu calculado para esta imagen."""
    umbral = _umbral_otsu(imagen_gris)
    return imagen_gris.point(lambda p: 255 if p > umbral else 0)


def enfocar(imagen: Image.Image) -> Image.Image:
    return imagen.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))


_PATRON_ANGULO_OSD = re.compile(r"Rotate:\s*(\d+)")


def corregir_orientacion(imagen: Image.Image, idiomas: str) -> Image.Image:
    """
    Detecta si la pagina esta girada (90/180/270 grados) usando la
    deteccion de orientacion de Tesseract (OSD) y la endereza.

    OSD necesita una cantidad minima de texto reconocible para funcionar;
    en paginas muy ruidosas o con poco texto puede fallar. En ese caso
    (o si el idioma OSD no esta instalado) se deja la imagen tal cual --
    esto NUNCA debe detener el procesamiento del archivo.
    """
    try:
        salida = pytesseract.image_to_osd(imagen)
    except Exception:
        return imagen

    coincidencia = _PATRON_ANGULO_OSD.search(salida)
    if not coincidencia:
        return imagen

    angulo = int(coincidencia.group(1))
    if angulo == 0:
        return imagen

    # PIL rota en sentido antihorario; Tesseract reporta cuanto hay que
    # rotar en sentido horario para enderezar, por eso el signo negativo.
    return imagen.rotate(-angulo, expand=True, fillcolor="white")


def preparar_pagina_completa(imagen: Image.Image, idiomas: str) -> Image.Image:
    """
    Preprocesamiento para el primer barrido (la pagina completa). Se
    mantiene liviano -solo orientacion- porque Tesseract ya trae su
    propia binarizacion interna para paginas completas, y una
    binarizacion externa agresiva a veces borra texto fino en facturas
    con fondos de color.
    """
    return corregir_orientacion(imagen, idiomas)


def preparar_recorte_para_refinar(recorte: Image.Image) -> Image.Image:
    """
    Preprocesamiento para la segunda pasada (el recorte pequeno ya
    agrandado, ver ocr_engine.refinar_lectura). Aqui SI conviene ir a
    fondo: es una zona pequena y especifica, asi que binarizar ayuda a
    separar el texto de sombras/manchas sin arriesgar perder informacion
    de otras partes del documento.
    """
    gris = a_escala_grises(recorte)
    gris = autocontraste(gris)
    nitido = enfocar(gris)
    return binarizar(nitido)
