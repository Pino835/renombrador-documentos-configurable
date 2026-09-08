# -*- coding: utf-8 -*-
"""
settings.py
-------------------------------------------------------------------------
Modelo de "settings.json": el DOCUMENTO que el programa va a procesar --
como vienen los archivos (sueltos o combinados, y como separarlos), que
formato(s) de factura existen y donde estan sus datos (por patrones de
texto -motor "clasico"- o por zonas de la hoja -motor "zonas"-), y el
patron del nombre de archivo final.

Es un archivo NUEVO y separado de "config.json": config.json se queda con
lo que es puramente de infraestructura (carpetas, dpi, idioma del OCR,
umbral de confianza), cosas que casi nunca cambian. settings.json es lo
que cambia cada vez que se configura un cliente/documento distinto, y por
eso se arma con el asistente (ver asistente.py) en vez de editarse a
mano.

Se modela con dataclasses + funciones to_dict/from_dict escritas a mano
(sin agregar pydantic ni ninguna dependencia nueva).
-------------------------------------------------------------------------
"""

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

from .config import CFG, limpiar_texto_extraido

VERSION_ACTUAL = 1


def _settings_path():
    """
    Se resuelve contra CFG.carpeta_proyecto en cada llamada (no como una
    constante fija calculada una sola vez al importar el modulo) para ser
    consistente con el resto del proyecto (almacenamiento.py, registro.py,
    aprendizaje.py hacen lo mismo) y para que las pruebas puedan redirigir
    CFG.carpeta_proyecto sin que este modulo "se quede" con la ruta vieja.
    """
    return CFG.carpeta_proyecto / "settings.json"

# Valores del motor "clasico", identicos a los que trae el programa desde
# su version anterior (antes vivian sueltos en config.json). Sirven de
# respaldo si config.json ya no los tiene, y como base del atajo "usar
# plantilla clasica" del asistente.
_CLASICO_PATRONES_FACTURA = [r"CMER[\s\-]{0,2}([A-Za-z0-9]{3,15})"]
_CLASICO_PREFIJO_FACTURA = "CMER-"
_CLASICO_ETIQUETAS_FACTURA_RESPALDO = [r"Factura\s*[:\-]?"]
_CLASICO_ETIQUETAS_CLIENTE = [
    r"(?:C[oóeé0]d\.?\s*(?:de\s*)?Cliente|Cliente\s*(?:No\.?|N[°º]|#))\s*[:\-]?"
]
_CLASICO_LIMITE_SUPERIOR_RATIO = 0.5


@dataclass
class ReglasClasicas:
    """Lo mismo que antes vivia suelto en config.json, para el motor 'clasico'."""
    patrones_factura: list
    prefijo_factura_normalizado: str
    etiquetas_factura_respaldo: list
    etiquetas_cliente: list
    limite_superior_ratio: float

    @staticmethod
    def from_dict(d):
        return ReglasClasicas(
            patrones_factura=list(d.get("patrones_factura", _CLASICO_PATRONES_FACTURA)),
            prefijo_factura_normalizado=d.get("prefijo_factura_normalizado", _CLASICO_PREFIJO_FACTURA),
            etiquetas_factura_respaldo=list(
                d.get("etiquetas_factura_respaldo", _CLASICO_ETIQUETAS_FACTURA_RESPALDO)
            ),
            etiquetas_cliente=list(d.get("etiquetas_cliente", _CLASICO_ETIQUETAS_CLIENTE)),
            limite_superior_ratio=float(d.get("limite_superior_ratio", _CLASICO_LIMITE_SUPERIOR_RATIO)),
        )


