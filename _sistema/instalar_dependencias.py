# -*- coding: utf-8 -*-
"""
instalar_dependencias.py
-------------------------------------------------------------------------
Instalador de dependencias para el proyecto RENOMBRADOR.

Se ejecuta UNA VEZ, a traves de "ejecutar_1_instalar_dependencias.bat"
(ese .bat primero se asegura de que Python este instalado -- ver
"instalar_python.ps1" -- y luego llama a este archivo). Deja el equipo
listo:

  1. Verifica que la version de Python instalada sea compatible.
  2. Instala / actualiza las librerias de Python que necesita el programa.
  3. Instala automaticamente el motor de OCR "Tesseract" si no esta en el
     equipo (Tesseract NO es una libreria de Python, es un programa
     aparte, por lo que pip no lo puede instalar solo). Primero intenta
     con winget; si no esta disponible, descarga el instalador oficial
     de UB-Mannheim y lo instala en modo silencioso, sin pedir permisos
     de administrador.
  4. Verifica el idioma Español y el modulo de deteccion de orientacion
     (OSD) de Tesseract, que la version 2 usa para enderezar paginas
     escaneadas de lado antes de leerlas.

Se puede volver a ejecutar cuantas veces se quiera: si ya esta todo
instalado, simplemente confirma que todo esta en orden y actualiza las
librerias a su ultima version.
-------------------------------------------------------------------------
"""

import sys
import subprocess
import shutil
import os
import urllib.request

# Librerias de Python que necesita el paquete "motor/"
REQUIREMENTS = [
    "PyMuPDF",       # Abrir PDFs y convertir sus paginas a imagenes (sin necesitar Poppler aparte)
    "pytesseract",   # Conector de Python hacia el motor de OCR Tesseract
    "Pillow",        # Recortar, mejorar y mostrar imagenes en la pantalla de revision manual
]


def print_titulo(txt):
    print("\n" + "=" * 64)
    print(txt)
    print("=" * 64)


def verificar_python():
    print_titulo("1. Verificando version de Python")
    print(f"Python detectado: {sys.version}")
    if sys.version_info < (3, 8):
        print("ERROR: se requiere Python 3.8 o superior.")
        print("Descargue una version reciente en https://www.python.org/downloads/")
        input("\nPresione ENTER para salir...")
        sys.exit(1)
    print("OK - version de Python compatible.")


def actualizar_pip():
    print_titulo("2. Actualizando pip")
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], check=False)


def instalar_librerias():
    print_titulo("3. Instalando / actualizando librerias de Python")
    fallidas = []
    for paquete in REQUIREMENTS:
        print(f"\n-> Instalando/actualizando: {paquete}")
        resultado = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", paquete],
            check=False,
        )
        if resultado.returncode != 0:
            fallidas.append(paquete)

    if fallidas:
        print("\nAVISO: no se pudieron instalar estas librerias automaticamente:")
        for f in fallidas:
            print(f"   - {f}")
        print("Intente instalarlas manualmente abriendo una consola (CMD) y escribiendo:")
        print(f"   {sys.executable} -m pip install " + " ".join(fallidas))
    else:
        print("\nOK - todas las librerias de Python quedaron instaladas/actualizadas.")


def verificar_tkinter():
    print_titulo("4. Verificando tkinter (pantallas del programa)")
    try:
        import tkinter  # noqa: F401
        print("OK - tkinter disponible (viene incluido con Python).")
    except ImportError:
        print("ADVERTENCIA: tkinter no esta disponible en este Python.")
        print("Reinstale Python desde https://www.python.org/downloads/ marcando")
        print("la opcion 'tcl/tk and IDLE' durante la instalacion.")


# Version fija del instalador de Tesseract-OCR (build oficial de UB-Mannheim,
# publicada en el repositorio oficial de tesseract-ocr en GitHub). Si mas
# adelante sale una version mas nueva y quieren usarla, solo hay que
# actualizar esta URL.
URL_INSTALADOR_TESSERACT = (
    "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/"
    "tesseract-ocr-w64-setup-5.5.0.20241111.exe"
)


