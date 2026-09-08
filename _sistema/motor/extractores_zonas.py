# -*- coding: utf-8 -*-
"""
extractores_zonas.py
-------------------------------------------------------------------------
Motor "zonas": busca cada Campo dentro de las areas de la pagina que el
usuario marco en el asistente, en vez de buscar etiquetas de texto en
toda la pagina (eso sigue siendo "extractores.py", el motor "clasico",
que esta funcion NUNCA toca).

Con varios Formato configurados, "detectar_formato" decide cual aplica
ANTES de gastar el OCR enfocado (el "refine pass" caro): primero por
"texto_identificador" si esta configurado, y si no, probando todos con
solo el OCR de pagina completa que YA se calculo una vez (sin volver a
invocar Tesseract por cada formato candidato).
-------------------------------------------------------------------------
"""

import re

from . import ocr_engine
from . import preprocesamiento
from . import aprendizaje
from .config import limpiar_texto_extraido
from .settings import valor_cumple_patron, aplicar_conversiones


def _zona_a_pixeles(zona, ancho, alto):
    x0, y0, x1, y1 = zona
    return (x0 * ancho, y0 * alto, x1 * ancho, y1 * alto)


def _area(rect):
    return max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])


def _interseccion_area(a, b):
    izquierda = max(a[0], b[0])
    arriba = max(a[1], b[1])
    derecha = min(a[2], b[2])
    abajo = min(a[3], b[3])
    if derecha <= izquierda or abajo <= arriba:
        return 0
    return (derecha - izquierda) * (abajo - arriba)


def _linea_en_zona(linea, rect_zona_px, umbral=0.3):
    """True si al menos 'umbral' del area de la linea cae dentro de la zona."""
    bbox_linea = (linea["left"], linea["top"], linea["right"], linea["bottom"])
    area_linea = _area(bbox_linea)
    if area_linea <= 0:
        return False
    return (_interseccion_area(bbox_linea, rect_zona_px) / area_linea) >= umbral


def _bbox_de_palabra(p):
    return (p["left"], p["top"], p["left"] + p["width"], p["top"] + p["height"])


def _confianza_rango(linea, char_start, char_end):
    """Confianza promedio de las palabras que cubren el rango [char_start, char_end) en la linea."""
    pos = 0
    confs = []
    for p in linea["palabras"]:
        wstart = pos
        wend = pos + len(p["texto"])
        if p["conf"] >= 0 and wend > char_start and wstart < char_end:
            confs.append(p["conf"])
        pos = wend + 1
    return (sum(confs) / len(confs)) if confs else linea["confianza"]


def _bbox_union(bboxes):
    izquierdas, arribas, derechas, abajos = zip(*bboxes)
    return (min(izquierdas), min(arribas), max(derechas), max(abajos))


def _confianza_en_zona(lineas, zona, ancho, alto):
    """Confianza promedio del OCR en la zona, sin validar patron."""
    rect_px = _zona_a_pixeles(zona, ancho, alto)
    confs = [
        p["conf"] for linea in lineas for p in linea["palabras"]
        if _interseccion_area(_bbox_de_palabra(p), rect_px) > 0 and p["conf"] >= 0
    ]
    return (sum(confs) / len(confs)) if confs else None


def _palabras_en_zona_directo(lineas, rect_px):
    """
    Palabras cuyo bbox intersecta con rect_px, buscadas directamente en
    todas las lineas sin el filtro de superposicion a nivel de linea. Usado
    como respaldo cuando _linea_en_zona filtra toda la linea porque esta es
    mas ancha que la zona (ej. zona cubre el 25% izquierdo de la pagina y
    la linea se extiende de extremo a extremo).
    """
    return sorted(
        [p for linea in lineas for p in linea["palabras"]
         if _interseccion_area(_bbox_de_palabra(p), rect_px) > 0],
        key=lambda p: (p["top"], p["left"]),
    )


_TABLA_NORM_OCR_TODO = str.maketrans("OI", "01")