@dataclass
class Campo:
    """
    Un dato a extraer (ej. "cliente", "factura", "orden"). En el motor
    "zonas", se busca dentro de "zonas" (rectangulos fraccionarios 0..1
    de la pagina, probados en ese orden -- igual que ya hacia
    CFG.patrones_factura con varios patrones). El valor encontrado debe
    cumplir "patron_validacion" para aceptarse.
    """
    nombre: str
    zonas: list  # lista de (x0, y0, x1, y1) fraccionarios
    patron_validacion: str
    patron_amigable: Optional[str] = None
    etiqueta: Optional[str] = None  # texto que precede al valor en el doc (ej. "BENEFICIARIO")
    pagina: int = 0  # pagina DENTRO del documento logico (0 = primera)
    obligatorio: bool = True
    mayusculas_forzadas: bool = True
    conversiones: list = field(default_factory=list)  # [{"entrada": "...", "salida": "..."}]
    longitud_minima: Optional[int] = None  # si esta definido, rechaza valores mas cortos

    @staticmethod
    def from_dict(d):
        lmin = d.get("longitud_minima")
        campo = Campo(
            nombre=d["nombre"],
            zonas=[tuple(z) for z in d.get("zonas", [])],
            patron_validacion=d.get("patron_validacion", ".+"),
            patron_amigable=d.get("patron_amigable"),
            etiqueta=d.get("etiqueta") or None,
            pagina=int(d.get("pagina", 0)),
            obligatorio=bool(d.get("obligatorio", True)),
            mayusculas_forzadas=bool(d.get("mayusculas_forzadas", True)),
            conversiones=list(d.get("conversiones", [])),
            longitud_minima=int(lmin) if lmin is not None else None,
        )
        # El patron_amigable, si existe, es la fuente de verdad: se
        # regenera el regex a partir de el en vez de confiar en que
        # quedaron sincronizados (por si alguien edito el JSON a mano).
        if campo.patron_amigable:
            campo.patron_validacion = traducir_patron_amigable(campo.patron_amigable)
        return campo

    def to_dict(self):
        return {
            "nombre": self.nombre,
            "zonas": [list(z) for z in self.zonas],
            "patron_validacion": self.patron_validacion,
            "patron_amigable": self.patron_amigable,
            "etiqueta": self.etiqueta,
            "pagina": self.pagina,
            "obligatorio": self.obligatorio,
            "mayusculas_forzadas": self.mayusculas_forzadas,
            "conversiones": self.conversiones,
            "longitud_minima": self.longitud_minima,
        }


@dataclass
class Formato:
    """
    Una "plantilla" de documento: motor "clasico" (patrones/etiquetas de
    texto en toda la pagina, el comportamiento de siempre) o "zonas"
    (campos ubicados por recorte de la pagina). Si hay varios formatos
    configurados, "texto_identificador" (opcional) permite reconocer cual
    aplica sin tener que probarlos todos.
    """
    nombre: str
    motor: str  # "clasico" | "zonas"
    patron_nombre_archivo: Optional[str] = None  # si es None, se usa el global de Settings
    texto_identificador: Optional[str] = None
    campos: list = field(default_factory=list)  # list[Campo], usado si motor == "zonas"
    reglas_clasicas: Optional[ReglasClasicas] = None  # usado si motor == "clasico"
    orientacion: str = "vertical"
    filas_cuadricula: int = 6
    columnas_cuadricula: int = 4

    @staticmethod
    def from_dict(d):
        return Formato(
            nombre=d["nombre"],
            motor=d.get("motor", "clasico"),
            patron_nombre_archivo=d.get("patron_nombre_archivo"),
            texto_identificador=d.get("texto_identificador"),
            campos=[Campo.from_dict(c) for c in d.get("campos", [])],
            reglas_clasicas=(
                ReglasClasicas.from_dict(d["reglas_clasicas"]) if d.get("reglas_clasicas") else None
            ),
            orientacion=d.get("orientacion", "vertical"),
            filas_cuadricula=int(d.get("filas_cuadricula", 6)),
            columnas_cuadricula=int(d.get("columnas_cuadricula", 4)),
        )

    def to_dict(self):
        return {
            "nombre": self.nombre,
            "motor": self.motor,
            "patron_nombre_archivo": self.patron_nombre_archivo,
            "texto_identificador": self.texto_identificador,
            "campos": [c.to_dict() for c in self.campos],
            "reglas_clasicas": asdict(self.reglas_clasicas) if self.reglas_clasicas else None,
            "orientacion": self.orientacion,
            "filas_cuadricula": self.filas_cuadricula,
            "columnas_cuadricula": self.columnas_cuadricula,
        }


