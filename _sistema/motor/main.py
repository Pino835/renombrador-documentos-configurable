# -*- coding: utf-8 -*-
"""
main.py
-------------------------------------------------------------------------
Orquesta todo el proceso. A diferencia de la version anterior (que solo
sabia leer "cliente" y "factura" con patrones fijos), ahora el documento a
procesar esta descrito por "settings.json" (ver settings.py):

  - modo_entrada: los PDF de PRUEBA vienen SUELTOS (cada archivo es un
    documento) o COMBINADOS (un PDF trae varios documentos, que hay que
    separar primero -- ver division_documentos.py).
  - formatos: uno o mas "Formato", cada uno con motor "clasico" (el
    pipeline de siempre, extractores.py sin tocar) o "zonas" (campos
    ubicados por recorte de la pagina, ver extractores_zonas.py). Si hay
    varios, se detecta cual aplica antes de gastar el OCR enfocado.

Con eso, el resto del flujo es el mismo de siempre:
  1. Fase automatica: lo que se puede leer bien (con confianza suficiente
     y cumpliendo el patron de cada campo) se guarda ya renombrado.
  2. Fase manual: lo que quedo en POR_REVISAR (de esta corrida o de
     antes) se revisa uno por uno, mostrando TODOS los campos del formato
     detectado (no solo 2 fijos).
  3. Resumen final.
-------------------------------------------------------------------------
"""

import sys
import tkinter as tk
from tkinter import messagebox, ttk
from PIL import Image

from . import ocr_engine
from . import extractores
from . import extractores_zonas
from . import division_documentos
from . import preprocesamiento
from . import aprendizaje
from . import almacenamiento
from . import registro
from . import gui
from . import settings
from . import asistente
from .config import CFG

# Cantidad minima de paginas a leer por documento. Los formatos actuales
# (TRANSFERENCIA BANCARIA, DIARIO DE PAGOS) son siempre de una sola
# pagina, asi que se procesa solo esa por defecto -- evita convertir y
# hacerle OCR a 2 paginas de mas en cada archivo. Si algun campo de algun
# Formato pide una pagina mas alla de esta, se usa esa cantidad en su
# lugar (ver _tope_paginas_ocr), asi que un formato futuro a 2+ paginas
# sigue funcionando sin tocar esta constante.
TOPE_PAGINAS_BASE = 1


def _paginas_enderezadas(imagenes):
    """
    Corrige la orientacion (90/180/270) de cada pagina antes del OCR de
    zonas. En el modo "combinados" esto ya lo hacia division_documentos.py
    al separar el PDF; en modo "separados" (el mas comun) las imagenes
    nunca pasaban por aqui, asi que un PDF escaneado de lado se procesaba
    tal cual, produciendo lecturas sin sentido en todas las zonas.
    """
    return [preprocesamiento.preparar_pagina_completa(imagen, CFG.idiomas_ocr) for imagen in imagenes]


def _tope_paginas_ocr(settings_actual: settings.Settings) -> int:
    max_pagina_configurada = -1
    for formato in settings_actual.formatos:
        for campo in formato.campos:
            max_pagina_configurada = max(max_pagina_configurada, campo.pagina)
    return max(TOPE_PAGINAS_BASE, max_pagina_configurada + 1)


# =========================================================================
# Adaptador del motor "clasico" a la forma generica {"campos": {...}}
# =========================================================================

def _datos_clasico_a_campos(imagen, datos_clasico):
    return {
        "campos": {
            "cliente": {
                "valor": datos_clasico["cliente"], "confianza": datos_clasico["conf_cliente"],
                "bbox": datos_clasico["bbox_cliente"], "valido": bool(datos_clasico["cliente"]),
                "pagina": 0, "imagen": imagen,
            },
            "factura": {
                "valor": datos_clasico["factura"], "confianza": datos_clasico["conf_factura"],
                "bbox": datos_clasico["bbox_factura"], "valido": bool(datos_clasico["factura"]),
                "pagina": 0, "imagen": imagen,
            },
        }
    }


