# -*- coding: utf-8 -*-
"""
asistente.py
-------------------------------------------------------------------------
Asistente de configuracion (wizard) de Tkinter. Se abre:
  - OBLIGATORIO, la primera vez que se usa el programa (no existe
    settings.json todavia).
  - A pedido, cuando el usuario elige "Modificar configuracion" en vez de
    "usar la configuracion anterior" (ver main.py).

Pasos:
  0) Atajo: "usar la plantilla clasica ya armada" (CMER-XXXXXXX + Cod.
     Cliente, el comportamiento de siempre) vs "configurar desde cero".
  1) Como vienen los documentos: sueltos, o combinados (con cantidad fija
     de paginas, o por patron de inicio/fin).
  2) Un solo formato, o varios formatos distintos.
  3) Por cada formato: imagen de muestra (opcional), cuadricula ajustable
     (ver selector_zonas.py), campos (nombre, patron esperado, pagina,
     obligatorio) y sus zonas.
  4) Patron del nombre de archivo final (combinando los campos).
  5) Resumen y guardar.

Simplificacion deliberada (para no disparar el alcance de esta pantalla):
la zona de un campo se marca SIEMPRE sobre la MISMA imagen de muestra
cargada para el formato, sin importar en que pagina del documento
aparezca ese campo (Campo.pagina) -- se asume que las paginas de un mismo
documento tienen tamaño de hoja parecido. Si eso no alcanza para algun
caso real, se puede ajustar "a mano" editando settings.json.
-------------------------------------------------------------------------
"""

import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image

from . import ocr_engine
from . import preprocesamiento
from . import settings as settings_mod
from .config import CFG
from .selector_zonas import SelectorZonas

PLACEHOLDER_VERTICAL = (850, 1100)
PLACEHOLDER_HORIZONTAL = (1100, 850)


# =========================================================================
# Dialogo pequeno: agregar/editar un campo
# =========================================================================

