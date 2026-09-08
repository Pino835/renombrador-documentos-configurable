# -*- coding: utf-8 -*-
"""
renombrador.py
-------------------------------------------------------------------------
Punto de entrada. La logica real vive organizada en el paquete "motor/"
(config, ocr_engine, preprocesamiento, extractores, aprendizaje,
almacenamiento, registro, gui, main) en vez de un solo archivo largo --
mas facil de ubicar y modificar cada parte por separado. Se llama
"motor" y no "renombrador" para no tener un archivo y una carpeta con el
mismo nombre en el mismo lugar (eso confunde a Python al importar).
-------------------------------------------------------------------------
"""

from motor.main import main

if __name__ == "__main__":
    main()
