# -*- coding: utf-8 -*-
"""
aprendizaje.py
-------------------------------------------------------------------------
Maneja la lista de "valores ya confirmados a mano" -- ahora por CAMPO
(cliente, factura, orden, o cualquier otro que se configure), no solo
para el codigo de cliente como en la primera version -- y la usa para
corregir automaticamente confusiones tipicas del OCR (O/0, I/1) en
lecturas futuras del mismo valor.

Se guarda en "codigos_confirmados.json" = {"cliente": [...], "factura": [...], ...}.
La primera version de este proyecto (y la version 1 original) guardaban
un unico archivo de texto "codigos_cliente_confirmados.txt" con un solo
campo; "migrar_codigos_confirmados_desde_txt_viejo" trae ese historial
una sola vez bajo la clave "cliente" para no perderlo.

CORRECCION IMPORTANTE que se mantiene desde la iteracion anterior: se
encontraron entradas basura mezcladas con codigos reales en el archivo
viejo (fragmentos de GUID, simbolos sueltos) porque nunca se validaba la
forma del texto antes de guardarlo -- probablemente de un pegado
accidental. Esas entradas basura no solo ensucian el archivo: TAMBIEN
debilitan la correccion automatica, porque "corregir_con_lista_confirmados"
se niega a corregir cuando encuentra mas de un candidato parecido (para
no adivinar entre dos valores reales parecidos), y cada entrada basura de
mas es una oportunidad extra de que eso pase. Por eso se valida la forma
ANTES de guardar (ver "es_codigo_valido"), y se limpia una vez al iniciar
cualquier basura que ya hubiera quedado guardada de antes.
-------------------------------------------------------------------------
"""

import json
import re

from .config import CFG

# Forma que debe tener un valor confirmado para guardarse: empieza con
# letra o numero, y de ahi en adelante solo letras, numeros, guion, guion
# bajo o punto (separadores que si se ven en codigos reales) -- entre 2 y
# 20 caracteres en total.
_PATRON_CODIGO_VALIDO = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\-]{1,19}$')

# Un GUID/UUID (ej. "18CD235F-A89D-47CD-9B12-...") tiene la forma exacta
# de grupos hexadecimales de 8-4-4-4-12; si algo calza con esto NO es un
# codigo real aunque pase el patron de arriba.
_PATRON_GUID = re.compile(
    r'^[0-9A-Fa-f]{8}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4,12}$'
)


def es_codigo_valido(codigo: str) -> bool:
    if not codigo:
        return False
    codigo = codigo.strip()
    if "{" in codigo or "}" in codigo:
        return False
    if not _PATRON_CODIGO_VALIDO.match(codigo):
        return False
    if _PATRON_GUID.match(codigo):
        return False
    return True