def _textos_candidatos(texto):
    """
    Devuelve el texto original seguido de variantes con sustitucion O→0/I→1,
    en tres niveles de agresividad:
      1) Original (sin tocar): codigos con O o I reales pasan aqui.
      2) Una posicion a la vez: cubre confusiones simples (ej. EFMO00C→EFM000C,
         FROSTO00→FROST000). Permite corregir un cero confundido sin romper
         las letras reales del codigo.
      3) Todas a la vez: cubre codigos donde el OCR confundio varios ceros
         simultaneamente (ej. BUAROO0→BUAR000, TIANCHENOOO→TIANCHEN000).
    Se limita a textos cortos (<= 30 chars) para no generar variantes
    innecesarias en texto de zona largo.
    """
    if len(texto) > 30:
        return [texto]
    variantes = [texto]
    for i, c in enumerate(texto):
        if c == 'O':
            variantes.append(texto[:i] + '0' + texto[i + 1:])
        elif c == 'I':
            variantes.append(texto[:i] + '1' + texto[i + 1:])
    todo = texto.translate(_TABLA_NORM_OCR_TODO)
    if todo not in variantes:
        variantes.append(todo)
    # Sustitucion espacio->guion_bajo: el OCR a veces lee "_" como " ".
    # Util cuando el patron espera "488892_008" y el OCR devuelve "488892 008".
    if " " in texto:
        sin_espacios = texto.replace(" ", "_")
        if sin_espacios not in variantes:
            variantes.append(sin_espacios)
    return variantes


def _texto_crudo_en_zona(lineas, zona, ancho, alto):
    """Devuelve el texto en bruto encontrado en la zona, sin validar patron."""
    rect_px = _zona_a_pixeles(zona, ancho, alto)
    candidatas = [l for l in lineas if _linea_en_zona(l, rect_px)]
    candidatas.sort(key=lambda l: (l["top"], l["left"]))
    palabras_en_zona = [
        p for linea in candidatas for p in linea["palabras"]
        if _interseccion_area(_bbox_de_palabra(p), rect_px) > 0
    ]
    # Respaldo: si el filtro de lineas no encontro ninguna candidata (porque
    # las lineas son mas anchas que la zona), buscar directamente por palabra.
    if not palabras_en_zona:
        palabras_en_zona = _palabras_en_zona_directo(lineas, rect_px)
    if palabras_en_zona:
        return " ".join(p["texto"] for p in palabras_en_zona).strip() or None
    return None


def buscar_campo_por_etiqueta(lineas, campo):
    """
    Busca el valor de 'campo' localizando su 'etiqueta' en el OCR y
    extrayendo lo que le sigue en la misma linea o en la siguiente.
    Mas robusto que zonas fijas para documentos escaneados desplazados.

    Estrategia:
      1) Encontrar la linea que contiene la etiqueta.
      2) Extraer el texto que sigue en esa misma linea (tras separadores : - =).
      3) Si no coincide con el patron, intentar la linea siguiente completa.
      4) Palabra por palabra en la linea siguiente.

    Returns (valor, confianza, bbox) o (None, None, None).
    """
    if not campo.etiqueta:
        return None, None, None

    try:
        regex = re.compile(campo.patron_validacion, re.IGNORECASE)
    except re.error:
        return None, None, None

    etiqueta_upper = campo.etiqueta.upper().strip()
    lineas_ord = sorted(lineas, key=lambda l: (l["top"], l["left"]))

    for i, linea in enumerate(lineas_ord):
        if etiqueta_upper not in linea["texto"].upper():
            continue

        # ---- Caso 1: valor en la misma linea, despues de la etiqueta ----
        idx_fin = linea["texto"].upper().find(etiqueta_upper) + len(etiqueta_upper)
        texto_post_raw = linea["texto"][idx_fin:]
        match_sep = re.match(r'^[\s:=\-]+', texto_post_raw)
        sep_len = len(match_sep.group(0)) if match_sep else 0
        texto_post = texto_post_raw[sep_len:]
        abs_offset = idx_fin + sep_len

        if texto_post:
            for texto_cand in _textos_candidatos(texto_post):
                m = regex.search(texto_cand)
                if m:
                    valor = limpiar_texto_extraido(m.group(0))
                    if campo.longitud_minima and len(valor) < campo.longitud_minima:
                        continue
                    bbox = ocr_engine.bbox_de_rango(linea, abs_offset + m.start(), abs_offset + m.end())
                    return valor, _confianza_rango(linea, abs_offset + m.start(), abs_offset + m.end()), bbox

        # ---- Caso 2: valor en la linea siguiente ----
        if i + 1 < len(lineas_ord):
            linea_sig = lineas_ord[i + 1]
            for texto_cand in _textos_candidatos(linea_sig["texto"]):
                m = regex.search(texto_cand)
                if m:
                    valor = limpiar_texto_extraido(m.group(0))
                    if campo.longitud_minima and len(valor) < campo.longitud_minima:
                        continue
                    bbox = ocr_engine.bbox_de_rango(linea_sig, m.start(), m.end())
                    return valor, _confianza_rango(linea_sig, m.start(), m.end()), bbox
            for p in sorted(linea_sig["palabras"], key=lambda p: p["left"]):
                for texto_cand in _textos_candidatos(p["texto"]):
                    m = regex.search(texto_cand)
                    if m:
                        valor = limpiar_texto_extraido(m.group(0))
                        if campo.longitud_minima and len(valor) < campo.longitud_minima:
                            continue
                        confianza = p["conf"] if p["conf"] >= 0 else None
                        return valor, confianza, _bbox_de_palabra(p)

    return None, None, None


