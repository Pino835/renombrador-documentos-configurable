# -*- coding: utf-8 -*-
"""
extractores.py
-------------------------------------------------------------------------
Aqui vive el "que buscar y donde": los patrones de factura y cliente, y
la logica para encontrarlos dentro de las lineas que ya reconstruyo
ocr_engine.obtener_lineas_ocr.

Los patrones YA NO estan escritos a mano en este archivo (como en la
version 1): se leen de config.json a traves de CFG, y se prueban en
orden -- asi, si mas adelante aparece una factura con un formato
distinto, se agrega un patron nuevo al config sin tocar el codigo.
-------------------------------------------------------------------------
"""

import re

from . import ocr_engine
from . import preprocesamiento
from . import aprendizaje
from .config import CFG, limpiar_texto_extraido


def _valor_tras_posicion(linea, pos_char, min_len=3, max_len=15):
    """
    Busca, entre las palabras de la fila que empiezan en o despues de
    'pos_char', la primera que -al quitarle simbolos raros- quede como un
    codigo razonable (letras y/o numeros de min_len a max_len
    caracteres). Sirve para leer el valor que sigue a una etiqueta
    ("Cliente:", "Factura:") sin exigir que este pegado caracter por
    caracter, ya que el OCR a veces mete un simbolo basura de por medio.
    Devuelve (valor_limpio, palabra) o (None, None) si no se encontro nada.
    """
    for p in linea["palabras"]:
        if p["char_inicio"] < pos_char:
            continue
        candidato = re.sub(r'[^A-Za-z0-9]', '', p["texto"])
        if min_len <= len(candidato) <= max_len:
            return candidato, p
    return None, None


def buscar_factura(lineas, alto_pagina=None):
    # alto_pagina=None se usa para la segunda pasada (sobre un recorte ya
    # acotado): ahi no tiene sentido restringir a la "mitad superior".
    limite = alto_pagina * CFG.limite_superior_ratio if alto_pagina is not None else None

    # 1) Patrones directos (ej. "CMER-xxxx"): muy especificos, se buscan
    #    en toda la pagina, en el orden en que estan en config.json.
    for patron in CFG.patrones_factura:
        for linea in lineas:
            m = patron.search(linea["texto"])
            if m:
                valor = limpiar_texto_extraido(m.group(0))
                bbox = ocr_engine.bbox_de_rango(linea, m.start(), m.end())
                return _normalizar_factura(valor), linea["confianza"], bbox

    # 2) Respaldo: etiqueta "Factura" en la mitad superior del documento.
    for patron_etiqueta in CFG.etiquetas_factura_respaldo:
        for linea in lineas:
            if limite is not None and linea["top"] > limite:
                continue
            m = patron_etiqueta.search(linea["texto"])
            if m:
                valor, palabra_valor = _valor_tras_posicion(linea, m.end(), min_len=4)
                if valor:
                    bbox = ocr_engine.bbox_de_rango(linea, m.start(), palabra_valor["char_fin"])
                    return valor, linea["confianza"], bbox

    return None, None, None


def _normalizar_factura(valor: str) -> str:
    """
    Deja el numero de factura con el prefijo siempre igual (ej.
    "CMER-004206455"), sin importar si el OCR leyo "CMER 004206455" o
    "CMER-004206455" o "CMER004206455".
    """
    if not CFG.prefijo_factura_normalizado:
        return valor.upper()
    prefijo_sin_guion = CFG.prefijo_factura_normalizado.rstrip("-")
    resto = re.sub(rf'^{re.escape(prefijo_sin_guion)}[\s\-]*', '', valor, flags=re.IGNORECASE)
    return f"{CFG.prefijo_factura_normalizado}{resto}".upper()


def buscar_cliente(lineas, alto_pagina=None):
    limite = alto_pagina * CFG.limite_superior_ratio if alto_pagina is not None else None
    for patron_etiqueta in CFG.etiquetas_cliente:
        for linea in lineas:
            if limite is not None and linea["top"] > limite:
                continue
            m = patron_etiqueta.search(linea["texto"])
            if m:
                valor, palabra_valor = _valor_tras_posicion(linea, m.end())
                if valor:
                    bbox = ocr_engine.bbox_de_rango(linea, m.start(), palabra_valor["char_fin"])
                    return valor, linea["confianza"], bbox
    return None, None, None


