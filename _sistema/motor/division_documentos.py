# -*- coding: utf-8 -*-
"""
division_documentos.py
-------------------------------------------------------------------------
Cuando varios documentos vienen COMBINADOS en un solo PDF (modo_entrada.tipo
== "juntos"), este modulo decide donde termina uno y empieza el siguiente,
antes de que el resto del programa los trate como documentos separados
(cada "grupo de paginas" resultante se procesa despues exactamente igual
que hoy se procesa un PDF suelto).

Dos formas de dividir (configuradas en el asistente):
  - "paginas_fijas": cada documento tiene siempre la misma cantidad de
    paginas (ej. 2 paginas = 1 factura). Division mecanica, sin OCR.
  - "patron": no hay cantidad fija; se reconoce el INICIO (y opcionalmente
    el FIN) de cada documento por una frase/patron que aparece impresa en
    la pagina. Requiere leer el texto de cada pagina (rapido: solo texto
    plano, sin posiciones -- la ubicacion exacta de cada dato se resuelve
    despues, ya con el documento separado).
-------------------------------------------------------------------------
"""

import re
from dataclasses import dataclass

import pymupdf as fitz
import pytesseract

from . import ocr_engine
from . import preprocesamiento
from .config import CFG


@dataclass
class GrupoDocumento:
    """Un documento logico dentro del PDF combinado (rango de paginas 0-based, inclusive)."""
    pagina_inicio: int
    pagina_fin: int
    confiable: bool
    motivo: str

    @property
    def cantidad_paginas(self):
        return self.pagina_fin - self.pagina_inicio + 1


def _contar_paginas(ruta_pdf):
    documento = fitz.open(ruta_pdf)
    try:
        return len(documento)
    finally:
        documento.close()


def _dividir_por_paginas_fijas(total_paginas, paginas_por_documento):
    grupos = []
    inicio = 0
    while inicio < total_paginas:
        fin = min(inicio + paginas_por_documento, total_paginas) - 1
        cantidad = fin - inicio + 1
        completo = cantidad == paginas_por_documento
        grupos.append(GrupoDocumento(
            inicio, fin,
            confiable=completo,
            # Un ultimo grupo mas corto que lo esperado sugiere que el PDF
            # combinado quedo cortado a la mitad de un documento -- se
            # manda a revision manual en vez de asumir que esta completo.
            motivo="ok" if completo else "ultimo_grupo_incompleto",
        ))
        inicio = fin + 1
    return grupos


def _texto_paginas(ruta_pdf, total_paginas):
    """Texto OCR rapido (sin posiciones) de cada pagina del PDF combinado, en orden."""
    imagenes = ocr_engine.pdf_a_imagenes(ruta_pdf, max_paginas=total_paginas)
    textos = []
    for imagen in imagenes:
        imagen_derecha = preprocesamiento.preparar_pagina_completa(imagen, CFG.idiomas_ocr)
        textos.append(pytesseract.image_to_string(imagen_derecha, lang=CFG.idiomas_ocr))
    return textos


def _dividir_por_patron(textos, patron_inicio, patron_fin):
    """
    Recorrido secuencial (una sola pasada): cada aparicion de
    "patron_inicio" cierra el grupo abierto (si habia) y abre uno nuevo;
    "patron_fin" (si esta configurado) cierra el grupo actual. Paginas sin
    ninguna marca siguen perteneciendo al grupo abierto.
    """
    regex_inicio = re.compile(patron_inicio, re.IGNORECASE)
    regex_fin = re.compile(patron_fin, re.IGNORECASE) if patron_fin else None

    es_inicio = [bool(regex_inicio.search(t)) for t in textos]
    es_fin = [bool(regex_fin.search(t)) for t in textos] if regex_fin else [False] * len(textos)

    grupos = []
    inicio_abierto = None
    total = len(textos)
    i = 0

    while i < total:
        if es_inicio[i]:
            if inicio_abierto is not None:
                grupos.append(GrupoDocumento(inicio_abierto, i - 1, True, "cerrado_por_siguiente_inicio"))
            inicio_abierto = i
            if regex_fin and es_fin[i]:
                # Inicio y fin en la misma pagina: documento de 1 pagina.
                grupos.append(GrupoDocumento(inicio_abierto, i, True, "cerrado_mismo_pagina"))
                inicio_abierto = None
            i += 1
            continue

        if inicio_abierto is None:
            # Pagina huerfana ANTES del primer patron_inicio: no se pierde
            # ni se agrupa a ciegas con huerfanas vecinas -- va sola a
            # revision manual.
            grupos.append(GrupoDocumento(i, i, False, "huerfana_antes_del_primer_inicio"))
            i += 1
            continue

        if regex_fin and es_fin[i]:
            grupos.append(GrupoDocumento(inicio_abierto, i, True, "cerrado_normal"))
            inicio_abierto = None
            i += 1
            continue

        i += 1  # pagina intermedia sin marca: sigue en el grupo abierto

    if inicio_abierto is not None:
        # Se acabo el PDF con un grupo todavia abierto. Solo se marca como
        # no confiable si se esperaba un "patron_fin" que nunca aparecio
        # (posible documento cortado); si no hay patron_fin configurado,
        # terminar en el ultimo PDF es el comportamiento normal.
        fin_esperado_pero_no_encontrado = bool(regex_fin)
        grupos.append(GrupoDocumento(
            inicio_abierto, total - 1,
            confiable=not fin_esperado_pero_no_encontrado,
            motivo="cerrado_por_fin_de_pdf",
        ))

    return grupos


def separar_documentos(ruta_pdf, modo_entrada):
    """
    Devuelve la lista de GrupoDocumento (paginas 0-based, inclusive) en
    las que se debe partir "ruta_pdf" segun modo_entrada. Si
    modo_entrada.tipo == "separados" no hace falta llamar a esta funcion
    (cada PDF ya es un documento); se cubre igual el caso trivial por si
    se invoca de todas formas, devolviendo el PDF completo como un unico
    grupo.
    """
    total_paginas = _contar_paginas(ruta_pdf)
    if total_paginas == 0:
        return []

    if modo_entrada.tipo == "separados":
        return [GrupoDocumento(0, total_paginas - 1, True, "documento_ya_separado")]

    if modo_entrada.modo_division == "paginas_fijas":
        paginas_por_documento = modo_entrada.paginas_por_documento or 1
        return _dividir_por_paginas_fijas(total_paginas, paginas_por_documento)

    if modo_entrada.modo_division == "patron":
        if not modo_entrada.patron_inicio:
            # Configuracion incompleta: no hay como dividir. Se trata el
            # PDF completo como un solo documento NO confiable, para que
            # vaya a revision manual en vez de perderse o adivinar.
            return [GrupoDocumento(0, total_paginas - 1, False, "patron_inicio_no_configurado")]
        textos = _texto_paginas(ruta_pdf, total_paginas)
        return _dividir_por_patron(textos, modo_entrada.patron_inicio, modo_entrada.patron_fin)

    raise ValueError(f"modo_division desconocido: {modo_entrada.modo_division!r}")
