# Renombrador de Documentos Configurable

Programa de escritorio (Python + Tkinter + Tesseract-OCR) que lee PDF escaneados, extrae campos por OCR y guarda una copia renombrada según un patrón configurable. No está atado a un tipo de documento: toda la adaptación (zonas de la hoja, patrones, conversiones, nombre final) se hace vía un asistente (wizard) que genera la configuración, sin tocar código.

Es una evolución generalizada de un [renombrador más simple](../renombrador) enfocado originalmente en un solo tipo de documento.

## Qué hace

1. Revisa cada PDF de una carpeta de entrada (o cada sub-documento, si vienen combinados en un mismo archivo).
2. Detecta el formato del documento y extrae los campos configurados, ya sea por zonas fijas de la hoja o por patrones de texto.
3. Valida cada valor extraído contra un patrón esperado y un umbral de confianza de OCR.
4. Si todo cuadra, guarda una copia renombrada en una carpeta de resultados organizada por fecha.
5. Si algo no pasa la validación automática, abre una ventana de revisión con los recortes de cada campo para completarlo a mano.
6. Aprende de las correcciones manuales para autocorregir confusiones típicas del OCR (como "O" vs "0") en corridas futuras.
7. Registra cada resultado en un log (JSON y CSV).

## Tecnologías

- Python
- PyMuPDF (lectura de PDF)
- Tesseract OCR (vía `pytesseract`)
- Pillow
- Tkinter (asistente de configuración y ventanas de revisión)

## Estructura

```
_sistema/motor/       # todo el código del pipeline
_sistema/config.json  # configuración de infraestructura (umbral OCR, idioma, carpetas)
Documentacion/        # guías de instalación, uso y sintaxis de patrones
```

Más detalle de arquitectura y convenciones en `CLAUDE.md`.

## Cómo correr

1. `ejecutar_1_instalar_dependencias.bat` — una sola vez (o al cambiar de equipo).
2. `ejecutar_2_renombrador.bat` — procesa los documentos de la carpeta de entrada.

## Nota

Este proyecto se desarrolló como parte de un rol de automatización de procesos administrativos, dirigiendo herramientas de IA (Claude, Claude Code) para el diseño, implementación y documentación de la solución. El código aquí publicado no incluye la configuración específica de formato, datos ni documentos reales de ninguna organización.