def _es_confiable(datos_generico, formato):
    """
    Un documento es "confiable" (se acepta automaticamente) si TODOS sus
    campos obligatorios tienen valor, cumplen su patron de validacion, y
    la confianza del OCR alcanza el umbral configurado. Para el motor
    "clasico" los campos obligatorios son siempre "cliente" y "factura"
    (igual que la version anterior); para "zonas" son los que se marcaron
    con obligatorio=True en el asistente.
    """
    if formato.motor == "clasico":
        nombres_obligatorios = ["cliente", "factura"]
    else:
        nombres_obligatorios = [c.nombre for c in formato.campos if c.obligatorio]

    campos = datos_generico["campos"]
    campos_obligatorios = [campos[n] for n in nombres_obligatorios if n in campos]
    if len(campos_obligatorios) < len(nombres_obligatorios):
        return False

    todos_con_valor = all(c["valor"] for c in campos_obligatorios)
    if formato.motor == "clasico":
        todos_validos = todos_con_valor
    else:
        todos_validos = all(c["valido"] for c in campos_obligatorios)

    confianza_suficiente = all(
        c["confianza"] is None or c["confianza"] >= CFG.umbral_confianza_minima
        for c in campos_obligatorios
    )

    return bool(todos_con_valor and todos_validos and confianza_suficiente)


def _elegir_formato(imagen_pagina0, formatos):
    if not formatos:
        return None
    if len(formatos) == 1:
        return formatos[0]
    lineas0 = ocr_engine.obtener_lineas_ocr(imagen_pagina0)
    ancho, alto = imagen_pagina0.size
    return extractores_zonas.detectar_formato(lineas0, ancho, alto, formatos)


def _procesar_clasico_multipagina(imagenes, formato):
    """Igual idea que antes: se prueba pagina por pagina hasta encontrar una confiable; si no, se usa la mejor."""
    mejor = None
    for imagen in imagenes:
        datos_pagina = extractores.extraer_datos(imagen)
        datos_generico = _datos_clasico_a_campos(imagen, datos_pagina)
        confiable = _es_confiable(datos_generico, formato)
        actual = (datos_generico, confiable)
        if confiable:
            return actual
        if mejor is None:
            mejor = actual
        else:
            cuenta_actual = sum(1 for c in datos_generico["campos"].values() if c["valor"])
            cuenta_mejor = sum(1 for c in mejor[0]["campos"].values() if c["valor"])
            if cuenta_actual > cuenta_mejor:
                mejor = actual
    return mejor


def _procesar_documento(imagenes, formatos):
    """Devuelve {"formato","datos","confiable"} para un documento logico ya convertido a imagenes."""
    if not imagenes:
        return None

    formato = _elegir_formato(imagenes[0], formatos)
    if formato is None:
        return {"formato": None, "datos": {"campos": {}}, "confiable": False}

    if formato.motor == "clasico":
        datos_generico, confiable = _procesar_clasico_multipagina(imagenes, formato)
    else:
        datos_generico = extractores_zonas.extraer_datos_formato_multipagina(imagenes, formato)
        confiable = _es_confiable(datos_generico, formato)

    return {"formato": formato, "datos": datos_generico, "confiable": confiable}


def _resolver_nombre_base(formato, settings_actual, datos_generico):
    """Devuelve (nombre_base, None) o (None, motivo) si falta algun campo que pide el patron."""
    patron = (
        formato.patron_nombre_archivo if (formato and formato.patron_nombre_archivo)
        else settings_actual.patron_nombre_archivo
    )
    valores = {nombre: info["valor"] for nombre, info in datos_generico["campos"].items() if info["valor"]}
    try:
        return settings.construir_nombre_archivo(patron, valores), None
    except KeyError as error:
        return None, f"falta el campo {error} para construir el nombre de archivo (patron '{patron}')"


def _recorte_para_campo(info_campo, imagenes_documento, campo_cfg=None):
    imagen = info_campo.get("imagen")
    bbox = info_campo.get("bbox")
    if imagen is not None and bbox is not None:
        recorte = ocr_engine.recorte_desde_bbox(imagen, bbox)
        if recorte is not None:
            return recorte
    # Respaldo 1: si el campo tiene zona configurada, mostrar exactamente
    # esa zona para que el usuario vea el area que configuro.
    imagen_base = imagen if imagen is not None else (imagenes_documento[0] if imagenes_documento else None)
    if imagen_base is not None and campo_cfg is not None and campo_cfg.zonas:
        zona = campo_cfg.zonas[0]
        ancho, alto = imagen_base.size
        x0, y0, x1, y1 = zona
        return imagen_base.crop((int(x0 * ancho), int(y0 * alto), int(x1 * ancho), int(y1 * alto)))
    # Respaldo 2: parte superior de la primera pagina.
    if imagenes_documento:
        imagen_respaldo = imagenes_documento[0]
        ancho, alto = imagen_respaldo.size
        return imagen_respaldo.crop((0, 0, ancho, int(alto * 0.35)))
    return Image.new("RGB", (600, 150), "white")


