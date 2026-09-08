# -*- coding: utf-8 -*-
"""
selector_zonas.py
-------------------------------------------------------------------------
Widget de Tkinter reutilizable: muestra una pagina de muestra (o un
rectangulo en blanco si no hay muestra) con una cuadricula ENCIMA, ajustable
en filas/columnas. El usuario elige que campo esta marcando ("campo
activo") y hace click en las celdas donde aparece ese dato; cada campo
queda pintado de un color distinto para diferenciarlos. La zona resultante
de cada campo (el rectangulo que envuelve sus celdas marcadas) se puede
pedir en fracciones 0..1 de la pagina con "obtener_zona_fraccionaria",
lista para guardarse en settings.json (Campo.zonas).

No depende de "asistente.py": se puede probar solo (ver el bloque
"if __name__" al final).
-------------------------------------------------------------------------
"""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

_PALETA_COLORES = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"]


class SelectorZonas(ttk.Frame):

    def __init__(self, master, imagen_fondo: Image.Image = None, filas=6, columnas=4,
                 ancho_maximo=650, alto_maximo=850, on_cambio=None):
        super().__init__(master)
        self.filas = max(1, filas)
        self.columnas = max(1, columnas)
        self.imagen_fondo_original = imagen_fondo or Image.new("RGB", (850, 1100), "white")
        self.celdas_por_campo = {}  # nombre_campo -> set of (fila, col)
        self.campo_activo = None
        self.on_cambio = on_cambio
        self._ancho_maximo = ancho_maximo
        self._alto_maximo = alto_maximo

        controles = ttk.Frame(self)
        controles.pack(fill="x", pady=(0, 6))

        ttk.Label(controles, text="Filas:").pack(side="left")
        self.spin_filas = ttk.Spinbox(controles, from_=1, to=40, width=4, command=self._on_cambiar_grilla)
        self.spin_filas.delete(0, "end")
        self.spin_filas.insert(0, str(self.filas))
        self.spin_filas.pack(side="left", padx=(2, 12))
        self.spin_filas.bind("<Return>", lambda e: self._on_cambiar_grilla())
        self.spin_filas.bind("<FocusOut>", lambda e: self._on_cambiar_grilla())

        ttk.Label(controles, text="Columnas:").pack(side="left")
        self.spin_columnas = ttk.Spinbox(controles, from_=1, to=40, width=4, command=self._on_cambiar_grilla)
        self.spin_columnas.delete(0, "end")
        self.spin_columnas.insert(0, str(self.columnas))
        self.spin_columnas.pack(side="left", padx=(2, 0))
        self.spin_columnas.bind("<Return>", lambda e: self._on_cambiar_grilla())
        self.spin_columnas.bind("<FocusOut>", lambda e: self._on_cambiar_grilla())

        self.canvas = tk.Canvas(self, bg="white", cursor="crosshair", highlightthickness=1,
                                 highlightbackground="#999999")
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_click_celda)

        self._recalcular_geometria()
        self._dibujar()

    # --- API publica ---------------------------------------------------

    def establecer_campo_activo(self, nombre_campo):
        """Los clicks en la grilla, de ahora en adelante, marcan celdas para este campo."""
        self.campo_activo = nombre_campo
        if nombre_campo is not None:
            self.celdas_por_campo.setdefault(nombre_campo, set())
        self._dibujar()

    def quitar_campo(self, nombre_campo):
        self.celdas_por_campo.pop(nombre_campo, None)
        if self.campo_activo == nombre_campo:
            self.campo_activo = None
        self._dibujar()

    def limpiar_celdas_de(self, nombre_campo):
        self.celdas_por_campo[nombre_campo] = set()
        self._dibujar()

    def obtener_zona_fraccionaria(self, nombre_campo):
        """
        Devuelve (x0, y0, x1, y1) fraccionario (0..1 de la pagina) que
        envuelve TODAS las celdas marcadas para ese campo, o None si no
        tiene ninguna celda marcada.
        """
        celdas = self.celdas_por_campo.get(nombre_campo)
        if not celdas:
            return None
        filas = [f for f, _c in celdas]
        columnas = [c for _f, c in celdas]
        fila_min, fila_max = min(filas), max(filas)
        col_min, col_max = min(columnas), max(columnas)
        return (
            col_min / self.columnas,
            fila_min / self.filas,
            (col_max + 1) / self.columnas,
            (fila_max + 1) / self.filas,
        )

    def establecer_imagen_fondo(self, imagen: Image.Image):
        self.imagen_fondo_original = imagen
        self._recalcular_geometria()
        self._dibujar()

    # --- Internos --------------------------------------------------------

    def _recalcular_geometria(self):
        ancho_original, alto_original = self.imagen_fondo_original.size
        escala = min(self._ancho_maximo / ancho_original, self._alto_maximo / alto_original)
        self.ancho_mostrado = max(1, int(ancho_original * escala))
        self.alto_mostrado = max(1, int(alto_original * escala))
        self.canvas.configure(width=self.ancho_mostrado, height=self.alto_mostrado)
        imagen_redimensionada = self.imagen_fondo_original.resize(
            (self.ancho_mostrado, self.alto_mostrado), Image.LANCZOS
        )
        self._foto_fondo = ImageTk.PhotoImage(imagen_redimensionada)

    def _on_cambiar_grilla(self):
        try:
            nuevas_filas = max(1, int(self.spin_filas.get()))
            nuevas_columnas = max(1, int(self.spin_columnas.get()))
        except ValueError:
            return
        if nuevas_filas == self.filas and nuevas_columnas == self.columnas:
            return
        self.filas, self.columnas = nuevas_filas, nuevas_columnas
        self._dibujar()

    def _on_click_celda(self, evento):
        if self.campo_activo is None:
            return
        ancho_celda = self.ancho_mostrado / self.columnas
        alto_celda = self.alto_mostrado / self.filas
        col = min(max(int(evento.x // ancho_celda), 0), self.columnas - 1)
        fila = min(max(int(evento.y // alto_celda), 0), self.filas - 1)

        celdas = self.celdas_por_campo.setdefault(self.campo_activo, set())
        if (fila, col) in celdas:
            celdas.discard((fila, col))
        else:
            celdas.add((fila, col))

        self._dibujar()
        if self.on_cambio:
            self.on_cambio()

    def _color_de(self, nombre_campo):
        nombres = list(self.celdas_por_campo.keys())
        indice = nombres.index(nombre_campo) if nombre_campo in nombres else 0
        return _PALETA_COLORES[indice % len(_PALETA_COLORES)]

    def _dibujar(self):
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._foto_fondo)

        ancho_celda = self.ancho_mostrado / self.columnas
        alto_celda = self.alto_mostrado / self.filas

        for nombre, celdas in self.celdas_por_campo.items():
            color = self._color_de(nombre)
            estampado = "gray25" if nombre == self.campo_activo else "gray50"
            for fila, col in celdas:
                x0, y0 = col * ancho_celda, fila * alto_celda
                x1, y1 = x0 + ancho_celda, y0 + alto_celda
                self.canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline=color, stipple=estampado)

        for i in range(self.filas + 1):
            y = i * alto_celda
            self.canvas.create_line(0, y, self.ancho_mostrado, y, fill="#aaaaaa")
        for j in range(self.columnas + 1):
            x = j * ancho_celda
            self.canvas.create_line(x, 0, x, self.alto_mostrado, fill="#aaaaaa")


if __name__ == "__main__":
    # Prueba aislada: python -m motor.selector_zonas
    raiz = tk.Tk()
    raiz.title("Prueba - selector de zonas")

    selector = SelectorZonas(raiz, filas=6, columnas=4)
    selector.pack(padx=10, pady=10)
    selector.establecer_campo_activo("cliente")

    barra = ttk.Frame(raiz)
    barra.pack(pady=(0, 10))

    def _marcar_cliente():
        selector.establecer_campo_activo("cliente")

    def _marcar_factura():
        selector.establecer_campo_activo("factura")

    def _mostrar_zonas():
        print("cliente:", selector.obtener_zona_fraccionaria("cliente"))
        print("factura:", selector.obtener_zona_fraccionaria("factura"))

    ttk.Button(barra, text="Marcar 'cliente'", command=_marcar_cliente).pack(side="left", padx=4)
    ttk.Button(barra, text="Marcar 'factura'", command=_marcar_factura).pack(side="left", padx=4)
    ttk.Button(barra, text="Imprimir zonas", command=_mostrar_zonas).pack(side="left", padx=4)

    raiz.mainloop()