def _tesseract_ya_instalado():
    ruta = shutil.which("tesseract")
    if ruta:
        return ruta
    posibles = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Tesseract-OCR", "tesseract.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
    ]
    for p in posibles:
        if p and os.path.exists(p):
            return p
    return None


def instalar_tesseract():
    """Devuelve la ruta de tesseract.exe si quedo instalado (o ya lo estaba), o None si no."""
    print_titulo("5. Instalando el motor de OCR (Tesseract-OCR)")

    ruta = _tesseract_ya_instalado()
    if ruta:
        print(f"OK - Tesseract ya esta instalado en: {ruta}")
        return ruta

    print("No se encontro Tesseract-OCR en este equipo. Se va a instalar")
    print("automaticamente (es el programa que hace el reconocimiento de")
    print("texto -OCR- sobre las facturas escaneadas; no es una libreria de")
    print("Python, por eso no se instala con pip).")

    instalado = False

    # 1) Se intenta primero con winget: es lo mas simple y confiable
    #    cuando esta disponible en el equipo.
    if shutil.which("winget"):
        print("\n-> Instalando con winget (puede tardar varios minutos)...")
        resultado = subprocess.run(
            [
                "winget", "install", "--id", "UB-Mannheim.TesseractOCR", "-e",
                "--silent", "--accept-package-agreements", "--accept-source-agreements",
            ],
            check=False,
        )
        if resultado.returncode == 0:
            instalado = True
        else:
            print("winget no pudo instalarlo (o no esta disponible); se intenta por descarga directa.")

    # 2) Respaldo: se descarga el instalador oficial (UB-Mannheim) y se
    #    ejecuta en modo silencioso, instalando en la carpeta del usuario
    #    para que NO haga falta permisos de administrador.
    if not instalado:
        destino = os.path.join(os.environ.get("TEMP", "."), "tesseract-ocr-w64-setup.exe")
        directorio_instalacion = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Tesseract-OCR")
        try:
            print(f"\n-> Descargando el instalador desde:\n   {URL_INSTALADOR_TESSERACT}")
            urllib.request.urlretrieve(URL_INSTALADOR_TESSERACT, destino)
            print("-> Instalando (silencioso, sin permisos de administrador)...")
            # El modificador /D= debe ir de ultimo y sin comillas: asi lo
            # exige el instalador (esta hecho con NSIS).
            subprocess.run([destino, "/S", f"/D={directorio_instalacion}"], check=False)
            instalado = True
        except Exception as error:
            print(f"ERROR: no se pudo descargar/instalar Tesseract-OCR automaticamente: {error}")

    ruta_final = _tesseract_ya_instalado()
    if instalado and ruta_final:
        print("\nOK - Tesseract-OCR quedo instalado correctamente.")
        return ruta_final
    elif instalado:
        print("\nSe corrio el instalador, pero no se pudo confirmar la instalacion todavia.")
        print("Vuelva a ejecutar este archivo para confirmar.")
        return None
    else:
        print("\nATENCION: no se pudo instalar Tesseract-OCR automaticamente.")
        print("Descarguelo e instalelo manualmente desde:")
        print("   https://github.com/UB-Mannheim/tesseract/wiki")
        print("(en el instalador, en 'Additional language data', marque 'Spanish').")
        return None


# El instalador silencioso de Tesseract (tanto por winget como por descarga
# directa) NO incluye el idioma Español -- solo trae Ingles. Sin el idioma
# Español, el programa igual "funciona" pero lee mucho peor las facturas
# (pierde precision con tildes, "Cod.", etc.). Por eso se descarga aparte
# el archivo de idioma Español directo del repositorio oficial de datos
# de Tesseract, y se coloca junto a los demas idiomas.
URL_IDIOMA_ESPANOL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/spa.traineddata"