def _armar_campos_revision(formato, datos_generico, imagenes_documento):
    """Arma la lista de gui.CampoRevision a mostrar en la ventana de revision manual."""
    vacio = {"valor": None, "bbox": None, "imagen": None, "valido": False}
    campos_revision = []

    if formato is not None and formato.motor == "zonas":
        for campo_cfg in formato.campos:
            info = datos_generico["campos"].get(campo_cfg.nombre, vacio)
            recorte = _recorte_para_campo(info, imagenes_documento, campo_cfg)
            # Si el OCR no encontro un valor valido pero leyo algo en la zona,
            # se precarga ese texto crudo para que el usuario lo vea y corrija.
            valor_previo = info.get("valor") or info.get("texto_crudo")
            campos_revision.append(gui.CampoRevision(
                nombre=campo_cfg.nombre, recorte=recorte,
                valor_previo=valor_previo, patron_valido=info.get("valido"),
                obligatorio=campo_cfg.obligatorio,
            ))
    else:
        for nombre in ("cliente", "factura"):
            info = datos_generico["campos"].get(nombre, vacio)
            recorte = _recorte_para_campo(info, imagenes_documento)
            campos_revision.append(gui.CampoRevision(
                nombre=nombre, recorte=recorte,
                valor_previo=info.get("valor"), patron_valido=info.get("valido"),
                obligatorio=True,
            ))

    return campos_revision


# =========================================================================
# Fase 1: automatica
# =========================================================================

def _construir_items(archivos_pdf, settings_actual):
    """
    Lista de (ruta_pdf, grupo) a procesar. En modo 'separados', grupo es
    None (el PDF completo es el documento). En modo 'juntos', un PDF
    combinado aporta un item por cada GrupoDocumento que resulte de
    separarlo (ver division_documentos.py).
    """
    items = []
    if settings_actual.modo_entrada.tipo == "separados":
        for ruta_pdf in archivos_pdf:
            items.append((ruta_pdf, None))
        return items

    for ruta_pdf in archivos_pdf:
        for grupo in division_documentos.separar_documentos(ruta_pdf, settings_actual.modo_entrada):
            items.append((ruta_pdf, grupo))
    return items


def _etiqueta_item(ruta_pdf, grupo):
    if grupo is None:
        return ruta_pdf.name
    return f"{ruta_pdf.name} (pag. {grupo.pagina_inicio + 1}-{grupo.pagina_fin + 1})"


def _nombre_sugerido_grupo(ruta_pdf, grupo):
    return f"{ruta_pdf.stem}__pag{grupo.pagina_inicio + 1}-{grupo.pagina_fin + 1}"


def _enviar_a_por_revisar(ruta_pdf, grupo):
    if grupo is None:
        almacenamiento.copiar_a_por_revisar(ruta_pdf)
    else:
        almacenamiento.copiar_subconjunto_paginas_a_por_revisar(
            ruta_pdf, grupo.pagina_inicio, grupo.pagina_fin, _nombre_sugerido_grupo(ruta_pdf, grupo),
        )