@dataclass
class ModoEntrada:
    """Como vienen los PDF de entrada: sueltos, o varios documentos combinados en uno solo."""
    tipo: str = "separados"  # "separados" | "juntos"
    modo_division: str = "paginas_fijas"  # "paginas_fijas" | "patron" (solo aplica si tipo == "juntos")
    paginas_por_documento: Optional[int] = 1
    patron_inicio: Optional[str] = None
    patron_fin: Optional[str] = None

    @staticmethod
    def from_dict(d):
        return ModoEntrada(
            tipo=d.get("tipo", "separados"),
            modo_division=d.get("modo_division", "paginas_fijas"),
            paginas_por_documento=d.get("paginas_por_documento", 1),
            patron_inicio=d.get("patron_inicio"),
            patron_fin=d.get("patron_fin"),
        )

    def to_dict(self):
        return asdict(self)


@dataclass
class Settings:
    modo_entrada: ModoEntrada
    formatos: list  # list[Formato]
    patron_nombre_archivo: str = "{cliente}-{factura}"
    version: int = VERSION_ACTUAL

    @staticmethod
    def from_dict(d):
        return Settings(
            modo_entrada=ModoEntrada.from_dict(d.get("modo_entrada", {})),
            formatos=[Formato.from_dict(f) for f in d.get("formatos", [])],
            patron_nombre_archivo=d.get("patron_nombre_archivo", "{cliente}-{factura}"),
            version=int(d.get("version", VERSION_ACTUAL)),
        )

    def to_dict(self):
        return {
            "version": self.version,
            "modo_entrada": self.modo_entrada.to_dict(),
            "formatos": [f.to_dict() for f in self.formatos],
            "patron_nombre_archivo": self.patron_nombre_archivo,
        }


def existe() -> bool:
    return _settings_path().exists()


def cargar() -> Optional[Settings]:
    """Devuelve el Settings guardado, o None si no existe o quedo dañado (nunca lanza excepcion)."""
    ruta = _settings_path()
    if not ruta.exists():
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return Settings.from_dict(datos)
    except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"ADVERTENCIA: no se pudo leer settings.json ({error}); se va a pedir configurar de nuevo.")
        return None


def guardar(settings: Settings):
    ruta = _settings_path()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(settings.to_dict(), f, ensure_ascii=False, indent=2)


def _leer_config_json_crudo():
    """
    Lee config.json tal cual, en JSON crudo (no los valores ya
    compilados/resueltos de CFG), para poder armar ReglasClasicas con el
    mismo texto de patrones que config.json tiene guardado. Si el archivo
    no existe o esta incompleto, se usan los valores de respaldo de este
    modulo (identicos a los que ya trae CFG por defecto).
    """
    ruta = CFG.carpeta_proyecto / "config.json"
    if not ruta.exists():
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def settings_por_defecto_clasico() -> Settings:
    """
    Fabrica el Settings equivalente al comportamiento de la version
    anterior del programa: un unico Formato con motor="clasico", con las
    reglas que antes vivian sueltas en config.json (o los valores de
    respaldo de este modulo). Es lo que arma el asistente cuando se elige
    "usar la plantilla clasica ya armada".
    """
    crudo = _leer_config_json_crudo()
    reglas = ReglasClasicas(
        patrones_factura=list(crudo.get("patrones_factura", _CLASICO_PATRONES_FACTURA)),
        prefijo_factura_normalizado=crudo.get("prefijo_factura_normalizado", _CLASICO_PREFIJO_FACTURA),
        etiquetas_factura_respaldo=list(
            crudo.get("etiquetas_factura_respaldo", _CLASICO_ETIQUETAS_FACTURA_RESPALDO)
        ),
        etiquetas_cliente=list(crudo.get("etiquetas_cliente", _CLASICO_ETIQUETAS_CLIENTE)),
        limite_superior_ratio=float(crudo.get("limite_superior_ratio", _CLASICO_LIMITE_SUPERIOR_RATIO)),
    )
    formato = Formato(
        nombre="Plantilla clasica (CMER)",
        motor="clasico",
        patron_nombre_archivo="{cliente}-{factura}",
        reglas_clasicas=reglas,
    )
    return Settings(
        modo_entrada=ModoEntrada(tipo="separados", modo_division="paginas_fijas", paginas_por_documento=1),
        formatos=[formato],
        patron_nombre_archivo="{cliente}-{factura}",
    )


# =========================================================================
# Patrones "amigables" (ej. "LLL-NNNN") y composicion del nombre de archivo
# =========================================================================

_TOKENS_PATRON_AMIGABLE = {"L": "[A-Za-z]", "N": r"\d", "A": "[A-Za-z0-9]"}