def instalar_idioma_espanol(ruta_tesseract_exe):
    print_titulo("6. Verificando el idioma Español para el OCR")

    if not ruta_tesseract_exe:
        print("Se omite este paso: no se pudo confirmar donde quedo instalado Tesseract-OCR.")
        return

    carpeta_tessdata = os.path.join(os.path.dirname(ruta_tesseract_exe), "tessdata")
    destino = os.path.join(carpeta_tessdata, "spa.traineddata")

    if os.path.exists(destino):
        print(f"OK - el idioma Español ya esta instalado ({destino}).")
        return

    print("Tesseract esta instalado, pero SIN el idioma Español (por defecto solo")
    print("trae Ingles). Sin el, la lectura de facturas en Español pierde bastante")
    print("precision. Se va a descargar ahora...")
    try:
        print(f"\n-> Descargando desde:\n   {URL_IDIOMA_ESPANOL}")
        urllib.request.urlretrieve(URL_IDIOMA_ESPANOL, destino)
        print(f"\nOK - idioma Español instalado en: {destino}")
    except PermissionError:
        print(f"\nATENCION: no se pudo escribir en:\n   {carpeta_tessdata}")
        print("(hace falta permiso de administrador para esa carpeta).")
        print("Vuelva a ejecutar 'ejecutar_1_instalar_dependencias.bat' como Administrador,")
        print("o descargue el archivo manualmente desde:")
        print(f"   {URL_IDIOMA_ESPANOL}")
        print(f"y copielo hacia:\n   {carpeta_tessdata}")
    except Exception as error:
        print(f"\nERROR: no se pudo descargar/instalar el idioma Español: {error}")


# La version 2 usa la deteccion de orientacion de Tesseract (OSD) para
# enderezar paginas escaneadas de lado o al reves antes de leerlas (ver
# "motor/preprocesamiento.py"). Ese modulo viene incluido por defecto en
# la instalacion normal de Tesseract, pero se verifica aqui para poder
# avisar si por algun motivo falta (el programa igual sigue funcionando
# sin el, solo que sin esa correccion de orientacion).
URL_OSD = "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/osd.traineddata"


def verificar_modulo_orientacion(ruta_tesseract_exe):
    print_titulo("7. Verificando el modulo de orientacion (OSD) de Tesseract")

    if not ruta_tesseract_exe:
        print("Se omite este paso: no se pudo confirmar donde quedo instalado Tesseract-OCR.")
        return

    carpeta_tessdata = os.path.join(os.path.dirname(ruta_tesseract_exe), "tessdata")
    destino = os.path.join(carpeta_tessdata, "osd.traineddata")

    if os.path.exists(destino):
        print(f"OK - el modulo de orientacion ya esta instalado ({destino}).")
        return

    print("Falta el modulo de orientacion (osd.traineddata). Sin el, el programa")
    print("sigue funcionando normal, solo que no puede enderezar automaticamente")
    print("una pagina escaneada de lado o al reves. Se va a descargar ahora...")
    try:
        print(f"\n-> Descargando desde:\n   {URL_OSD}")
        urllib.request.urlretrieve(URL_OSD, destino)
        print(f"\nOK - modulo de orientacion instalado en: {destino}")
    except Exception as error:
        print(f"\nAVISO: no se pudo descargar el modulo de orientacion: {error}")
        print("No es grave: el programa sigue funcionando igual, solo sin esa mejora.")


def main():
    print_titulo("INSTALADOR DE DEPENDENCIAS - PROYECTO RENOMBRADOR (v2)")
    verificar_python()
    actualizar_pip()
    instalar_librerias()
    verificar_tkinter()
    ruta_tesseract = instalar_tesseract()
    instalar_idioma_espanol(ruta_tesseract)
    verificar_modulo_orientacion(ruta_tesseract)
    print_titulo("Instalacion finalizada")
    print("Ya puede ejecutar 'ejecutar_2_renombrador.bat' para procesar las facturas.")
    input("\nPresione ENTER para cerrar esta ventana...")


if __name__ == "__main__":
    main()