def buscar_campo_por_zona(lineas, campo, ancho, alto):
    """
    Busca el valor de "campo" dentro de sus zonas (probadas en orden). En
    cada zona se intenta, de mas a menos exigente:
      1) que una linea COMPLETA dentro de la zona cumpla el patron
         (caso mas comun: la zona solo contiene el valor).
      2) palabra por palabra (por si la zona tiene mas texto ademas del
         valor, ej. una etiqueta que quedo parcialmente adentro).
      3) todas las palabras de la zona concatenadas (por si el OCR partio
         el valor en dos palabras o filas distintas).
    Devuelve (valor, confianza, bbox_en_pixeles) o (None, None, None).
    """
    try:
        regex = re.compile(campo.patron_validacion, re.IGNORECASE)
    except re.error:
        return None, None, None

    for zona in campo.zonas:
        rect_px = _zona_a_pixeles(zona, ancho, alto)
        candidatas = [l for l in lineas if _linea_en_zona(l, rect_px)]
        candidatas.sort(key=lambda l: (l["top"], l["left"]))

        for linea in candidatas:
            for texto_cand in _textos_candidatos(linea["texto"]):
                m = regex.search(texto_cand)
                if m:
                    valor = limpiar_texto_extraido(m.group(0))
                    if campo.longitud_minima and len(valor) < campo.longitud_minima:
                        continue
                    bbox = ocr_engine.bbox_de_rango(linea, m.start(), m.end())
                    return valor, _confianza_rango(linea, m.start(), m.end()), bbox

        palabras_en_zona = [
            p for linea in candidatas for p in linea["palabras"]
            if _interseccion_area(_bbox_de_palabra(p), rect_px) > 0
        ]

        for p in palabras_en_zona:
            for texto_cand in _textos_candidatos(p["texto"]):
                m = regex.search(texto_cand)
                if m:
                    valor = limpiar_texto_extraido(m.group(0))
                    if campo.longitud_minima and len(valor) < campo.longitud_minima:
                        continue
                    confianza = p["conf"] if p["conf"] >= 0 else None
                    return valor, confianza, _bbox_de_palabra(p)

        if palabras_en_zona:
            texto_zona = " ".join(p["texto"] for p in palabras_en_zona)
            for texto_cand in _textos_candidatos(texto_zona):
                m = regex.search(texto_cand)
                if m:
                    valor = limpiar_texto_extraido(m.group(0))
                    if campo.longitud_minima and len(valor) < campo.longitud_minima:
                        continue
                    confs = [p["conf"] for p in palabras_en_zona if p["conf"] >= 0]
                    confianza = (sum(confs) / len(confs)) if confs else None
                    bbox = _bbox_union([_bbox_de_palabra(p) for p in palabras_en_zona])
                    return valor, confianza, bbox

        # Respaldo: si el filtro de lineas no encontro candidatas (lineas mas
        # anchas que la zona), buscar directamente a nivel de palabra.
        if not candidatas:
            palabras_directo = _palabras_en_zona_directo(lineas, rect_px)
            for p in palabras_directo:
                for texto_cand in _textos_candidatos(p["texto"]):
                    m = regex.search(texto_cand)
                    if m:
                        valor = limpiar_texto_extraido(m.group(0))
                        if campo.longitud_minima and len(valor) < campo.longitud_minima:
                            continue
                        confianza = p["conf"] if p["conf"] >= 0 else None
                        return valor, confianza, _bbox_de_palabra(p)
            if palabras_directo:
                texto_zona = " ".join(p["texto"] for p in palabras_directo)
                for texto_cand in _textos_candidatos(texto_zona):
                    m = regex.search(texto_cand)
                    if m:
                        valor = limpiar_texto_extraido(m.group(0))
                        if campo.longitud_minima and len(valor) < campo.longitud_minima:
                            continue
                        confs = [p["conf"] for p in palabras_directo if p["conf"] >= 0]
                        confianza = (sum(confs) / len(confs)) if confs else None
                        bbox = _bbox_union([_bbox_de_palabra(p) for p in palabras_directo])
                        return valor, confianza, bbox

    return None, None, None