def traducir_patron_amigable(patron: str) -> str:
    """
    Traduce una notacion simple a una expresion regular de Python:
      L = una letra, N = un digito, A = alfanumerico.
      Repetir el mismo caracter pide esa cantidad exacta
        (ej. "LLL" = exactamente 3 letras).
      "+" despues de L/N/A pide "una o mas" de ese tipo.
      "{n,}" despues de L/N/A pide "n o mas" de ese tipo.
      "{n,m}" despues de L/N/A pide entre n y m de ese tipo.
      Cualquier otro caracter se toma literal (ej. el "-" de "LLL-NNNN").
    Ejemplos:
      "LLL-NNNN"  -> tres letras, guion, cuatro numeros.
      "OC-NNNN"   -> literalmente "OC-" seguido de cuatro numeros.
      "A{6,}"     -> seis o mas caracteres alfanumericos.
      "L{2,5}"    -> entre dos y cinco letras.
    Si el patron empieza con "regex:", el resto se usa tal cual como
    expresion regular de Python (para quien prefiera escribirla directo
    -- asi se representa tambien el patron CMER clasico sin inventar
    sintaxis nueva para ese caso).
    """
    if patron.startswith("regex:"):
        return patron[len("regex:"):]

    salida = []
    i = 0
    while i < len(patron):
        caracter = patron[i]
        if caracter in _TOKENS_PATRON_AMIGABLE:
            clase = _TOKENS_PATRON_AMIGABLE[caracter]
            # {n,} o {n,m}: minimo con o sin maximo
            if i + 1 < len(patron) and patron[i + 1] == "{":
                m = re.match(r"\{(\d+),(\d*)\}", patron[i + 1:])
                if m:
                    n, max_val = m.group(1), m.group(2)
                    salida.append(f"{clase}{{{n},{max_val}}}" if max_val else f"{clase}{{{n},}}")
                    i += 1 + len(m.group(0))
                    continue
            # + : uno o mas
            if i + 1 < len(patron) and patron[i + 1] == "+":
                salida.append(clase + "+")
                i += 2
                continue
            # repeticion exacta: contar consecutivos del mismo tipo
            j = i
            while j < len(patron) and patron[j] == caracter:
                j += 1
            cantidad = j - i
            salida.append(clase + (f"{{{cantidad}}}" if cantidad > 1 else ""))
            i = j
            continue
        salida.append(re.escape(caracter))
        i += 1

    return "^" + "".join(salida) + "$"


def aplicar_conversiones(valor: str, conversiones: list) -> str:
    """
    Aplica las reglas de conversion al valor extraido. Cada regla es un
    dict {"entrada": "...", "salida": "..."}: si el texto extraido CONTIENE
    la cadena "entrada" (sin distincion de mayusculas), se devuelve "salida"
    completo en su lugar. Se aplica la PRIMERA regla que coincida; si ninguna
    coincide, el valor original no cambia.

    Ejemplo: entrada="Banco de Costa Rica", salida="BCR" -- si el OCR lee
    "Banco de Costa Rica S.A.", se guarda "BCR".
    """
    if not valor or not conversiones:
        return valor
    valor_lower = valor.lower()
    for regla in conversiones:
        entrada = regla.get("entrada", "")
        salida = regla.get("salida", "")
        if entrada and entrada.lower() in valor_lower:
            return salida
    return valor


def valor_cumple_patron(valor: Optional[str], patron_validacion: str) -> bool:
    """
    True si "valor" cumple la expresion regular "patron_validacion"
    (comparacion sin distinguir mayusculas/minusculas). Se usa tanto al
    aceptar una lectura automatica como al revisar una correccion manual
    -- en ambos casos queremos saber si el texto "tiene forma" de lo que
    se esperaba antes de darlo por bueno.
    """
    if not valor:
        return False
    try:
        return re.search(patron_validacion, valor, re.IGNORECASE) is not None
    except re.error:
        return False


def construir_nombre_archivo(patron: str, valores: dict) -> str:
    """
    Arma el nombre final combinando los valores de los campos segun el
    patron configurado (ej. "{cliente}-{factura}"). Lanza KeyError si
    falta algun campo que el patron necesita -- quien llama debe
    atraparlo y mandar el documento a revision manual en vez de dejar
    que el programa reviente.
    """
    nombre = patron.format(**valores)
    return limpiar_texto_extraido(nombre)