def refinar_lectura(imagen_pagina, bbox, tipo: str):
    """
    Segunda pasada de OCR, mas precisa que el primer barrido de la pagina
    completa: recorta SOLO la zona pequena donde ese primer barrido
    encontro el dato (con margen), la agranda y la binariza (ver
    preprocesamiento.preparar_recorte_para_refinar), y le vuelve a hacer
    OCR con una configuracion pensada para una sola linea corta de texto
    ("--psm 7").

    Ataca casos donde el barrido de pagina completa inventa un caracter
    de mas en codigos cortos (ej. lee "MCMO001" en vez de "MCM001") con
    confianza alta -- una segunda lectura enfocada suele evitarlo.

    Devuelve (valor, confianza) si logra leer algo valido en el recorte,
    o (None, None) si no (se conserva el resultado del primer barrido).
    """
    recorte = ocr_engine.recorte_desde_bbox(imagen_pagina, bbox, margen=15)
    if recorte is None:
        return None, None

    recorte_grande = ocr_engine.agrandar_recorte(recorte)
    recorte_procesado = preprocesamiento.preparar_recorte_para_refinar(recorte_grande)
    lineas_recorte = ocr_engine.obtener_lineas_ocr(recorte_procesado, config="--psm 7")
    if not lineas_recorte:
        return None, None

    if tipo == "cliente":
        valor, confianza, _bbox = buscar_cliente(lineas_recorte, alto_pagina=None)
    else:
        valor, confianza, _bbox = buscar_factura(lineas_recorte, alto_pagina=None)

    return valor, confianza


def extraer_datos(imagen):
    """Devuelve un diccionario con cliente, factura, su confianza OCR y su bbox (para recortes)."""
    ancho, alto = imagen.size
    lineas = ocr_engine.obtener_lineas_ocr(imagen)
    factura, conf_factura, bbox_factura = buscar_factura(lineas, alto)
    cliente, conf_cliente, bbox_cliente = buscar_cliente(lineas, alto)

    if bbox_cliente is not None:
        valor_refinado, confianza_refinada = refinar_lectura(imagen, bbox_cliente, "cliente")
        if valor_refinado:
            cliente, conf_cliente = valor_refinado, confianza_refinada

    if bbox_factura is not None:
        valor_refinado, confianza_refinada = refinar_lectura(imagen, bbox_factura, "factura")
        if valor_refinado:
            factura, conf_factura = valor_refinado, confianza_refinada

    # Tercer filtro: si el codigo de cliente leido esta muy cerca de uno
    # ya confirmado a mano antes (ej. para el mismo cliente en una
    # factura anterior), se corrige solo. Ataca el caso de "MCMO001" vs
    # "MCM001": una vez confirmado una vez, las siguientes facturas de
    # ese mismo cliente se corrigen automaticamente.
    if cliente:
        codigos_confirmados = aprendizaje.cargar_codigos_confirmados()
        cliente_corregido, se_corrigio = aprendizaje.corregir_con_lista_confirmados(
            cliente, codigos_confirmados
        )
        if se_corrigio:
            cliente = cliente_corregido
            conf_cliente = 100.0  # coincide con un codigo ya confirmado a mano

    return {
        "cliente": cliente, "conf_cliente": conf_cliente, "bbox_cliente": bbox_cliente,
        "factura": factura, "conf_factura": conf_factura, "bbox_factura": bbox_factura,
    }


def obtener_recortes_para_revision(imagen, datos: dict):
    """Devuelve (recorte_codigo_cliente, recorte_factura) para la pantalla manual."""
    ancho, alto = imagen.size
    recorte_cliente = ocr_engine.recorte_desde_bbox(imagen, datos["bbox_cliente"])
    recorte_factura = ocr_engine.recorte_desde_bbox(imagen, datos["bbox_factura"])

    # Respaldo: si no se ubico ni siquiera la etiqueta, se muestra la
    # parte superior del documento (donde normalmente estan estos datos).
    if recorte_cliente is None:
        recorte_cliente = imagen.crop((0, 0, ancho, int(alto * 0.35)))
    if recorte_factura is None:
        recorte_factura = imagen.crop((0, 0, ancho, int(alto * 0.35)))

    return recorte_cliente, recorte_factura