def fase_1_automatica(items, ventana_progreso, settings_actual):
    total_ok = 0
    total_enviados_a_revisar = 0
    tope = _tope_paginas_ocr(settings_actual)

    for indice, (ruta_pdf, grupo) in enumerate(items, start=1):
        etiqueta = _etiqueta_item(ruta_pdf, grupo)
        ventana_progreso.actualizar(indice, len(items), etiqueta)

        if grupo is not None and not grupo.confiable:
            # La propia separacion del PDF combinado ya detecto un
            # problema (pagina huerfana, documento truncado, etc.): va
            # directo a revision manual sin intentar la fase automatica.
            _enviar_a_por_revisar(ruta_pdf, grupo)
            registro.registrar(etiqueta, None, {}, "automatico",
                                f"DIVISION NO CONFIABLE ({grupo.motivo})")
            total_enviados_a_revisar += 1
            continue

        try:
            if grupo is None:
                imagenes = ocr_engine.pdf_a_imagenes(ruta_pdf, max_paginas=tope)
            else:
                limite = min(grupo.pagina_fin, grupo.pagina_inicio + tope - 1)
                imagenes = ocr_engine.imagenes_de_rango(ruta_pdf, grupo.pagina_inicio, limite)
            if not imagenes:
                raise ValueError("no se pudieron obtener paginas legibles")
            imagenes = _paginas_enderezadas(imagenes)
            resultado = _procesar_documento(imagenes, settings_actual.formatos)
        except Exception as error:
            _enviar_a_por_revisar(ruta_pdf, grupo)
            registro.registrar(etiqueta, None, {}, "automatico", f"ERROR AL LEER ({error})")
            total_enviados_a_revisar += 1
            continue

        formato = resultado["formato"]
        datos_generico = resultado["datos"]
        confiable = resultado["confiable"]
        # Si el OCR no encontro valor valido pero leyo texto en la zona
        # (texto_crudo), se guarda ese texto en el log para diagnostico:
        # permite ver que habia en la zona sin tener que abrir la ventana
        # de revision (ej. "CANTIDAD PRECIO UNITARIO" indica zona erronea).
        campos_para_log = {
            nombre: info["valor"] or info.get("texto_crudo")
            for nombre, info in datos_generico["campos"].items()
        }
        confianzas_para_log = {
            nombre: info["confianza"]
            for nombre, info in datos_generico["campos"].items()
            if info.get("confianza") is not None
        }

        nombre_base, motivo_error_nombre = (None, None)
        if confiable:
            nombre_base, motivo_error_nombre = _resolver_nombre_base(formato, settings_actual, datos_generico)
            if motivo_error_nombre:
                confiable = False

        if confiable:
            if grupo is None:
                nombre_final = almacenamiento.guardar_resultado(ruta_pdf, nombre_base)
            else:
                nombre_final = almacenamiento.guardar_resultado_subconjunto_paginas(
                    ruta_pdf, grupo.pagina_inicio, grupo.pagina_fin, nombre_base
                )
            registro.registrar(etiqueta, nombre_final, campos_para_log, "automatico", "OK",
                               confianzas=confianzas_para_log)
            total_ok += 1
        else:
            _enviar_a_por_revisar(ruta_pdf, grupo)
            if motivo_error_nombre:
                estado = motivo_error_nombre
            elif any(campos_para_log.values()):
                partes = []
                if formato is not None:
                    campos_oblig = [
                        (c.nombre, datos_generico["campos"].get(c.nombre, {}))
                        for c in formato.campos if c.obligatorio
                    ]
                    sin_valor = [
                        nombre for nombre, info in campos_oblig
                        if not info.get("valor")
                    ]
                    fallos_patron = [
                        nombre for nombre, info in campos_oblig
                        if info.get("valor") and not info.get("valido")
                    ]
                    fallos_confianza = [
                        f"{nombre}={info['confianza']:.0f}%"
                        for nombre, info in campos_oblig
                        if info.get("confianza") is not None
                        and info["confianza"] < CFG.umbral_confianza_minima
                    ]
                    if sin_valor:
                        partes.append("sin valor valido: " + ", ".join(sin_valor))
                    if fallos_patron:
                        partes.append("patron invalido: " + ", ".join(fallos_patron))
                    if fallos_confianza:
                        partes.append("confianza baja: " + ", ".join(fallos_confianza))
                estado = "A REVISION MANUAL" + (" — " + "; ".join(partes) if partes else "")
            registro.registrar(etiqueta, None, campos_para_log, "automatico", estado,
                               confianzas=confianzas_para_log)
            total_enviados_a_revisar += 1

    return total_ok, total_enviados_a_revisar


# =========================================================================
# Fase 2: manual
# =========================================================================

