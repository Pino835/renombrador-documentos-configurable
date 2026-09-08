# -*- coding: utf-8 -*-
"""
gui.py
-------------------------------------------------------------------------
Ventanas de Tkinter del programa.

Mejoras sobre la version 1:

  1. VENTANA DE PROGRESO durante la fase automatica: en la version 1 el
     programa se quedaba "en silencio" (sin ninguna ventana visible)
     mientras procesaba todos los PDF de PRUEBA, lo cual con muchos
     archivos (o un equipo lento) se puede confundir con que el programa
     esta trabado. Ahora se muestra "Procesando X de Y: archivo.pdf" con
     una barra de progreso.

  2. VENTANA DE REVISION MANUAL generalizada a N CAMPOS: la version
     anterior mostraba siempre exactamente 2 campos fijos (cliente,
     factura). Ahora muestra los campos que tenga el Formato detectado
     (uno solo, dos, o los que se hayan configurado en el asistente),
     cada uno con su recorte (clic para agrandar), su valor leido
     precargado, y un aviso si ese valor NO cumple el patron esperado
     (para que la correccion manual no sea "a ciegas"). Tiene contador
     ("2 de 5 pendientes") y atajos de teclado (Enter = Aceptar, Esc =
     Cancelar).
-------------------------------------------------------------------------
"""

import os
from collections import namedtuple

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

from .config import limpiar_texto_extraido

# Un campo a mostrar en la ventana de revision manual:
#   nombre         -- nombre del campo (ej. "cliente", "factura", "orden")
#   recorte        -- imagen PIL ya recortada de donde se leyo (o un respaldo)
#   valor_previo   -- lo que el OCR alcanzo a leer (puede ser None)
#   patron_valido  -- True/False: si valor_previo cumple el patron esperado
#   obligatorio    -- si hace falta un valor para poder Aceptar
CampoRevision = namedtuple("CampoRevision", "nombre recorte valor_previo patron_valido obligatorio")


def _nombre_visible(nombre: str) -> str:
    """"codigo_cliente" -> "Codigo Cliente" (solo para mostrar en pantalla)."""
    return " ".join(palabra.capitalize() for palabra in nombre.replace("_", " ").split())


class VentanaProgreso(tk.Toplevel):
    """Ventana simple con una barra de progreso, visible durante la fase automatica."""

    def __init__(self, master, total: int):
        super().__init__(master)
        self.title("Procesando documentos - RENOMBRADOR")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # no se puede cerrar a mitad de proceso

        contenedor = ttk.Frame(self, padding=20)
        contenedor.pack(fill="both", expand=True)

        self.etiqueta = ttk.Label(contenedor, text="Iniciando...", width=60)
        self.etiqueta.pack(pady=(0, 10))

        self.barra = ttk.Progressbar(contenedor, length=400, maximum=max(total, 1))
        self.barra.pack()

        self.update_idletasks()
        ancho = self.winfo_reqwidth()
        alto = self.winfo_reqheight()
        x = (self.winfo_screenwidth() - ancho) // 2
        y = (self.winfo_screenheight() - alto) // 2
        self.geometry(f"+{x}+{y}")

    def actualizar(self, indice: int, total: int, nombre_archivo: str):
        self.etiqueta.config(text=f"Procesando {indice} de {total}:\n{nombre_archivo}")
        self.barra["value"] = indice
        self.update_idletasks()