def refinar_lectura_generico(imagen_pagina, bbox, campo):
    """
    Segunda pasada de OCR sobre el recorte encontrado (igual idea que
    extractores.refinar_lectura, pero validando contra el patron del
    campo en vez de contra buscar_cliente/buscar_factura). Devuelve
    (valor, confianza) o (None, None) si no logra leer nada valido -- en
    ese caso se conserva el resultado del primer barrido, sin regresion.
    """
    recorte = ocr_engine.recorte_desde_bbox(imagen_pagina, bbox, margen=15)
    if recorte is None:
        return None, None

    try:
        regex = re.compile(campo.patron_validacion, re.IGNORECASE)
    except re.error:
        return None, None

    recorte_grande = ocr_engine.agrandar_recorte(recorte)
    recorte_procesado = preprocesamiento.preparar_recorte_para_refinar(recorte_grande)
    lineas_recorte = ocr_engine.obtener_lineas_ocr(recorte_procesado, config="--psm 7")
    if not lineas_recorte:
        return None, None

    for linea in lineas_recorte:
        for texto_cand in _textos_candidatos(linea["texto"]):
            m = regex.search(texto_cand)
            if m:
                return limpiar_texto_extraido(m.group(0)), linea["confianza"]

    todas_palabras = [p for linea in lineas_recorte for p in linea["palabras"]]
    texto_concatenado = " ".join(p["texto"] for p in todas_palabras)
    for texto_cand in _textos_candidatos(texto_concatenado):
        m = regex.search(texto_cand)
        if m:
            confs = [p["conf"] for p in todas_palabras if p["conf"] >= 0]
            confianza = (sum(confs) / len(confs)) if confs else None
            return limpiar_texto_extraido(m.group(0)), confianza

    return None, None


def detectar_formato(lineas_pagina_0, ancho, alto, formatos):
    """
    Decide cual Formato (de una lista de 1 o mas) aplica a un documento,
    usando SOLO el OCR ya calculado de su primera pagina (nunca se vuelve
    a invocar Tesseract aqui). Simplificacion deliberada: la puntuacion de
    desempate solo mira los campos configurados en la pagina 0 de cada
    formato -- es la pagina donde casi siempre esta el dato que identifica
    el documento, y evita tener que OCRear paginas siguientes de un
    documento para CADA formato candidato solo para decidir cual usar.

    Orden de decision:
      1) Si algun Formato tiene "texto_identificador" y aparece en el
         texto de la pagina, se usa ese (determinista, sin ambiguedad).
      2) Si no, se prueban todos con buscar_campo_por_zona (barato: solo
         regex en Python, cero OCR adicional) y gana el que valide mas
         campos obligatorios de su pagina 0; empate -> gana el primero en
         la lista (el usuario controla el orden en el asistente).

    Devuelve el Formato elegido, o None si la lista esta vacia.
    """
    if not formatos:
        return None
    if len(formatos) == 1:
        return formatos[0]

    texto_pagina = " ".join(l["texto"] for l in lineas_pagina_0)
    for formato in formatos:
        if not formato.texto_identificador:
            continue
        try:
            if re.search(formato.texto_identificador, texto_pagina, re.IGNORECASE):
                return formato
        except re.error:
            continue

    mejor_formato, mejor_score = None, (-1, -1.0)
    for formato in formatos:
        campos_pagina_0 = [c for c in formato.campos if c.pagina == 0]
        validados, confianzas = [], []
        for campo in campos_pagina_0:
            if not campo.obligatorio:
                continue
            valor, confianza, _bbox = None, None, None
            if campo.zonas:
                valor, confianza, _bbox = buscar_campo_por_zona(lineas_pagina_0, campo, ancho, alto)
            if valor is None and campo.etiqueta:
                valor, confianza, _bbox = buscar_campo_por_etiqueta(lineas_pagina_0, campo)
            if valor and campo.mayusculas_forzadas:
                valor = valor.upper()
            if valor_cumple_patron(valor, campo.patron_validacion):
                validados.append(campo)
                if confianza is not None:
                    confianzas.append(confianza)
        confianza_prom = (sum(confianzas) / len(confianzas)) if confianzas else 0.0
        score = (len(validados), confianza_prom)
        if score > mejor_score:
            mejor_score, mejor_formato = score, formato

    return mejor_formato


