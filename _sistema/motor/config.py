# -*- coding: utf-8 -*-
"""
config.py
-------------------------------------------------------------------------
Un solo lugar para todo lo "ajustable" del programa: rutas de carpetas,
umbrales del OCR y los patrones (regex) que identifican el codigo de
cliente y el numero de factura.

Antes (version 1) estos valores estaban como constantes sueltas dentro de
"renombrador.py", mezclados con la logica. Aqui viven en "config.json"
(se puede editar con el Bloc de notas, sin tocar codigo) y este modulo
solo se encarga de leerlo, validarlo y resolver las rutas absolutas.

Si "config.json" no existe o tiene un problema, se usan estos mismos
valores como respaldo (para que el programa nunca quede sin poder
arrancar solo por un config.json mal editado).
-------------------------------------------------------------------------
"""

import json
import re
from pathlib import Path
from datetime import datetime

# _sistema/motor/config.py  →  _sistema/ es CARPETA_SISTEMA, su padre es CARPETA_PROYECTO
CARPETA_SISTEMA  = Path(__file__).resolve().parent.parent   # …/_sistema/
CARPETA_PROYECTO = CARPETA_SISTEMA.parent                    # raiz del proyecto
CONFIG_PATH = CARPETA_SISTEMA / "config.json"

_VALORES_POR_DEFECTO = {
    "carpetas": {
        "entrada": "PRUEBA",
        "por_revisar": "POR_REVISAR",
        "resultado": "RESULTADO",
    },
    "ocr": {
        "idiomas": "spa+eng",
        "dpi_render": 300,
        "umbral_confianza_minima": 80.0,
    },
    "patrones_factura": [
        r"CMER[\s\-]{0,2}([A-Za-z0-9]{3,15})",
    ],
    "prefijo_factura_normalizado": "CMER-",
    "etiquetas_factura_respaldo": [
        r"Factura\s*[:\-]?",
    ],
    "etiquetas_cliente": [
        r"(?:C[oóeé0]d\.?\s*(?:de\s*)?Cliente|Cliente\s*(?:No\.?|N[°º]|#))\s*[:\-]?",
    ],
    "limite_superior_ratio": 0.5,
}


def _cargar_json_config():
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except (json.JSONDecodeError, OSError):
        # Un config.json mal editado no debe tumbar el programa: se avisa
        # y se sigue con los valores por defecto.
        print("ADVERTENCIA: no se pudo leer config.json (¿quedo mal editado?).")
        print("Se van a usar los valores por defecto mientras tanto.")
        return {}


def _compilar_lista_regex(lista_textos, nombre_campo):
    """Compila cada texto de la lista como regex; ignora los que no compilen (con aviso)."""
    compilados = []
    for texto in lista_textos:
        try:
            compilados.append(re.compile(texto, re.IGNORECASE))
        except re.error as error:
            print(f"ADVERTENCIA: el patron '{texto}' de '{nombre_campo}' en config.json "
                  f"no es una expresion regular valida ({error}); se ignora.")
    return compilados


class Configuracion:
    """Agrupa toda la configuracion ya resuelta y lista para usar."""

    def __init__(self):
        datos = _VALORES_POR_DEFECTO.copy()
        datos.update(_cargar_json_config())

        carpetas = {**_VALORES_POR_DEFECTO["carpetas"], **datos.get("carpetas", {})}
        ocr = {**_VALORES_POR_DEFECTO["ocr"], **datos.get("ocr", {})}

        self.carpeta_entrada     = CARPETA_PROYECTO / carpetas["entrada"]
        self.carpeta_por_revisar = CARPETA_PROYECTO / carpetas["por_revisar"]
        self.carpeta_resultado   = CARPETA_PROYECTO / carpetas["resultado"]
        self.carpeta_proyecto    = CARPETA_SISTEMA

        fecha_hoy = datetime.now().strftime("%d-%m-%Y")
        self.carpeta_resultado_hoy = self.carpeta_resultado / fecha_hoy

        self.log_path = self.carpeta_proyecto / "log_renombrador.json"
        # Nombre viejo (version 1, un solo campo "cliente"): se conserva
        # solo para poder migrarlo una vez a codigos_confirmados_json_path.
        self.codigos_confirmados_path = self.carpeta_proyecto / "codigos_cliente_confirmados.txt"
        self.codigos_confirmados_json_path = self.carpeta_proyecto / "codigos_confirmados.json"

        self.idiomas_ocr = ocr["idiomas"]
        self.dpi_render = int(ocr["dpi_render"])
        self.umbral_confianza_minima = float(ocr["umbral_confianza_minima"])

        self.prefijo_factura_normalizado = datos.get(
            "prefijo_factura_normalizado", _VALORES_POR_DEFECTO["prefijo_factura_normalizado"]
        )
        self.limite_superior_ratio = float(
            datos.get("limite_superior_ratio", _VALORES_POR_DEFECTO["limite_superior_ratio"])
        )

        self.patrones_factura = _compilar_lista_regex(
            datos.get("patrones_factura", _VALORES_POR_DEFECTO["patrones_factura"]),
            "patrones_factura",
        )
        self.etiquetas_factura_respaldo = _compilar_lista_regex(
            datos.get("etiquetas_factura_respaldo", _VALORES_POR_DEFECTO["etiquetas_factura_respaldo"]),
            "etiquetas_factura_respaldo",
        )
        self.etiquetas_cliente = _compilar_lista_regex(
            datos.get("etiquetas_cliente", _VALORES_POR_DEFECTO["etiquetas_cliente"]),
            "etiquetas_cliente",
        )

        if not self.patrones_factura and not self.etiquetas_factura_respaldo:
            raise ValueError(
                "config.json quedo sin ningun patron valido para reconocer la factura "
                "('patrones_factura' y 'etiquetas_factura_respaldo' estan vacios o mal escritos)."
            )


CARACTERES_INVALIDOS = re.compile(r'[\\/:*?"<>|]')


def limpiar_texto_extraido(valor: str) -> str:
    """Deja el valor extraido listo para usarse en un nombre de archivo."""
    valor = valor.strip()
    valor = CARACTERES_INVALIDOS.sub("", valor)
    return valor


# Una unica instancia compartida por todo el programa (se crea al importar
# este modulo la primera vez).
CFG = Configuracion()