class VentanaRevisionManual(tk.Toplevel):
    """
    Ventana persistente de revision manual: recibe la lista completa de
    archivos pendientes y los muestra uno por uno en el mismo lugar,
    actualizando el contenido al avanzar, sin cerrar ni reabrir la ventana
    entre archivos.

    items: list de (ruta_pdf: Path, nombre_archivo: str, campos: list[CampoRevision])
    resultados: list de ("aceptar", {campo: valor}) o ("cancelar", None),
                en el mismo orden que items (se llena conforme el usuario avanza).
    """

    ANCHO_MAX_IMAGEN = 650
    ALTO_MAX_IMAGEN = 180
    ALTO_MAX_VENTANA = 700

    def __init__(self, master, items):
        super().__init__(master)
        self.title("Revision manual necesaria - RENOMBRADOR")
        self.resizable(False, True)
        self.protocol("WM_DELETE_WINDOW", self._on_cerrar_ventana)

        self._items = list(items)
        self._indice = 0
        self.resultados = []   # ("aceptar", valores) o ("cancelar", None) por item
        self.entries = []
        self._fotos = []

        contenedor = ttk.Frame(self, padding=16)
        contenedor.pack(fill="both", expand=True)

        self._lbl_contador = ttk.Label(contenedor, font=("Segoe UI", 9), foreground="#555555")
        self._lbl_contador.pack(anchor="w")

        self._lbl_nombre = ttk.Label(contenedor, font=("Segoe UI", 11, "bold"), justify="center")
        self._lbl_nombre.pack(pady=(4, 12))

        self._zona_campos = ttk.Frame(contenedor)
        self._zona_campos.pack(fill="both", expand=True)

        self.mensaje_error = ttk.Label(contenedor, text="", foreground="red")
        self.mensaje_error.pack(pady=(6, 0))

        fila_botones = ttk.Frame(contenedor)
        fila_botones.pack(pady=(10, 0))
        self._btn_examinar = ttk.Button(
            fila_botones, text="Examinar Archivo",
            command=self._on_examinar_archivo,
        )
        self._btn_examinar.pack(side="left", padx=6)
        ttk.Button(fila_botones, text="Cancelar (omitir este archivo) [Esc]",
                   command=self._on_cancelar).pack(side="left", padx=6)
        ttk.Button(fila_botones, text="Aceptar [Enter]",
                   command=self._on_aceptar).pack(side="left", padx=6)

        self.bind("<Return>", lambda e: self._on_aceptar())
        self.bind("<Escape>", lambda e: self._on_cancelar())

        self.grab_set()
        self._cargar_item(0)

    def _cargar_item(self, indice):
        ruta_pdf, nombre_archivo, campos = self._items[indice]
        total = len(self._items)

        self._lbl_contador.config(
            text=f"Documento {indice + 1} de {total} pendientes de revision manual"
        )
        self._lbl_nombre.config(
            text=f"No se pudieron confirmar todos los datos de:\n{nombre_archivo}"
        )

        # Desenlazar rueda del mouse antes de destruir el canvas anterior
        self.unbind_all("<MouseWheel>")
        for widget in self._zona_campos.winfo_children():
            widget.destroy()
        self._fotos.clear()
        self.entries = []
        self.mensaje_error.config(text="")

        interior = self._crear_area_de_campos(self._zona_campos)
        for campo in campos:
            self._agregar_fila_de_campo(interior, campo)

        if self.entries:
            self.entries[0].focus_set()
        self.update_idletasks()

    def _crear_area_de_campos(self, padre):
        canvas = tk.Canvas(padre, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(padre, orient="vertical", command=canvas.yview)
        interior = ttk.Frame(canvas)

        interior.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=interior, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _rueda_mouse(evento):
            canvas.yview_scroll(int(-1 * (evento.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _rueda_mouse)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(width=self.ANCHO_MAX_IMAGEN + 40, height=self.ALTO_MAX_VENTANA)
        return interior

    def _agregar_fila_de_campo(self, padre, campo: CampoRevision):
        ttk.Label(
            padre, text=f"{_nombre_visible(campo.nombre)} (clic en la imagen para agrandar):"
        ).pack(anchor="w", pady=(4, 0))

        foto = self._preparar_foto(campo.recorte)
        self._fotos.append(foto)
        etiqueta_img = ttk.Label(padre, image=foto, relief="solid", cursor="hand2")
        etiqueta_img.pack(pady=(2, 4))
        etiqueta_img.bind("<Button-1>", lambda e, imagen=campo.recorte: self._ampliar(imagen))

        fila_entry = ttk.Frame(padre)
        fila_entry.pack(fill="x", pady=(0, 4))
        entry = ttk.Entry(fila_entry, width=40)
        entry.pack(side="left")
        if campo.valor_previo:
            entry.insert(0, campo.valor_previo)
        if not campo.obligatorio:
            ttk.Label(fila_entry, text="(opcional)", foreground="#777777").pack(side="left", padx=(8, 0))

        if campo.valor_previo and not campo.patron_valido:
            ttk.Label(
                padre,
                text="El OCR leyo un valor que no cumple el formato esperado para este campo -- reviselo.",
                foreground="#b45309",
            ).pack(anchor="w", pady=(0, 8))
        else:
            ttk.Frame(padre, height=8).pack()

        self.entries.append(entry)

    def _preparar_foto(self, imagen_pil: Image.Image):
        copia = imagen_pil.copy()
        copia.thumbnail((self.ANCHO_MAX_IMAGEN, self.ALTO_MAX_IMAGEN))
        return ImageTk.PhotoImage(copia)

    def _ampliar(self, imagen_pil: Image.Image):
        ventana = tk.Toplevel(self)
        ventana.title("Vista ampliada")
        copia = imagen_pil.copy()
        copia.thumbnail((1400, 900))
        foto = ImageTk.PhotoImage(copia)
        etiqueta = ttk.Label(ventana, image=foto)
        etiqueta.image = foto
        etiqueta.pack()
        ttk.Button(ventana, text="Cerrar", command=ventana.destroy).pack(pady=8)

    def _on_examinar_archivo(self):
        ruta_pdf, _, _campos = self._items[self._indice]
        try:
            os.startfile(ruta_pdf)
        except Exception:
            pass

    def _on_aceptar(self):
        _ruta, _nombre, campos = self._items[self._indice]
        valores = {}
        faltantes = []
        for campo, entry in zip(campos, self.entries):
            valor = limpiar_texto_extraido(entry.get())
            if not valor:
                if campo.obligatorio:
                    faltantes.append(_nombre_visible(campo.nombre))
                continue
            valores[campo.nombre] = valor

        if faltantes:
            self.mensaje_error.config(text=f"Campos obligatorios sin completar: {', '.join(faltantes)}.")
            return

        self.resultados.append(("aceptar", valores))
        self._avanzar()

    def _on_cancelar(self):
        self.resultados.append(("cancelar", None))
        self._avanzar()

    def _on_cerrar_ventana(self):
        # X en mitad de la sesion: marcar los restantes como cancelados y cerrar
        while len(self.resultados) < len(self._items):
            self.resultados.append(("cancelar", None))
        self.destroy()

    def _avanzar(self):
        siguiente = self._indice + 1
        if siguiente < len(self._items):
            self._indice = siguiente
            self._cargar_item(siguiente)
        else:
            self.destroy()