def _cargar_todos() -> dict:
    """{"cliente": {...}, "factura": {...}, ...} -- valores como sets."""
    if not CFG.codigos_confirmados_json_path.exists():
        return {}
    try:
        with open(CFG.codigos_confirmados_json_path, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if not isinstance(datos, dict):
            return {}
        return {campo: set(valores) for campo, valores in datos.items()}
    except (json.JSONDecodeError, OSError):
        return {}


def _guardar_todos(todos: dict):
    CFG.carpeta_proyecto.mkdir(parents=True, exist_ok=True)
    serializable = {campo: sorted(valores) for campo, valores in todos.items() if valores}
    with open(CFG.codigos_confirmados_json_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


def cargar_codigos_confirmados(campo: str = "cliente") -> set:
    """Devuelve el conjunto de valores ya confirmados a mano para ese campo."""
    return _cargar_todos().get(campo, set())


def agregar_codigo_confirmado(codigo, campo: str = "cliente"):
    """Agrega un valor a los confirmados de "campo", si tiene forma valida y no estaba ya."""
    if not codigo:
        return
    codigo = codigo.strip()
    if not es_codigo_valido(codigo):
        print(f"AVISO: '{codigo}' no parece un valor valido para '{campo}'; no se guarda "
              "en la lista de confirmados (pero el documento SI se renombra normalmente).")
        return
    todos = _cargar_todos()
    actuales = todos.setdefault(campo, set())
    if codigo in actuales:
        return
    actuales.add(codigo)
    _guardar_todos(todos)


def migrar_codigos_confirmados_desde_txt_viejo():
    """
    Si existe el archivo viejo de un solo campo (version anterior) y
    todavia no se creo el nuevo multi-campo, se migra una sola vez bajo
    la clave "cliente" (que es lo unico que existia antes), validando
    forma igual que siempre.
    """
    if CFG.codigos_confirmados_json_path.exists():
        return
    if not CFG.codigos_confirmados_path.exists():
        return

    with open(CFG.codigos_confirmados_path, "r", encoding="utf-8") as f:
        codigos_viejos = {linea.strip() for linea in f if linea.strip()}
    validos = {c for c in codigos_viejos if es_codigo_valido(c)}
    if validos:
        _guardar_todos({"cliente": validos})
        print(f"Se migraron {len(validos)} valor(es) de 'cliente' desde "
              f"'{CFG.codigos_confirmados_path.name}' (version anterior) a "
              f"'{CFG.codigos_confirmados_json_path.name}'.")


def limpiar_codigos_confirmados_existentes():
    """
    Se corre una vez al iniciar el programa: para cada campo, si ya hay
    entradas con forma invalida (por edicion manual, o por datos migrados
    de una version anterior que no validaba), las quita y guarda un
    respaldo del archivo completo tal como estaba, para no perder
    informacion silenciosamente.
    """
    if not CFG.codigos_confirmados_json_path.exists():
        return

    todos = _cargar_todos()
    todos_limpios = {}
    total_invalidas = 0
    for campo, codigos in todos.items():
        validos = {c for c in codigos if es_codigo_valido(c)}
        total_invalidas += len(codigos - validos)
        todos_limpios[campo] = validos

    if total_invalidas == 0:
        return

    respaldo = CFG.codigos_confirmados_json_path.with_suffix(".respaldo_antes_de_limpiar.json")
    if not respaldo.exists():
        with open(respaldo, "w", encoding="utf-8") as f:
            json.dump({campo: sorted(codigos) for campo, codigos in todos.items()}, f,
                      ensure_ascii=False, indent=2)

    _guardar_todos(todos_limpios)
    print(f"AVISO: se quitaron {total_invalidas} entrada(s) sin forma de codigo valido de "
          f"'{CFG.codigos_confirmados_json_path.name}' (ej. texto pegado por error, no codigos "
          f"reales). Se guardo una copia del archivo original en '{respaldo.name}' por si acaso.")


def sembrar_codigos_confirmados_desde_log(filas_log, campo: str = "cliente", clave_log: str = "cliente"):
    """
    La primera vez que se usa esta funcion (todavia no existe NINGUN
    archivo de codigos confirmados), se aprovechan las correcciones
    manuales que ya quedaron guardadas en ejecuciones anteriores del log,
    en vez de empezar la lista desde cero. Solo se siembran las que
    tengan forma valida de codigo.
    """
    if CFG.codigos_confirmados_json_path.exists() or CFG.codigos_confirmados_path.exists():
        return
    codigos = set()
    for fila in filas_log:
        if fila.get("metodo") == "manual" and fila.get("estado") == "OK" and fila.get(clave_log):
            candidato = fila[clave_log].strip()
            if es_codigo_valido(candidato):
                codigos.add(candidato)
    if codigos:
        todos = _cargar_todos()
        todos.setdefault(campo, set()).update(codigos)
        _guardar_todos(todos)


# Unicos caracteres que se permite insertar/quitar/sustituir "gratis" al
# comparar contra la lista de confirmados. Con una lista grande, permitir
# CUALQUIER sustitucion de un solo caracter es peligroso: por ejemplo,
# "JAS003" (bien leido) esta a una sola letra de "AAS003" (otro valor
# real), y con una distancia de edicion normal se "corregiria" al valor
# equivocado. Por eso solo se permiten, a costo cero, los cambios que
# sabemos que comete el OCR en este tipo de codigos.
_EQUIVALENTES_OCR = {("O", "0"), ("0", "O"), ("I", "1"), ("1", "I")}
_CARACTERES_AMBIGUOS_OCR = {"O", "0", "I", "1"}


def _distancia_restringida(a, b):
    """
    Como una distancia de edicion, pero SOLO permite (a costo 0) los
    cambios tipicos de la confusion O/0 e I/1 del OCR -- insertar, quitar
    o sustituir unicamente esos caracteres. Cualquier otro cambio cuesta
    "infinito" (no esta permitido). Si el resultado es 0, "a" y "b" son
    el mismo valor, solo que con esas confusiones tipicas de por medio.
    """
    a, b = a.upper(), b.upper()
    m, n = len(a), len(b)
    INFINITO = float("inf")

    def costo_insertar_o_quitar(caracter):
        return 0 if caracter in _CARACTERES_AMBIGUOS_OCR else INFINITO

    def costo_sustituir(ca, cb):
        if ca == cb or (ca, cb) in _EQUIVALENTES_OCR:
            return 0
        return INFINITO

    fila_anterior = [0] * (n + 1)
    for j in range(1, n + 1):
        fila_anterior[j] = fila_anterior[j - 1] + costo_insertar_o_quitar(b[j - 1])

    for i in range(1, m + 1):
        fila_actual = [fila_anterior[0] + costo_insertar_o_quitar(a[i - 1])] + [0] * n
        for j in range(1, n + 1):
            fila_actual[j] = min(
                fila_anterior[j] + costo_insertar_o_quitar(a[i - 1]),      # quitar de "a"
                fila_actual[j - 1] + costo_insertar_o_quitar(b[j - 1]),    # falta en "a"
                fila_anterior[j - 1] + costo_sustituir(a[i - 1], b[j - 1]),
            )
        fila_anterior = fila_actual

    return fila_anterior[n]


def corregir_con_lista_confirmados(valor, codigos_confirmados):
    """
    Si "valor" (lo que leyo el OCR) es el MISMO valor que uno ya
    confirmado a mano antes para ese campo, solo que con una confusion
    tipica de O/0 o I/1 de por medio, se corrige a ese valor confirmado.
    No corrige ante cualquier otra diferencia, ni si hay dos valores
    confirmados que calzan igual (para no adivinar entre dos valores
    reales parecidos). Devuelve (valor_final, se_corrigio).
    """
    if not valor or not codigos_confirmados:
        return valor, False
    if valor in codigos_confirmados:
        return valor, False

    candidatos = [codigo for codigo in codigos_confirmados if _distancia_restringida(valor, codigo) == 0]
    if len(candidatos) != 1:
        return valor, False  # ninguno calza, o hay mas de uno: no se adivina

    return candidatos[0], True