class _DialogoCampo(tk.Toplevel):
    def __init__(self, master, campo_existente=None):
        super().__init__(master)
        self.title("Campo a extraer")
        self.resizable(False, False)
        self.resultado = None

        contenedor = ttk.Frame(self, padding=14)
        contenedor.pack()

        ttk.Label(contenedor, text="Nombre del campo (ej. cliente, factura, orden):").grid(
            row=0, column=0, sticky="w"
        )
        self.entry_nombre = ttk.Entry(contenedor, width=32)
        self.entry_nombre.grid(row=1, column=0, pady=(0, 10), sticky="w")

        ttk.Label(contenedor, text="Patron esperado (ej. LLL-NNNN, OC-NNNN):").grid(
            row=2, column=0, sticky="w"
        )
        self.entry_patron = ttk.Entry(contenedor, width=32)
        self.entry_patron.grid(row=3, column=0, pady=(0, 2), sticky="w")
        ttk.Label(
            contenedor,
            text="L=letra   N=numero   A=alfanumerico   (repetir = cantidad exacta, ej. LLL = 3 letras)\n"
                 "Deje vacio para aceptar cualquier texto, o escriba 'regex:...' para una expresion regular.",
            foreground="#777777", font=("Segoe UI", 8), justify="left",
        ).grid(row=4, column=0, sticky="w", pady=(0, 10))

        ttk.Label(contenedor, text="Etiqueta de texto (opcional):").grid(
            row=5, column=0, sticky="w"
        )
        self.entry_etiqueta = ttk.Entry(contenedor, width=32)
        self.entry_etiqueta.grid(row=6, column=0, pady=(0, 2), sticky="w")
        ttk.Label(
            contenedor,
            text="Texto que aparece antes del dato en el documento (ej. BENEFICIARIO, BANCO:).\n"
                 "El programa lo buscara en toda la pagina, sin depender de coordenadas fijas.\n"
                 "Util para documentos escaneados que pueden estar desplazados.",
            foreground="#777777", font=("Segoe UI", 8), justify="left",
        ).grid(row=7, column=0, sticky="w", pady=(0, 10))

        ttk.Label(contenedor, text="Pagina del documento donde aparece (1 = primera):").grid(
            row=8, column=0, sticky="w"
        )
        self.spin_pagina = ttk.Spinbox(contenedor, from_=1, to=20, width=6)
        self.spin_pagina.delete(0, "end")
        self.spin_pagina.insert(0, "1")
        self.spin_pagina.grid(row=9, column=0, sticky="w", pady=(0, 10))

        self.var_obligatorio = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            contenedor, text="Obligatorio (si falta, el documento va a revision manual)",
            variable=self.var_obligatorio,
        ).grid(row=10, column=0, sticky="w", pady=(0, 10))

        ttk.Label(contenedor, text="Longitud minima del valor (0 = sin limite):").grid(
            row=11, column=0, sticky="w"
        )
        self.spin_longitud = ttk.Spinbox(contenedor, from_=0, to=100, width=6)
        self.spin_longitud.delete(0, "end")
        self.spin_longitud.insert(0, "0")
        self.spin_longitud.grid(row=12, column=0, sticky="w", pady=(0, 10))

        self._editando_nombre_existente = campo_existente is not None
        if campo_existente:
            self.entry_nombre.insert(0, campo_existente["nombre"])
            self.entry_nombre.configure(state="disabled")  # no se renombra: lo referencia el patron de nombre de archivo
            self.entry_patron.insert(0, campo_existente.get("patron_amigable") or "")
            self.entry_etiqueta.insert(0, campo_existente.get("etiqueta") or "")
            self.spin_pagina.delete(0, "end")
            self.spin_pagina.insert(0, str(campo_existente.get("pagina", 0) + 1))
            self.var_obligatorio.set(campo_existente.get("obligatorio", True))
            self.spin_longitud.delete(0, "end")
            self.spin_longitud.insert(0, str(campo_existente.get("longitud_minima") or 0))

        self.mensaje_error = ttk.Label(contenedor, text="", foreground="red", wraplength=320)
        self.mensaje_error.grid(row=13, column=0, sticky="w")

        fila_botones = ttk.Frame(contenedor)
        fila_botones.grid(row=14, column=0, pady=(10, 0))
        ttk.Button(fila_botones, text="Cancelar", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(fila_botones, text="Guardar", command=self._on_guardar).pack(side="left", padx=4)

        self.grab_set()
        self.entry_nombre.focus_set()

    def _on_guardar(self):
        nombre = self.entry_nombre.get().strip().lower().replace(" ", "_") if not self._editando_nombre_existente \
            else self.entry_nombre.get().strip()
        patron_amigable = self.entry_patron.get().strip() or None
        etiqueta = self.entry_etiqueta.get().strip() or None
        try:
            pagina = max(0, int(self.spin_pagina.get()) - 1)
        except ValueError:
            pagina = 0
        try:
            longitud_minima = int(self.spin_longitud.get())
            longitud_minima = longitud_minima if longitud_minima > 0 else None
        except ValueError:
            longitud_minima = None

        if not nombre:
            self.mensaje_error.config(text="El nombre del campo es obligatorio.")
            return
        if not re.match(r'^[a-z][a-z0-9_]*$', nombre):
            self.mensaje_error.config(text="Use solo letras minusculas, numeros y guion bajo, empezando con una letra.")
            return

        patron_validacion = settings_mod.traducir_patron_amigable(patron_amigable) if patron_amigable else ".+"
        try:
            re.compile(patron_validacion)
        except re.error:
            self.mensaje_error.config(text="Ese patron no resulto ser una expresion regular valida.")
            return

        # "zonas" no se incluye aqui: quien llama a este dialogo decide que
        # hacer con las zonas (un campo nuevo arranca sin ninguna; uno que
        # ya existia conserva las que tenia).
        self.resultado = {
            "nombre": nombre,
            "patron_amigable": patron_amigable,
            "patron_validacion": patron_validacion,
            "etiqueta": etiqueta,
            "pagina": pagina,
            "obligatorio": self.var_obligatorio.get(),
            "longitud_minima": longitud_minima,
        }
        self.destroy()


# =========================================================================
# Dialogo de conversiones de un campo
# =========================================================================

class _DialogoConversiones(tk.Toplevel):
    """
    Tabla de reglas de conversion para un campo: si el texto extraido
    CONTIENE la columna 'Texto en documento', se guarda la columna
    'Guardar como' en su lugar.
    """

    def __init__(self, master, conversiones_existentes=None):
        super().__init__(master)
        self.title("Reglas de conversion")
        self.resizable(False, False)
        self.resultado = None  # None = cancelado; lista = aceptado (puede estar vacia)

        contenedor = ttk.Frame(self, padding=14)
        contenedor.pack(fill="both", expand=True)

        ttk.Label(
            contenedor,
            text="Si el texto extraido CONTIENE el valor de 'Texto en documento',\n"
                 "se reemplaza completo por 'Guardar como'.\n"
                 "La comparacion ignora mayusculas/minusculas.",
            justify="left", foreground="#555555",
        ).pack(anchor="w", pady=(0, 8))

        marco_tabla = ttk.Frame(contenedor)
        marco_tabla.pack(fill="both", expand=True)

        self._tabla = ttk.Treeview(
            marco_tabla, columns=("entrada", "salida"), show="headings", height=8,
        )
        self._tabla.heading("entrada", text="Texto en documento")
        self._tabla.heading("salida", text="Guardar como")
        self._tabla.column("entrada", width=210)
        self._tabla.column("salida", width=160)
        self._tabla.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(marco_tabla, orient="vertical", command=self._tabla.yview)
        scroll.pack(side="right", fill="y")
        self._tabla.configure(yscrollcommand=scroll.set)

        for regla in (conversiones_existentes or []):
            self._tabla.insert("", "end", values=(regla.get("entrada", ""), regla.get("salida", "")))

        fila_campos = ttk.Frame(contenedor)
        fila_campos.pack(fill="x", pady=(8, 0))
        ttk.Label(fila_campos, text="Texto en documento:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self._entry_entrada = ttk.Entry(fila_campos, width=22)
        self._entry_entrada.grid(row=0, column=1, padx=(0, 12))
        ttk.Label(fila_campos, text="Guardar como:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self._entry_salida = ttk.Entry(fila_campos, width=18)
        self._entry_salida.grid(row=0, column=3)

        self._lbl_error = ttk.Label(contenedor, text="", foreground="red")
        self._lbl_error.pack(anchor="w", pady=(4, 0))

        fila_botones = ttk.Frame(contenedor)
        fila_botones.pack(fill="x", pady=(8, 0))
        ttk.Button(fila_botones, text="Agregar regla", command=self._agregar).pack(side="left", padx=2)
        ttk.Button(fila_botones, text="Eliminar seleccionada", command=self._eliminar).pack(side="left", padx=2)
        ttk.Button(fila_botones, text="Cancelar", command=self.destroy).pack(side="right", padx=2)
        ttk.Button(fila_botones, text="Aceptar", command=self._aceptar).pack(side="right", padx=2)

        self.grab_set()
        self._entry_entrada.focus_set()

    def _agregar(self):
        entrada = self._entry_entrada.get().strip()
        salida = self._entry_salida.get().strip()
        if not entrada or not salida:
            self._lbl_error.config(text="Ambos campos son obligatorios.")
            return
        self._lbl_error.config(text="")
        self._tabla.insert("", "end", values=(entrada, salida))
        self._entry_entrada.delete(0, "end")
        self._entry_salida.delete(0, "end")
        self._entry_entrada.focus_set()

    def _eliminar(self):
        for item in self._tabla.selection():
            self._tabla.delete(item)

    def _aceptar(self):
        self.resultado = [
            {"entrada": self._tabla.item(item, "values")[0], "salida": self._tabla.item(item, "values")[1]}
            for item in self._tabla.get_children()
        ]
        self.destroy()


# =========================================================================
# Asistente principal
# =========================================================================

class AsistenteConfiguracion(tk.Toplevel):

    def __init__(self, master, settings_existente=None):
        super().__init__(master)
        self.title("Configuracion del RENOMBRADOR")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cerrar_sin_guardar)

        self.resultado = None  # Settings final, o None si se cerro sin terminar

        # --- Estado que se va completando a lo largo de los pasos ---
        self.modo_entrada_tipo = "separados"
        self.modo_division = "paginas_fijas"
        self.paginas_por_documento = 1
        self.patron_inicio = ""
        self.patron_fin = ""

        self.un_solo_formato = True
        # Cada formato "en construccion" es un dict simple (no dataclass
        # todavia, para poder editarlo libremente en pantalla):
        # {"nombre","orientacion","filas","columnas","texto_identificador",
        #  "campos": [...], "imagen_muestra": PIL.Image|None}
        self.formatos_wip = []
        self.indice_formato_editando = None
        self._origen_paso_3 = "unico"  # "unico" o "gestor" -- a donde volver despues de editar zonas

        self.patron_nombre_archivo = "{cliente}-{factura}"

        self._modificando_existente = settings_existente is not None
        if settings_existente is not None:
            self._cargar_desde_settings(settings_existente)

        contenedor = ttk.Frame(self, padding=16)
        contenedor.pack(fill="both", expand=True)
        self.marco_paso = ttk.Frame(contenedor)
        self.marco_paso.pack(fill="both", expand=True)

        if self._modificando_existente:
            self._ir_a_paso_1()
        else:
            self._ir_a_paso_0()

        self.grab_set()

    # --- Utilidades comunes ---------------------------------------------

    def _limpiar_marco(self):
        for hijo in self.marco_paso.winfo_children():
            hijo.destroy()

    def _titulo_paso(self, texto):
        ttk.Label(self.marco_paso, text=texto, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 12))

    def _fila_navegacion(self, on_atras=None, texto_siguiente="Siguiente", on_siguiente=None):
        fila = ttk.Frame(self.marco_paso)
        fila.pack(fill="x", pady=(16, 0))
        if on_atras:
            ttk.Button(fila, text="Atras", command=on_atras).pack(side="left")
        if on_siguiente:
            ttk.Button(fila, text=texto_siguiente, command=on_siguiente).pack(side="right")

    def _cargar_desde_settings(self, s: settings_mod.Settings):
        self.modo_entrada_tipo = s.modo_entrada.tipo
        self.modo_division = s.modo_entrada.modo_division
        self.paginas_por_documento = s.modo_entrada.paginas_por_documento or 1
        self.patron_inicio = s.modo_entrada.patron_inicio or ""
        self.patron_fin = s.modo_entrada.patron_fin or ""
        self.un_solo_formato = len(s.formatos) <= 1
        self.patron_nombre_archivo = s.patron_nombre_archivo

        self.formatos_wip = []
        for formato in s.formatos:
            self.formatos_wip.append({
                "nombre": formato.nombre,
                "motor": formato.motor,
                "orientacion": formato.orientacion,
                "filas": formato.filas_cuadricula,
                "columnas": formato.columnas_cuadricula,
                "texto_identificador": formato.texto_identificador or "",
                "patron_nombre_archivo": formato.patron_nombre_archivo,
                "reglas_clasicas": formato.reglas_clasicas,
                "campos": [
                    {
                        "nombre": c.nombre, "patron_amigable": c.patron_amigable,
                        "patron_validacion": c.patron_validacion, "etiqueta": c.etiqueta,
                        "pagina": c.pagina, "obligatorio": c.obligatorio,
                        "longitud_minima": c.longitud_minima,
                        "zonas": list(c.zonas), "conversiones": list(c.conversiones),
                    }
                    for c in formato.campos
                ],
                "imagen_muestra": None,
            })

    # --- Paso 0: atajo ----------------------------------------------------

    def _ir_a_paso_0(self):
        self._limpiar_marco()
        self._titulo_paso("Antes de empezar")

        ttk.Label(
            self.marco_paso,
            text="¿Los documentos son iguales a los que ya procesa este programa\n"
                 "(codigo de cliente + factura con formato CMER-XXXXXXX)?",
            justify="left",
        ).pack(anchor="w", pady=(0, 16))

        ttk.Button(
            self.marco_paso, text="Si, usar esa plantilla ya armada",
            command=self._usar_plantilla_clasica,
        ).pack(anchor="w", pady=4)
        ttk.Button(
            self.marco_paso, text="No, quiero configurar el documento desde cero",
            command=self._ir_a_paso_1,
        ).pack(anchor="w", pady=4)

    def _usar_plantilla_clasica(self):
        self.resultado = settings_mod.settings_por_defecto_clasico()
        settings_mod.guardar(self.resultado)
        self.destroy()

    # --- Paso 1: modo de entrada -------------------------------------------

    def _ir_a_paso_1(self):
        self._limpiar_marco()
        self._titulo_paso("1. ¿Como vienen los documentos?")

        self.var_tipo_entrada = tk.StringVar(value=self.modo_entrada_tipo)
        ttk.Radiobutton(
            self.marco_paso, text="Separados (cada PDF es un documento distinto)",
            variable=self.var_tipo_entrada, value="separados", command=self._actualizar_visibilidad_paso_1,
        ).pack(anchor="w")
        ttk.Radiobutton(
            self.marco_paso, text="Combinados (varios documentos en el mismo PDF)",
            variable=self.var_tipo_entrada, value="juntos", command=self._actualizar_visibilidad_paso_1,
        ).pack(anchor="w")

        self.marco_combinados = ttk.Frame(self.marco_paso, padding=(20, 10, 0, 0))
        self.marco_combinados.pack(anchor="w", fill="x")

        self.var_modo_division = tk.StringVar(value=self.modo_division)
        ttk.Radiobutton(
            self.marco_combinados, text="Cada documento tiene una cantidad FIJA de paginas:",
            variable=self.var_modo_division, value="paginas_fijas", command=self._actualizar_visibilidad_paso_1,
        ).grid(row=0, column=0, sticky="w", columnspan=2)
        self.spin_paginas = ttk.Spinbox(self.marco_combinados, from_=1, to=20, width=6)
        self.spin_paginas.delete(0, "end")
        self.spin_paginas.insert(0, str(self.paginas_por_documento))
        self.spin_paginas.grid(row=1, column=0, sticky="w", padx=(20, 0), pady=(2, 10))

        ttk.Radiobutton(
            self.marco_combinados, text="NO es una cantidad fija: reconocer por texto de inicio/fin",
            variable=self.var_modo_division, value="patron", command=self._actualizar_visibilidad_paso_1,
        ).grid(row=2, column=0, sticky="w", columnspan=2)

        ttk.Label(self.marco_combinados, text="Frase/patron con el que EMPIEZA cada documento:").grid(
            row=3, column=0, sticky="w", padx=(20, 0), pady=(6, 0)
        )
        self.entry_patron_inicio = ttk.Entry(self.marco_combinados, width=40)
        self.entry_patron_inicio.insert(0, self.patron_inicio)
        self.entry_patron_inicio.grid(row=4, column=0, sticky="w", padx=(20, 0))

        ttk.Label(self.marco_combinados, text="Frase/patron con el que TERMINA (opcional):").grid(
            row=5, column=0, sticky="w", padx=(20, 0), pady=(6, 0)
        )
        self.entry_patron_fin = ttk.Entry(self.marco_combinados, width=40)
        self.entry_patron_fin.insert(0, self.patron_fin)
        self.entry_patron_fin.grid(row=6, column=0, sticky="w", padx=(20, 0))

        self.mensaje_error_paso1 = ttk.Label(self.marco_paso, text="", foreground="red")
        self.mensaje_error_paso1.pack(anchor="w", pady=(8, 0))

        self._actualizar_visibilidad_paso_1()
        self._fila_navegacion(on_siguiente=self._validar_y_avanzar_paso_1)

    def _actualizar_visibilidad_paso_1(self):
        combinados = self.var_tipo_entrada.get() == "juntos"
        for hijo in self.marco_combinados.winfo_children():
            hijo.configure(state="normal" if combinados else "disabled")

    def _validar_y_avanzar_paso_1(self):
        self.modo_entrada_tipo = self.var_tipo_entrada.get()
        if self.modo_entrada_tipo == "juntos":
            self.modo_division = self.var_modo_division.get()
            if self.modo_division == "paginas_fijas":
                try:
                    self.paginas_por_documento = max(1, int(self.spin_paginas.get()))
                except ValueError:
                    self.mensaje_error_paso1.config(text="La cantidad de paginas debe ser un numero.")
                    return
            else:
                self.patron_inicio = self.entry_patron_inicio.get().strip()
                self.patron_fin = self.entry_patron_fin.get().strip()
                if not self.patron_inicio:
                    self.mensaje_error_paso1.config(text="Hace falta el patron de INICIO de cada documento.")
                    return
                try:
                    re.compile(self.patron_inicio)
                    if self.patron_fin:
                        re.compile(self.patron_fin)
                except re.error:
                    self.mensaje_error_paso1.config(text="Alguno de los patrones no es una expresion regular valida.")
                    return
        self._ir_a_paso_2()

    # --- Paso 2: uno o varios formatos -------------------------------------

    def _ir_a_paso_2(self):
        self._limpiar_marco()
        self._titulo_paso("2. ¿Los documentos tienen el mismo formato?")

        self.var_un_solo_formato = tk.BooleanVar(value=self.un_solo_formato)
        ttk.Radiobutton(
            self.marco_paso, text="Si, todos tienen el mismo formato",
            variable=self.var_un_solo_formato, value=True,
        ).pack(anchor="w")
        ttk.Radiobutton(
            self.marco_paso, text="No, hay varios formatos distintos",
            variable=self.var_un_solo_formato, value=False,
        ).pack(anchor="w")

        self._fila_navegacion(on_atras=self._ir_a_paso_1, on_siguiente=self._confirmar_paso_2)

    def _confirmar_paso_2(self):
        self.un_solo_formato = self.var_un_solo_formato.get()

        if self.un_solo_formato:
            if not self.formatos_wip:
                self.formatos_wip = [self._formato_wip_nuevo("Formato principal")]
            else:
                # Se reutiliza el formato existente TAL CUAL (con todos sus
                # campos y zonas ya marcados, incluso si venia de una
                # configuracion "clasica" anterior) -- no se descarta nada.
                # _guardar_y_avanzar_paso_3 se encarga de dejarlo en motor
                # "zonas" al guardar, sin necesidad de reconfigurar de cero
                # lo que la persona ya habia marcado.
                self.formatos_wip = self.formatos_wip[:1]
            self.indice_formato_editando = 0
            self._origen_paso_3 = "unico"
            self._ir_a_paso_3()
        else:
            self._ir_a_paso_2b()

    def _formato_wip_nuevo(self, nombre):
        return {
            "nombre": nombre, "motor": "zonas", "orientacion": "vertical",
            "filas": 6, "columnas": 4, "texto_identificador": "",
            "patron_nombre_archivo": None, "reglas_clasicas": None,
            "campos": [], "imagen_muestra": None,
        }

    # --- Paso 2b: gestor de varios formatos ---------------------------------

    def _ir_a_paso_2b(self):
        self._limpiar_marco()
        self._titulo_paso("2. Formatos configurados")

        marco_lista = ttk.Frame(self.marco_paso)
        marco_lista.pack(fill="both", expand=True)

        self.lista_formatos = tk.Listbox(marco_lista, width=50, height=8)
        self.lista_formatos.pack(side="left", fill="both", expand=True)
        for formato in self.formatos_wip:
            self.lista_formatos.insert("end", f"{formato['nombre']}  ({len(formato['campos'])} campo(s))")

        botones = ttk.Frame(self.marco_paso)
        botones.pack(fill="x", pady=(10, 0))
        ttk.Button(botones, text="+ Agregar formato", command=self._agregar_formato_paso_2b).pack(side="left", padx=4)
        ttk.Button(botones, text="Editar zonas/campos", command=self._editar_formato_paso_2b).pack(side="left", padx=4)
        ttk.Button(botones, text="Quitar", command=self._quitar_formato_paso_2b).pack(side="left", padx=4)

        self.mensaje_error_paso2b = ttk.Label(self.marco_paso, text="", foreground="red")
        self.mensaje_error_paso2b.pack(anchor="w", pady=(8, 0))

        self._fila_navegacion(on_atras=self._ir_a_paso_2, on_siguiente=self._validar_y_avanzar_paso_2b)

    def _agregar_formato_paso_2b(self):
        nombre = f"Formato {len(self.formatos_wip) + 1}"
        self.formatos_wip.append(self._formato_wip_nuevo(nombre))
        self._ir_a_paso_2b()

    def _quitar_formato_paso_2b(self):
        seleccion = self.lista_formatos.curselection()
        if not seleccion:
            return
        del self.formatos_wip[seleccion[0]]
        self._ir_a_paso_2b()

    def _editar_formato_paso_2b(self):
        seleccion = self.lista_formatos.curselection()
        if not seleccion:
            self.mensaje_error_paso2b.config(text="Elija un formato de la lista primero.")
            return
        self.indice_formato_editando = seleccion[0]
        self._origen_paso_3 = "gestor"
        self._ir_a_paso_3()

    def _validar_y_avanzar_paso_2b(self):
        if not self.formatos_wip:
            self.mensaje_error_paso2b.config(text="Agregue al menos un formato antes de continuar.")
            return
        sin_campos = [f["nombre"] for f in self.formatos_wip if not f["campos"]]
        if sin_campos:
            self.mensaje_error_paso2b.config(
                text=f"Estos formatos todavia no tienen ningun campo configurado: {', '.join(sin_campos)}."
            )
            return
        self._ir_a_paso_4()

    # --- Paso 3: edicion de un formato (zonas + campos) ---------------------

    def _ir_a_paso_3(self):
        self._limpiar_marco()
        formato = self.formatos_wip[self.indice_formato_editando]

        self._titulo_paso(f"3. Configurar formato: {formato['nombre']}")

        fila_superior = ttk.Frame(self.marco_paso)
        fila_superior.pack(fill="x", pady=(0, 8))

        ttk.Label(fila_superior, text="Nombre del formato:").pack(side="left")
        self.entry_nombre_formato = ttk.Entry(fila_superior, width=24)
        self.entry_nombre_formato.insert(0, formato["nombre"])
        self.entry_nombre_formato.pack(side="left", padx=(4, 16))

        if not self.un_solo_formato:
            ttk.Label(fila_superior, text="Texto que identifica este formato (opcional):").pack(side="left")
            self.entry_identificador = ttk.Entry(fila_superior, width=24)
            self.entry_identificador.insert(0, formato.get("texto_identificador") or "")
            self.entry_identificador.pack(side="left", padx=(4, 0))
        else:
            self.entry_identificador = None

        fila_muestra = ttk.Frame(self.marco_paso)
        fila_muestra.pack(fill="x", pady=(0, 8))
        ttk.Button(fila_muestra, text="Elegir PDF de muestra...", command=self._elegir_pdf_muestra).pack(side="left")
        ttk.Button(fila_muestra, text="Usar hoja en blanco", command=self._usar_hoja_en_blanco).pack(side="left", padx=6)

        self.var_orientacion = tk.StringVar(value=formato["orientacion"])
        ttk.Radiobutton(fila_muestra, text="Vertical", variable=self.var_orientacion, value="vertical",
                         command=self._on_cambiar_orientacion).pack(side="left", padx=(16, 0))
        ttk.Radiobutton(fila_muestra, text="Horizontal", variable=self.var_orientacion, value="horizontal",
                         command=self._on_cambiar_orientacion).pack(side="left")

        cuerpo = ttk.Frame(self.marco_paso)
        cuerpo.pack(fill="both", expand=True)

        marco_selector = ttk.Frame(cuerpo)
        marco_selector.pack(side="left", padx=(0, 12))

        imagen_inicial = formato["imagen_muestra"] or self._placeholder_en_blanco(formato["orientacion"])
        self.selector = SelectorZonas(
            marco_selector, imagen_fondo=imagen_inicial,
            filas=formato["filas"], columnas=formato["columnas"],
            ancho_maximo=480, alto_maximo=620,
            on_cambio=self._on_cambio_selector,
        )
        self.selector.pack()
        for campo in formato["campos"]:
            self.selector.celdas_por_campo.setdefault(campo["nombre"], set())
            for zona in campo["zonas"]:
                self._marcar_celdas_de_zona(campo["nombre"], zona, formato["filas"], formato["columnas"])
        self.selector._dibujar()

        marco_campos = ttk.Frame(cuerpo)
        marco_campos.pack(side="left", fill="both", expand=True)

        ttk.Label(marco_campos, text="Campos de este formato:").pack(anchor="w")
        self.lista_campos = tk.Listbox(marco_campos, width=36, height=10)
        self.lista_campos.pack(fill="both", expand=True, pady=(2, 6))
        self._refrescar_lista_campos(formato)
        self.lista_campos.bind("<<ListboxSelect>>", self._on_seleccionar_campo)

        botones_campos = ttk.Frame(marco_campos)
        botones_campos.pack(fill="x")
        ttk.Button(botones_campos, text="+ Agregar campo", command=self._agregar_campo).pack(side="left", padx=2)
        ttk.Button(botones_campos, text="Editar", command=self._editar_campo_seleccionado).pack(side="left", padx=2)
        ttk.Button(botones_campos, text="Quitar", command=self._quitar_campo_seleccionado).pack(side="left", padx=2)
        ttk.Button(botones_campos, text="Conversiones...", command=self._abrir_conversiones_campo).pack(side="left", padx=2)
        ttk.Button(botones_campos, text="Limpiar zonas marcadas", command=self._limpiar_zonas_campo_seleccionado).pack(
            anchor="w", pady=(6, 0)
        )

        ttk.Label(
            marco_campos,
            text="1) Elija un campo de la lista.\n2) Haga clic en las celdas de la hoja donde aparece ese dato.\n"
                 "El color identifica a cada campo.",
            foreground="#555555", wraplength=280, justify="left",
        ).pack(anchor="w", pady=(10, 0))

        self.mensaje_error_paso3 = ttk.Label(self.marco_paso, text="", foreground="red")
        self.mensaje_error_paso3.pack(anchor="w", pady=(8, 0))

        texto_siguiente = "Guardar y volver a la lista" if self._origen_paso_3 == "gestor" else "Siguiente"
        self._fila_navegacion(on_atras=self._volver_desde_paso_3, texto_siguiente=texto_siguiente,
                               on_siguiente=self._guardar_y_avanzar_paso_3)

    def _placeholder_en_blanco(self, orientacion):
        tamano = PLACEHOLDER_HORIZONTAL if orientacion == "horizontal" else PLACEHOLDER_VERTICAL
        return Image.new("RGB", tamano, "white")

    def _marcar_celdas_de_zona(self, nombre_campo, zona, filas, columnas):
        """Al reabrir un formato ya configurado, reconstruye que celdas corresponden a una zona guardada."""
        x0, y0, x1, y1 = zona
        col_inicio = int(round(x0 * columnas))
        col_fin = max(col_inicio, int(round(x1 * columnas)) - 1)
        fila_inicio = int(round(y0 * filas))
        fila_fin = max(fila_inicio, int(round(y1 * filas)) - 1)
        celdas = self.selector.celdas_por_campo.setdefault(nombre_campo, set())
        for f in range(fila_inicio, fila_fin + 1):
            for c in range(col_inicio, col_fin + 1):
                celdas.add((f, c))

    def _on_cambio_selector(self):
        """
        Se llama cada vez que se marca/desmarca una celda en la
        cuadricula (SelectorZonas.on_cambio). Sin esto, la lista de
        campos se quedaba mostrando "(sin zona marcada)" hasta que se
        saliera y volviera a entrar a esta pantalla -- el click SI
        marcaba la celda en el dibujo, pero nunca se avisaba a esta
        ventana para que actualizara el dato guardado ni el texto de la
        lista.
        """
        self._sincronizar_zonas_desde_selector()
        self._refrescar_lista_campos(self.formatos_wip[self.indice_formato_editando])

    def _refrescar_lista_campos(self, formato):
        # Se preserva cual fila estaba resaltada: como la lista se borra y
        # se vuelve a llenar en cada click de la cuadricula, sin esto la
        # seleccion visual desaparecia con cada click aunque el campo
        # activo (para dibujar) seguia siendo el correcto.
        seleccion_previa = self.lista_campos.curselection()
        self.lista_campos.delete(0, "end")
        for campo in formato["campos"]:
            if campo["zonas"] and campo.get("etiqueta"):
                marca = f"✓ zona + etiqueta: {campo['etiqueta']}"
            elif campo["zonas"]:
                marca = "✓ zona"
            elif campo.get("etiqueta"):
                marca = f"✓ etiqueta: {campo['etiqueta']}"
            else:
                marca = "(sin zona ni etiqueta)"
            self.lista_campos.insert("end", f"{campo['nombre']}  {marca}")
        if seleccion_previa and seleccion_previa[0] < self.lista_campos.size():
            self.lista_campos.selection_set(seleccion_previa[0])

    def _campo_actual_seleccionado(self):
        seleccion = self.lista_campos.curselection()
        if not seleccion:
            return None
        formato = self.formatos_wip[self.indice_formato_editando]
        return formato["campos"][seleccion[0]]

    def _on_seleccionar_campo(self, _evento):
        campo = self._campo_actual_seleccionado()
        self.selector.establecer_campo_activo(campo["nombre"] if campo else None)

    def _elegir_pdf_muestra(self):
        ruta = filedialog.askopenfilename(title="Elegir PDF de muestra", filetypes=[("PDF", "*.pdf")])
        if not ruta:
            return
        try:
            imagenes = ocr_engine.pdf_a_imagenes(ruta, max_paginas=1)
        except Exception as error:
            messagebox.showerror("No se pudo abrir el PDF", str(error))
            return
        if not imagenes:
            messagebox.showerror("No se pudo abrir el PDF", "El archivo no tiene paginas legibles.")
            return
        # Misma correccion de orientacion que aplica el motor en produccion
        # (preparar_pagina_completa): sin esto, si el PDF viene girado, las
        # zonas se marcarian sobre una vista distinta a la que el OCR real
        # termina viendo, y quedarian todas desalineadas.
        imagen_muestra = preprocesamiento.corregir_orientacion(imagenes[0], CFG.idiomas_ocr)
        formato = self.formatos_wip[self.indice_formato_editando]
        formato["imagen_muestra"] = imagen_muestra
        self.selector.establecer_imagen_fondo(imagen_muestra)

    def _usar_hoja_en_blanco(self):
        formato = self.formatos_wip[self.indice_formato_editando]
        formato["imagen_muestra"] = None
        self.selector.establecer_imagen_fondo(self._placeholder_en_blanco(self.var_orientacion.get()))

    def _on_cambiar_orientacion(self):
        formato = self.formatos_wip[self.indice_formato_editando]
        if formato["imagen_muestra"] is None:
            self.selector.establecer_imagen_fondo(self._placeholder_en_blanco(self.var_orientacion.get()))

    def _agregar_campo(self):
        dialogo = _DialogoCampo(self)
        self.wait_window(dialogo)
        if dialogo.resultado is None:
            return
        nuevo = dialogo.resultado
        nuevo["zonas"] = []
        nuevo["conversiones"] = []
        nuevo.setdefault("etiqueta", None)
        formato = self.formatos_wip[self.indice_formato_editando]
        if any(c["nombre"] == nuevo["nombre"] for c in formato["campos"]):
            messagebox.showerror("Nombre repetido", f"Ya existe un campo llamado '{nuevo['nombre']}' en este formato.")
            return
        formato["campos"].append(nuevo)
        self.selector.establecer_campo_activo(nuevo["nombre"])
        self._refrescar_lista_campos(formato)

    def _editar_campo_seleccionado(self):
        campo = self._campo_actual_seleccionado()
        if campo is None:
            return
        dialogo = _DialogoCampo(self, campo_existente=campo)
        self.wait_window(dialogo)
        if dialogo.resultado is None:
            return
        campo["patron_amigable"] = dialogo.resultado["patron_amigable"]
        campo["patron_validacion"] = dialogo.resultado["patron_validacion"]
        campo["etiqueta"] = dialogo.resultado["etiqueta"]
        campo["pagina"] = dialogo.resultado["pagina"]
        campo["obligatorio"] = dialogo.resultado["obligatorio"]
        campo["longitud_minima"] = dialogo.resultado["longitud_minima"]
        self._refrescar_lista_campos(self.formatos_wip[self.indice_formato_editando])

    def _quitar_campo_seleccionado(self):
        campo = self._campo_actual_seleccionado()
        if campo is None:
            return
        formato = self.formatos_wip[self.indice_formato_editando]
        formato["campos"].remove(campo)
        self.selector.quitar_campo(campo["nombre"])
        self._refrescar_lista_campos(formato)

    def _limpiar_zonas_campo_seleccionado(self):
        campo = self._campo_actual_seleccionado()
        if campo is None:
            return
        self.selector.limpiar_celdas_de(campo["nombre"])
        campo["zonas"] = []
        self._refrescar_lista_campos(self.formatos_wip[self.indice_formato_editando])

    def _abrir_conversiones_campo(self):
        campo = self._campo_actual_seleccionado()
        if campo is None:
            self.mensaje_error_paso3.config(text="Elija un campo de la lista primero.")
            return
        self.mensaje_error_paso3.config(text="")
        dialogo = _DialogoConversiones(self, conversiones_existentes=campo.get("conversiones", []))
        self.wait_window(dialogo)
        if dialogo.resultado is None:
            return
        campo["conversiones"] = dialogo.resultado

    def _sincronizar_zonas_desde_selector(self):
        formato = self.formatos_wip[self.indice_formato_editando]
        for campo in formato["campos"]:
            zona = self.selector.obtener_zona_fraccionaria(campo["nombre"])
            campo["zonas"] = [zona] if zona else []

    def _volver_desde_paso_3(self):
        self._sincronizar_zonas_desde_selector()
        if self._origen_paso_3 == "gestor":
            self._ir_a_paso_2b()
        else:
            self._ir_a_paso_2()

    def _guardar_y_avanzar_paso_3(self):
        formato = self.formatos_wip[self.indice_formato_editando]
        nombre_nuevo = self.entry_nombre_formato.get().strip()
        if not nombre_nuevo:
            self.mensaje_error_paso3.config(text="El formato necesita un nombre.")
            return
        if not formato["campos"]:
            self.mensaje_error_paso3.config(text="Agregue al menos un campo antes de continuar.")
            return

        self._sincronizar_zonas_desde_selector()
        sin_ubicacion = [
            c["nombre"] for c in formato["campos"]
            if not c["zonas"] and not c.get("etiqueta")
        ]
        if sin_ubicacion:
            self.mensaje_error_paso3.config(
                text=f"Estos campos no tienen zona marcada ni etiqueta configurada: {', '.join(sin_ubicacion)}.\n"
                     f"Marque celdas en la hoja, o defina una etiqueta de texto con el boton 'Editar'."
            )
            return

        formato["nombre"] = nombre_nuevo
        formato["orientacion"] = self.var_orientacion.get()
        formato["filas"] = self.selector.filas
        formato["columnas"] = self.selector.columnas
        if self.entry_identificador is not None:
            formato["texto_identificador"] = self.entry_identificador.get().strip() or None

        # Esta pantalla es EXCLUSIVAMENTE el editor de zonas: el formato
        # que se guarda desde aqui siempre debe quedar en motor "zonas",
        # sin importar si arranco (por venir de una configuracion
        # "clasica" anterior, ver _confirmar_paso_2/_editar_formato_paso_2b)
        # marcado de otra forma. De lo contrario el programa seguiria
        # usando el motor clasico (buscar "Cod. Cliente"/"CMER-XXXXXXX" en
        # toda la hoja) e ignorando por completo los campos y zonas que se
        # acaban de configurar aqui.
        formato["motor"] = "zonas"
        formato["reglas_clasicas"] = None
        # El patron de nombre a nivel de formato no se edita en esta pantalla
        # (el unico que el usuario configura es el global, en el paso 4). Si
        # habia uno guardado de una configuracion clasica anterior, se limpia
        # para que no tape al global cuando se construya el nombre de archivo.
        formato["patron_nombre_archivo"] = None

        if self._origen_paso_3 == "gestor":
            self._ir_a_paso_2b()
        else:
            self._ir_a_paso_4()

    # --- Paso 4: patron del nombre de archivo -------------------------------

    def _ir_a_paso_4(self):
        self._limpiar_marco()
        self._titulo_paso("4. ¿Como se debe llamar el archivo final?")

        nombres_campos = sorted({c["nombre"] for f in self.formatos_wip for c in f["campos"]})

        ttk.Label(
            self.marco_paso,
            text="Combine los campos entre llaves, por ejemplo: {cliente}-{factura}",
        ).pack(anchor="w", pady=(0, 8))

        fila_botones_campos = ttk.Frame(self.marco_paso)
        fila_botones_campos.pack(anchor="w", pady=(0, 8))
        for nombre in nombres_campos:
            ttk.Button(
                fila_botones_campos, text=f"+ {{{nombre}}}",
                command=lambda n=nombre: self._insertar_placeholder(n),
            ).pack(side="left", padx=2)

        self.entry_patron_nombre = ttk.Entry(self.marco_paso, width=50)
        self.entry_patron_nombre.insert(0, self.patron_nombre_archivo)
        self.entry_patron_nombre.pack(anchor="w", pady=(0, 8))

        self.mensaje_error_paso4 = ttk.Label(self.marco_paso, text="", foreground="red", wraplength=500)
        self.mensaje_error_paso4.pack(anchor="w")

        self._fila_navegacion(
            on_atras=(self._ir_a_paso_2b if not self.un_solo_formato else self._ir_a_paso_2),
            on_siguiente=self._validar_y_avanzar_paso_4,
        )

    def _insertar_placeholder(self, nombre_campo):
        self.entry_patron_nombre.insert(tk.END, f"{{{nombre_campo}}}")

    def _validar_y_avanzar_paso_4(self):
        patron = self.entry_patron_nombre.get().strip()
        if not patron:
            self.mensaje_error_paso4.config(text="El patron del nombre de archivo no puede quedar vacio.")
            return

        nombres_pedidos = set(re.findall(r"\{(\w+)\}", patron))
        nombres_disponibles = {c["nombre"] for f in self.formatos_wip for c in f["campos"]}
        faltantes = nombres_pedidos - nombres_disponibles
        if faltantes:
            self.mensaje_error_paso4.config(
                text=f"El patron usa campos que no existen en ningun formato: {', '.join(sorted(faltantes))}."
            )
            return

        self.patron_nombre_archivo = patron
        self._ir_a_paso_final()

    # --- Paso final: resumen y guardar --------------------------------------

    def _ir_a_paso_final(self):
        self._limpiar_marco()
        self._titulo_paso("Resumen")

        lineas = []
        if self.modo_entrada_tipo == "separados":
            lineas.append("Entrada: documentos SUELTOS (cada PDF es un documento).")
        elif self.modo_division == "paginas_fijas":
            lineas.append(f"Entrada: documentos COMBINADOS, {self.paginas_por_documento} pagina(s) por documento.")
        else:
            lineas.append(
                f"Entrada: documentos COMBINADOS, separados por texto de inicio ('{self.patron_inicio}')"
                + (f" y fin ('{self.patron_fin}')." if self.patron_fin else " (sin patron de fin).")
            )

        lineas.append(f"Formato(s): {len(self.formatos_wip)}")
        for formato in self.formatos_wip:
            campos_txt = ", ".join(c["nombre"] for c in formato["campos"])
            lineas.append(f"  - {formato['nombre']}: campos [{campos_txt}]")

        lineas.append(f"Nombre de archivo: {self.patron_nombre_archivo}")

        texto_resumen = tk.Text(self.marco_paso, width=64, height=10, wrap="word")
        texto_resumen.insert("1.0", "\n".join(lineas))
        texto_resumen.configure(state="disabled")
        texto_resumen.pack(fill="both", expand=True, pady=(0, 12))

        self._fila_navegacion(on_atras=self._ir_a_paso_4, texto_siguiente="Guardar", on_siguiente=self._guardar_final)

    def _construir_settings_final(self) -> settings_mod.Settings:
        modo_entrada = settings_mod.ModoEntrada(
            tipo=self.modo_entrada_tipo,
            modo_division=self.modo_division,
            paginas_por_documento=self.paginas_por_documento,
            patron_inicio=self.patron_inicio or None,
            patron_fin=self.patron_fin or None,
        )

        formatos_finales = []
        for formato_wip in self.formatos_wip:
            campos_finales = [
                settings_mod.Campo(
                    nombre=c["nombre"], zonas=[tuple(z) for z in c["zonas"]],
                    patron_validacion=c["patron_validacion"], patron_amigable=c["patron_amigable"],
                    etiqueta=c.get("etiqueta") or None,
                    pagina=c["pagina"], obligatorio=c["obligatorio"],
                    longitud_minima=c.get("longitud_minima") or None,
                    conversiones=list(c.get("conversiones", [])),
                )
                for c in formato_wip["campos"]
            ]
            formatos_finales.append(settings_mod.Formato(
                nombre=formato_wip["nombre"],
                motor=formato_wip.get("motor", "zonas"),
                patron_nombre_archivo=formato_wip.get("patron_nombre_archivo"),
                texto_identificador=formato_wip.get("texto_identificador") or None,
                campos=campos_finales,
                reglas_clasicas=formato_wip.get("reglas_clasicas"),
                orientacion=formato_wip["orientacion"],
                filas_cuadricula=formato_wip["filas"],
                columnas_cuadricula=formato_wip["columnas"],
            ))

        return settings_mod.Settings(
            modo_entrada=modo_entrada,
            formatos=formatos_finales,
            patron_nombre_archivo=self.patron_nombre_archivo,
        )

    def _guardar_final(self):
        self.resultado = self._construir_settings_final()
        settings_mod.guardar(self.resultado)
        self.destroy()

    def _on_cerrar_sin_guardar(self):
        self.resultado = None
        self.destroy()


def ejecutar_asistente(master, settings_existente=None):
    """
    Abre el asistente (modal) y espera a que termine. Devuelve el Settings
    guardado, o None si se cerro sin completarlo (en ese caso quien llama
    debe decidir que hacer -- ver main.py, que no deja avanzar sin una
    configuracion valida).
    """
    ventana = AsistenteConfiguracion(master, settings_existente=settings_existente)
    master.wait_window(ventana)
    return ventana.resultado
