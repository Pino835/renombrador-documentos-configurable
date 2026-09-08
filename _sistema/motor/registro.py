# -*- coding: utf-8 -*-
"""
registro.py
-------------------------------------------------------------------------
El "historial" del programa: un registro por cada archivo procesado
(automatico o manual), guardado en log_renombrador.json.

Mejora sobre la version 1: ademas del .json (que es el que el programa
realmente usa), se mantiene sincronizado un log_renombrador.csv de solo
lectura, para que se pueda abrir directo con doble clic en Excel sin que
nadie tenga que exportarlo a mano.

Con el motor de "zonas" un documento puede tener CUALQUIER combinacion de
campos, no solo cliente/factura. Para no perder compatibilidad con el
historial ya guardado (y con "aprendizaje.sembrar_codigos_confirmados_desde_log",
que lee la columna "cliente" directo), se mantienen "cliente"/"factura"
como columnas de siempre (pobladas cuando esas claves existen) y se
agrega "campos_extra" (JSON) para cualquier otro campo de formatos nuevos.
-------------------------------------------------------------------------
"""

import csv
import json
from datetime import datetime

from .config import CFG

CAMPOS = [
    "fecha_hora", "archivo_original", "archivo_nuevo", "cliente", "factura",
    "campos_extra", "metodo", "confianzas_por_campo", "estado",
]


def leer_log():
    """Devuelve la lista de registros del log, o [] si no existe o esta vacio/dañado."""
    if not CFG.log_path.exists():
        return []
    with open(CFG.log_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _escribir_json(registros):
    CFG.carpeta_proyecto.mkdir(parents=True, exist_ok=True)
    with open(CFG.log_path, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)


def _escribir_csv_sincronizado(registros):
    """
    Copia de solo lectura del mismo historial, en formato CSV, para
    abrir directo en Excel. El .json sigue siendo el que el programa lee
    y escribe; este .csv se regenera completo cada vez, no se edita a
    mano.
    """
    ruta_csv = CFG.log_path.with_suffix(".csv")
    with open(ruta_csv, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=CAMPOS)
        escritor.writeheader()
        for fila in registros:
            escritor.writerow({campo: fila.get(campo, "") for campo in CAMPOS})


def registrar(archivo_original, archivo_nuevo, campos: dict, metodo, estado,
              confianzas: dict = None):
    """
    "campos" es un diccionario {nombre_campo: valor} con TODOS los datos
    encontrados para ese documento (ej. {"cliente": "LTJ000", "factura":
    "CMER-004206462"}, o con formatos nuevos {"orden": "OC-1234", "cliente": "ABC"}).
    "confianzas" es un diccionario opcional {nombre_campo: confianza_pct} con la
    confianza individual del OCR por campo, util para diagnosticar por que un
    archivo fue a revision manual sin tener que reabrir el programa.
    """
    campos = campos or {}
    campos_extra = {nombre: valor for nombre, valor in campos.items() if nombre not in ("cliente", "factura")}

    registros = leer_log()
    registros.append({
        "fecha_hora": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
        "archivo_original": archivo_original,
        "archivo_nuevo": archivo_nuevo or "",
        "cliente": campos.get("cliente") or "",
        "factura": campos.get("factura") or "",
        "campos_extra": json.dumps(campos_extra, ensure_ascii=False) if campos_extra else "",
        "metodo": metodo,
        "confianzas_por_campo": json.dumps(
            {k: round(v, 1) for k, v in confianzas.items() if v is not None},
            ensure_ascii=False,
        ) if confianzas else "",
        "estado": estado,
    })
    _escribir_json(registros)
    _escribir_csv_sincronizado(registros)
