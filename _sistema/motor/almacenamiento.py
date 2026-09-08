# -*- coding: utf-8 -*-
"""
almacenamiento.py
-------------------------------------------------------------------------
Todo lo que toca el disco: crear las carpetas que usa el programa, elegir
un nombre de archivo que no pise uno existente, y copiar el PDF ya
renombrado a su destino final.
-------------------------------------------------------------------------
"""

import shutil
from pathlib import Path

import pymupdf as fitz  # PyMuPDF

from .config import CFG


def preparar_carpetas():
    CFG.carpeta_proyecto.mkdir(parents=True, exist_ok=True)
    CFG.carpeta_por_revisar.mkdir(parents=True, exist_ok=True)
    CFG.carpeta_resultado_hoy.mkdir(parents=True, exist_ok=True)


def carpeta_entrada_lista() -> bool:
    """
    Devuelve True si la carpeta de entrada ya existia. Si no existia, la
    crea (para la proxima vez) y devuelve False, para que quien llama
    avise al usuario y detenga el proceso esta vez.
    """
    if CFG.carpeta_entrada.exists():
        return True
    CFG.carpeta_entrada.mkdir(parents=True, exist_ok=True)
    return False


def listar_pdfs(carpeta: Path):
    """Lista de PDFs en una carpeta (mayuscula o minuscula), sin duplicados, en orden."""
    archivos = list(carpeta.glob("*.pdf")) + list(carpeta.glob("*.PDF"))
    return sorted(set(archivos))


def nombre_disponible(carpeta: Path, nombre_base: str) -> str:
    """Evita sobreescribir si ya existe un archivo con ese nombre."""
    destino = carpeta / f"{nombre_base}.pdf"
    if not destino.exists():
        return destino.name
    contador = 2
    while (carpeta / f"{nombre_base} ({contador}).pdf").exists():
        contador += 1
    return f"{nombre_base} ({contador}).pdf"


def guardar_resultado(ruta_origen: Path, nombre_base: str) -> str:
    """
    Copia el PDF de origen COMPLETO (modo 'separados': el archivo ya es
    un solo documento) al destino final con el nombre resuelto. No se
    reconstruye con fitz -- para un documento que ya es un solo PDF no
    hay motivo para tocarlo, y evita alterar metadata sin necesidad.
    """
    nombre_final = nombre_disponible(CFG.carpeta_resultado_hoy, nombre_base)
    destino = CFG.carpeta_resultado_hoy / nombre_final
    shutil.copy2(ruta_origen, destino)  # copia (no borra el original de PRUEBA)
    return nombre_final


def _guardar_subconjunto_paginas_en(
    carpeta: Path, ruta_pdf_origen: Path, pagina_inicio: int, pagina_fin: int, nombre_base: str
) -> str:
    """
    Arma un PDF NUEVO con solo las paginas [pagina_inicio, pagina_fin]
    (0-based, inclusive) de "ruta_pdf_origen" y lo guarda en "carpeta"
    (evitando sobreescribir). Devuelve el nombre final (sin la carpeta).
    Usado tanto para guardar en RESULTADO como para materializar, en
    POR_REVISAR, cada documento logico de un PDF combinado que necesita
    revision manual -- por eso queda en su propio archivo independiente
    en vez de copiar el PDF combinado entero.
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre_final = nombre_disponible(carpeta, nombre_base)
    destino = carpeta / nombre_final

    documento_origen = fitz.open(ruta_pdf_origen)
    try:
        documento_nuevo = fitz.open()
        documento_nuevo.insert_pdf(documento_origen, from_page=pagina_inicio, to_page=pagina_fin)
        documento_nuevo.save(destino)
        documento_nuevo.close()
    finally:
        documento_origen.close()

    return nombre_final


def guardar_resultado_subconjunto_paginas(
    ruta_pdf_origen: Path, pagina_inicio: int, pagina_fin: int, nombre_base: str
) -> str:
    """Como guardar_resultado, pero para el modo 'juntos' (el PDF de origen tiene otros documentos ademas de este)."""
    return _guardar_subconjunto_paginas_en(
        CFG.carpeta_resultado_hoy, ruta_pdf_origen, pagina_inicio, pagina_fin, nombre_base
    )


def copiar_subconjunto_paginas_a_por_revisar(
    ruta_pdf_origen: Path, pagina_inicio: int, pagina_fin: int, nombre_base: str
) -> Path:
    """
    Igual que guardar_resultado_subconjunto_paginas, pero hacia
    POR_REVISAR: se usa cuando un documento logico (dentro de un PDF
    combinado) necesita revision manual, para que quede como su propio
    archivo independiente -- exactamente como si hubiera llegado suelto.
    """
    nombre_final = _guardar_subconjunto_paginas_en(
        CFG.carpeta_por_revisar, ruta_pdf_origen, pagina_inicio, pagina_fin, nombre_base
    )
    return CFG.carpeta_por_revisar / nombre_final


def copiar_a_por_revisar(ruta_pdf: Path) -> Path:
    destino = CFG.carpeta_por_revisar / ruta_pdf.name
    shutil.copy2(ruta_pdf, destino)
    return destino


def borrar_de_por_revisar(ruta_pdf: Path):
    ruta_pdf.unlink(missing_ok=True)