def fase_2_manual(raiz: tk.Tk, settings_actual: settings.Settings):
    total_manual_ok = 0
    total_omitidos = 0
    tope = _tope_paginas_ocr(settings_actual)

    pendientes = almacenamiento.listar_pdfs(CFG.carpeta_por_revisar)
    if not pendientes:
        return 0, 0

    # -- Etapa 2a: pre-procesar todos los archivos pendientes ------------------
    # Se hace antes de abrir la ventana de revision para que el usuario no
    # tenga que esperar entre archivo y archivo: la ventana se abre una sola
    # vez con todo listo.
    datos_pendientes = []   # (ruta_pdf, formato, campos_revision)
    progreso = gui.VentanaProgreso(raiz, len(pendientes))
    for indice, ruta_pdf in enumerate(pendientes, start=1):
        progreso.actualizar(indice, len(pendientes), ruta_pdf.name)
        raiz.update()
        try:
            imagenes = ocr_engine.pdf_a_imagenes(ruta_pdf, max_paginas=tope)
            imagenes = _paginas_enderezadas(imagenes)
            resultado = _procesar_documento(imagenes, settings_actual.formatos) if imagenes else None
        except Exception:
            imagenes = []
            resultado = None

        if resultado is not None:
            formato = resultado["formato"]
            datos_generico = resultado["datos"]
        else:
            formato = _elegir_formato(imagenes[0], settings_actual.formatos) if imagenes else None
            datos_generico = {"campos": {}}

        campos_revision = _armar_campos_revision(formato, datos_generico, imagenes)
        datos_pendientes.append((ruta_pdf, formato, campos_revision))
    progreso.destroy()

    # -- Etapa 2b: ventana unica de revision -----------------------------------
    items_ventana = [(ruta_pdf, ruta_pdf.name, campos) for ruta_pdf, formato, campos in datos_pendientes]
    ventana = gui.VentanaRevisionManual(raiz, items_ventana)
    raiz.wait_window(ventana)

    # -- Etapa 2c: procesar resultados -----------------------------------------
    for (ruta_pdf, formato, campos_revision), (accion, valores_corregidos) in zip(
        datos_pendientes, ventana.resultados
    ):
        if accion == "cancelar":
            campos_para_log = {c.nombre: c.valor_previo for c in campos_revision}
            registro.registrar(ruta_pdf.name, None, campos_para_log, "manual",
                               "OMITIDO (queda en POR_REVISAR)")
            total_omitidos += 1
            continue

        for nombre_campo, valor in valores_corregidos.items():
            aprendizaje.agregar_codigo_confirmado(valor, campo=nombre_campo)

        patrones_a_probar = []
        if formato and formato.patron_nombre_archivo:
            patrones_a_probar.append(formato.patron_nombre_archivo)
        patrones_a_probar.append(settings_actual.patron_nombre_archivo)

        nombre_base = None
        ultimo_error = None
        for patron in patrones_a_probar:
            try:
                nombre_base = settings.construir_nombre_archivo(patron, valores_corregidos)
                break
            except KeyError as error:
                ultimo_error = error

        if nombre_base is None:
            registro.registrar(ruta_pdf.name, None, valores_corregidos, "manual",
                               f"ERROR: falta {ultimo_error} para el nombre de archivo")
            total_omitidos += 1
            continue

        # Reintento si el archivo esta abierto en otro programa (ej. Adobe).
        guardado_ok = False
        while True:
            try:
                nombre_final = almacenamiento.guardar_resultado(ruta_pdf, nombre_base)
                almacenamiento.borrar_de_por_revisar(ruta_pdf)
                guardado_ok = True
                break
            except PermissionError:
                respuesta = tk.messagebox.askretrycancel(
                    "Archivo en uso",
                    f"No se puede mover '{ruta_pdf.name}' porque está abierto en otro programa.\n\n"
                    "Cierre el archivo y haga clic en Reintentar.",
                    parent=raiz,
                )
                if not respuesta:
                    break

        if guardado_ok:
            registro.registrar(ruta_pdf.name, nombre_final, valores_corregidos, "manual", "OK")
            total_manual_ok += 1
        else:
            registro.registrar(ruta_pdf.name, None, valores_corregidos, "manual",
                               "OMITIDO — archivo en uso al intentar mover")
            total_omitidos += 1

    return total_manual_ok, total_omitidos


def mostrar_resumen(total_ok, total_manual_ok, total_omitidos):
    mensaje = (
        f"Proceso terminado.\n\n"
        f"Renombrados automaticamente: {total_ok}\n"
        f"Renombrados con revision manual: {total_manual_ok}\n"
        f"Omitidos (siguen en POR_REVISAR): {total_omitidos}\n\n"
        f"Carpeta de resultado de hoy:\n{CFG.carpeta_resultado_hoy}\n\n"
        f"Detalle de esta y otras ejecuciones:\n{CFG.log_path}"
    )
    messagebox.showinfo("Resumen del proceso", mensaje)


