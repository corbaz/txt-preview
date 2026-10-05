# TXT Preview

Aplicación de escritorio para Windows escrita en PowerShell y WinForms. Permite editar texto, consultar y transformar contenido con Groq, previsualizar Markdown y leer el resultado en voz alta.

## Funciones actuales

- Editor y vista previa Markdown.
- Consultas, resumen, corrección y traducción mediante Groq.
- Lectura con voces locales de Windows o voces neuronales de Edge TTS.
- Control de voz, pausa, detención, velocidad y resaltado de la palabra actual.
- Exportación de la vista previa como PDF y de la lectura como MP3.
- Temas claro y oscuro.
- Pestaña de configuración con selección dinámica de modelos Groq.
- API key cifrada para el usuario de Windows mediante DPAPI.
- Búsqueda web con modelos GPT-OSS y adjuntos de texto o imagen según el modelo.
- Comprobación e instalación segura de actualizaciones desde el clon Git.

## Configuración de Groq

Abrí la pestaña **Configuración**, ingresá tu API key y seleccioná **Actualizar modelos**. Elegí el modelo activo y guardá la configuración. Los datos se almacenan fuera del repositorio en `%LOCALAPPDATA%\TXT Preview\settings.json`; la API key queda cifrada para tu usuario de Windows.

## Actualizaciones

Al abrir **Configuración**, la aplicación consulta `origin/main`. Si existe una versión posterior, aparece **Actualizar ahora**. La actualización requiere Git, la rama `main` y un árbol de trabajo sin cambios; usa `git pull --ff-only` y nunca sobrescribe modificaciones locales. Después hay que cerrar y volver a abrir TXT Preview.

## Requisitos

- Windows 10 u 11.
- Windows PowerShell 5.1.
- Python con `edge-tts` para las voces en línea.
- `ffplay` y `ffprobe` para reproducir y medir el audio Edge.
- Una API key de Groq para las funciones de IA.

## Ejecución

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\txt.ps1
```

## Seguridad

Las credenciales no forman parte del código ni del repositorio. No agregues archivos `.env`, `settings.json` ni API keys al control de versiones.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

La sintaxis del script principal puede comprobarse sin abrir la interfaz:

```powershell
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path .\txt.ps1), [ref]$tokens, [ref]$errors) > $null
$errors
```

## Documentación

Las decisiones y tareas SDD se guardan en [`docs/sdd/`](docs/sdd/).
