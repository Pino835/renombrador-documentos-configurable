# PROYECTO ULTRA SECRETO 3 — Renombrador de documentos (v2)

Programa de escritorio (Python + Tkinter + Tesseract-OCR) que lee PDF
escaneados, extrae campos por OCR y guarda una copia renombrada según un
patrón configurable. No está atado a un tipo de documento: toda la
adaptación (zonas de la hoja, patrones, conversiones, nombre final) se
hace vía un asistente (wizard) que escribe `settings.json`, sin tocar
código.

Es una reconstrucción desde cero de un proyecto anterior
("PROYECTO_RENOMBRADOR"), independiente y sin dependencias sobre él.
No es un repositorio git.

## Cómo correr

- `ejecutar_1_instalar_dependencias.bat` — una sola vez (o al cambiar de
  equipo). Instala Python y Tesseract-OCR si faltan (`_sistema/instalar_dependencias.py`,
  `_sistema/instalar_python.ps1`), todo a nivel de usuario (sin admin).
- `ejecutar_2_renombrador.bat` — ejecuta `_sistema/renombrador.py`, que
  llama a `motor.main.main()`. Cada vez que se quieran procesar documentos.
- Dependencias Python (`_sistema/requirements.txt`): PyMuPDF, pytesseract,
  Pillow.

No hay tests automatizados ni linter configurado en este proyecto.

## Flujo de datos (carpetas en la raíz)

```
PRUEBA/         -> PDF de entrada (nunca se modifican ni se borran)
POR_REVISAR/    -> cola temporal para revisión manual
RESULTADO/<fecha>/ -> PDF ya renombrados, destino final
_sistema/       -> todo el código y config; el usuario no necesita abrirla
Documentacion/  -> guías en texto plano (ver abajo)
```

Pipeline (`motor/main.py`):
1. **Fase 1 (automática)**: por cada PDF (o cada sub-documento si vienen
   combinados, ver `division_documentos.py`), detecta el formato, hace
   OCR en las zonas configuradas (`extractores_zonas.py`) o con el motor
   clásico de patrones de texto (`extractores.py`), valida contra el
   patrón esperado y el umbral de confianza, y si todo cuadra guarda la
   copia renombrada en `RESULTADO/<fecha>/`.
2. **Fase 2 (manual)**: lo que no pasó la fase automática se muestra en
   una ventana de revisión (`gui.py`) con el recorte de cada campo; al
   confirmar, el valor se guarda en `codigos_confirmados.json` para
   mejorar corridas futuras.
3. Todo se registra en `log_renombrador.json` (uso interno) y
   `log_renombrador.csv` (para abrir en Excel).

## `_sistema/motor/` — mapa de módulos

| Módulo | Responsabilidad |
|---|---|
| `main.py` | Orquesta todo el proceso (fases 1 y 2, resumen final). |
| `asistente.py` | Wizard de configuración (genera/edita `settings.json`). |
| `settings.py` | Modelo de `settings.json` + traductor de patrones amigables (`LLL-NNNN`, `A{6,}`, `regex:...`) a regex reales. |
| `config.py` | Lee `config.json` y resuelve rutas (umbral OCR, idioma, carpetas). |
| `selector_zonas.py` | Widget de cuadrícula para marcar zonas de campos en el wizard. |
| `preprocesamiento.py` | Enderezar páginas giradas, binarización (Otsu) antes del OCR. |
| `ocr_engine.py` | Interfaz con Tesseract y con PDF→imágenes (PyMuPDF). |
| `extractores.py` | Motor "clásico": busca campos por patrones de texto en toda la página (modo compatibilidad v1: cliente/factura). |
| `extractores_zonas.py` | Motor "zonas": OCR acotado a la zona marcada por campo, detección de formato, conversiones, corrección O/0 e I/1. |
| `division_documentos.py` | Separa un PDF combinado en documentos individuales (páginas fijas o por texto delimitador). |
| `aprendizaje.py` | `codigos_confirmados.json`: valores confirmados a mano por campo, usados para autocorregir confusiones típicas del OCR. |
| `almacenamiento.py` | Manejo de carpetas, nombres de archivo, copiado/movido de PDFs. |
| `registro.py` | Log `.json` (interno) y `.csv` (Excel). |
| `gui.py` | Ventanas Tkinter de progreso y de revisión manual. |

## Configuración (dos archivos, propósitos distintos)

- **`_sistema/config.json`** — infraestructura, casi nunca cambia: umbral
  de confianza OCR (`umbral_confianza_minima`), idioma Tesseract
  (`spa+eng`), DPI de render, nombres de carpetas. Editable a mano con
  Bloc de notas.
- **`_sistema/settings.json`** — generado y editado SOLO por el
  asistente (`asistente.py`). Define, por cada "formato" de documento:
  texto identificador, zonas (coordenadas relativas 0–1) de cada campo,
  patrón de validación, si es obligatorio, conversiones (ej.
  "Davivienda" → "DAV"), y el patrón del nombre de archivo final
  (`{numero_diario}-{banco}-{vendor}`). Soporta múltiples formatos
  (se detecta cuál aplica por texto identificador o por cuántos campos
  valida cada uno) y modo de entrada "separados" vs "combinados".

**Nunca edites `settings.json` a mano para agregar/cambiar formatos o
zonas** — usa el asistente (opción "Modificar configuración" al
arrancar el programa), ya que las coordenadas de zona dependen de la
cuadrícula (`filas_cuadricula`/`columnas_cuadricula`) elegida en el wizard.

### Sintaxis de patrón esperado (`patron_amigable`)

`L`=letra, `N`=dígito, `A`=alfanumérico. Repetir = cantidad exacta
(`LLL`), `+` = uno o más (`N+`), `{n,}` = mínimo (`A{6,}`), `{n,m}` =
rango (`L{2,5}`). Para casos avanzados, prefijo `regex:` con una regex
Python literal. Ver `Documentacion/GUIA_PATRON_ESPERADO.txt` para la
referencia completa.

## Convenciones del código

- Todo el código, nombres de variables/funciones y comentarios están en
  **español** — sigue esa convención al modificar este proyecto.
- Los archivos originales en `PRUEBA/` nunca se borran ni modifican: el
  programa siempre copia, nunca mueve el original directamente (excepto
  al confirmar revisión manual, donde sí se mueve de `POR_REVISAR` a
  `RESULTADO`).
- El botón "Cancelar" en revisión manual omite solo ese archivo, nunca
  todo el proceso.
- La corrección automática O/0 e I/1 solo actúa cuando hay exactamente
  un candidato confirmado que calce (para no adivinar entre códigos
  parecidos).
- Patrones más estrictos son preferibles a permisivos (`A+`,
  `regex:.+`): un patrón laxo puede aceptar y renombrar con datos
  incorrectos sin que nadie lo note.

## Documentación existente

`Documentacion/` contiene explicaciones ya escritas para el usuario final:
`LEEME_PRIMERO.txt` (checklist de instalación/uso), `COMO_FUNCIONA.txt`
(descripción detallada, la fuente principal para este archivo),
`GUIA_PATRON_ESPERADO.txt` (sintaxis de patrones) y `QUE_CAMBIO.txt`
(diferencias vs. v1). Consúltalos antes de reexplicar algo que ya está
documentado ahí.