def _preguntar_usar_anterior_o_modificar(raiz: tk.Tk) -> bool:
    """Ventana simple: True = usar la configuracion guardada tal cual; False = modificarla."""
    ventana = tk.Toplevel(raiz)
    ventana.title("Configuracion existente")
    ventana.resizable(False, False)
    respuesta = {"usar_anterior": True}

    contenedor = ttk.Frame(ventana, padding=20)
    contenedor.pack()
    ttk.Label(
        contenedor,
        text="Ya existe una configuracion guardada de una vez anterior.\n¿Que desea hacer?",
        justify="center",
    ).pack(pady=(0, 16))

    def _usar_anterior():
        respuesta["usar_anterior"] = True
        ventana.destroy()

    def _modificar():
        respuesta["usar_anterior"] = False
        ventana.destroy()

    fila = ttk.Frame(contenedor)
    fila.pack()
    ttk.Button(fila, text="Usar la configuracion anterior", command=_usar_anterior).pack(side="left", padx=6)
    ttk.Button(fila, text="Modificarla ahora", command=_modificar).pack(side="left", padx=6)

    ventana.protocol("WM_DELETE_WINDOW", _usar_anterior)  # cerrar sin elegir = opcion segura (usar la anterior)
    ventana.grab_set()
    raiz.wait_window(ventana)
    return respuesta["usar_anterior"]


def _obtener_settings(raiz: tk.Tk) -> settings.Settings:
    """
    Si no hay settings.json todavia, obliga a completar el asistente de
    configuracion. Si ya existe, pregunta si se quiere usar tal cual o
    modificarla (reabriendo el asistente precargado con los valores
    actuales).
    """
    settings_actual = settings.cargar()

    if settings_actual is None:
        settings_nuevo = asistente.ejecutar_asistente(raiz)
        if settings_nuevo is None:
            messagebox.showerror(
                "Configuracion requerida",
                "El programa necesita una configuracion para poder funcionar.\n"
                "Vuelva a ejecutarlo para completar el asistente."
            )
            raiz.destroy()
            sys.exit(1)
        return settings_nuevo

    if _preguntar_usar_anterior_o_modificar(raiz):
        return settings_actual

    settings_modificado = asistente.ejecutar_asistente(raiz, settings_existente=settings_actual)
    return settings_modificado if settings_modificado is not None else settings_actual


def main():
    raiz = tk.Tk()
    raiz.withdraw()  # no se muestra una ventana principal vacia, solo las de progreso/revision

    ruta_tesseract = ocr_engine.preparar_tesseract()
    if not ruta_tesseract:
        messagebox.showwarning(
            "Tesseract-OCR no encontrado",
            "No se encontro el motor de OCR (Tesseract) en este equipo.\n\n"
            "Vuelva a ejecutar 'ejecutar_1_instalar_dependencias.bat' para instalarlo, "
            "o instalelo manualmente.\n\nEl programa va a cerrarse."
        )
        raiz.destroy()
        sys.exit(1)

    almacenamiento.preparar_carpetas()
    aprendizaje.migrar_codigos_confirmados_desde_txt_viejo()
    aprendizaje.limpiar_codigos_confirmados_existentes()

    settings_actual = _obtener_settings(raiz)

    aprendizaje.sembrar_codigos_confirmados_desde_log(registro.leer_log())

    if not almacenamiento.carpeta_entrada_lista():
        messagebox.showinfo(
            "Carpeta PRUEBA creada",
            f"Se creo la carpeta:\n{CFG.carpeta_entrada}\n\n"
            "Coloque ahi los PDF (sueltos o combinados, segun la configuracion) "
            "y vuelva a ejecutar el programa."
        )
        raiz.destroy()
        sys.exit(0)

    archivos_pdf = almacenamiento.listar_pdfs(CFG.carpeta_entrada)
    total_ok = 0
    if archivos_pdf:
        items = _construir_items(archivos_pdf, settings_actual)
        if items:
            ventana_progreso = gui.VentanaProgreso(raiz, len(items))
            total_ok, _enviados_a_revisar = fase_1_automatica(items, ventana_progreso, settings_actual)
            ventana_progreso.destroy()

    total_manual_ok, total_omitidos = fase_2_manual(raiz, settings_actual)

    mostrar_resumen(total_ok, total_manual_ok, total_omitidos)
    raiz.destroy()


if __name__ == "__main__":
    main()