def extraer_datos_formato_multipagina(imagenes_documento, formato):
    """
    Aplica TODOS los campos de "formato" a un documento logico ya
    convertido a imagenes (una por pagina, en orden). Cada campo se busca
    en la pagina que le corresponde (campo.pagina); el OCR de pagina
    completa se corre una sola vez por pagina, aunque varios campos
    compartan la misma.

    Devuelve {"campos": {nombre: {"valor","confianza","bbox","valido","pagina","imagen"}}}.
    "imagen" es la pagina PIL de la que salio ese campo (para poder
    recortarla despues en la ventana de revision manual sin tener que
    volver a buscar el indice de pagina).
    """
    resultado = {"campos": {}}
    cache_lineas = {}

    for campo in formato.campos:
        indice_pagina = campo.pagina
        if indice_pagina < 0 or indice_pagina >= len(imagenes_documento):
            resultado["campos"][campo.nombre] = {
                "valor": None, "confianza": None, "bbox": None,
                "valido": False, "pagina": indice_pagina, "imagen": None,
            }
            continue

        imagen = imagenes_documento[indice_pagina]
        if indice_pagina not in cache_lineas:
            cache_lineas[indice_pagina] = ocr_engine.obtener_lineas_ocr(imagen)
        lineas = cache_lineas[indice_pagina]
        ancho, alto = imagen.size

        valor, confianza, bbox = None, None, None
        if campo.zonas:
            valor, confianza, bbox = buscar_campo_por_zona(lineas, campo, ancho, alto)
        if valor is None and campo.etiqueta:
            valor, confianza, bbox = buscar_campo_por_etiqueta(lineas, campo)

        if bbox is not None:
            valor_refinado, confianza_refinada = refinar_lectura_generico(imagen, bbox, campo)
            if valor_refinado:
                valor, confianza = valor_refinado, confianza_refinada

        if valor and campo.mayusculas_forzadas:
            valor = valor.upper()

        # Conversiones: primero contra el valor extraido; si no coincide,
        # intentar contra el texto completo de la zona. Esto permite que
        # una regla como "Davivienda" -> "DAV" funcione aunque el patron
        # solo haya extraido una palabra suelta (ej. "Banco").
        if campo.conversiones:
            convertido = aplicar_conversiones(valor, campo.conversiones) if valor else valor
            if convertido != valor:
                valor = convertido
            elif campo.zonas:
                texto_zona = _texto_crudo_en_zona(lineas, campo.zonas[0], ancho, alto)
                if texto_zona:
                    resultado_zona = aplicar_conversiones(texto_zona, campo.conversiones)
                    if resultado_zona != texto_zona:
                        valor = resultado_zona
                        # La conversion vino del texto de zona (no de la palabra extraida):
                        # reemplazar bbox y confianza para reflejar la zona real del campo.
                        bbox = tuple(int(c) for c in _zona_a_pixeles(campo.zonas[0], ancho, alto))
                        confianza = _confianza_en_zona(lineas, campo.zonas[0], ancho, alto)

        # Corrección de confusiones OCR (O↔0, I↔1) contra la lista de
        # valores ya confirmados a mano para este campo.
        if valor:
            codigos_campo = aprendizaje.cargar_codigos_confirmados(campo.nombre)
            valor, _ = aprendizaje.corregir_con_lista_confirmados(valor, codigos_campo)

        # Si no se encontro un valor valido, capturar de todas formas la
        # confianza promedio del OCR en la zona y el texto en bruto. La
        # confianza permite distinguir en el log "OCR leyo bien pero el
        # patron no coincidio" de "la zona no tenia texto legible", sin
        # tener que abrir la ventana de revision para saberlo.
        texto_crudo = None
        if valor is None and campo.zonas:
            confianza = _confianza_en_zona(lineas, campo.zonas[0], ancho, alto)
            texto_crudo = _texto_crudo_en_zona(lineas, campo.zonas[0], ancho, alto)
            if texto_crudo and campo.mayusculas_forzadas:
                texto_crudo = texto_crudo.upper()

        valido = valor_cumple_patron(valor, campo.patron_validacion)
        resultado["campos"][campo.nombre] = {
            "valor": valor, "confianza": confianza, "bbox": bbox,
            "valido": valido, "pagina": indice_pagina, "imagen": imagen,
            "texto_crudo": texto_crudo,
        }

    return resultado
