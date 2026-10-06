# TXT Preview

Aplicación de escritorio para Windows que reúne en una sola ventana un editor de texto, una vista previa Markdown, herramientas de IA (consultar, resumir, corregir y traducir con [Groq](https://groq.com)) y lectura en voz alta.

## Qué podés hacer

- Escribir o pegar texto y verlo formateado en **Vista previa**.
- **Consultar IA**: tu consulta queda en el Editor y la respuesta aparece en **Vista previa**. Desde ahí podés usar **Llevar al editor** para seguir trabajando sobre la respuesta, o **Ver el editor** para volver a ver tu texto.
- **Resumir**, **Corregir gramática y ortografía** y **Traducir** inglés ↔ español reemplazan el texto del Editor; **Ctrl+Z** recupera el original.
- En la barra **Contexto IA**, arriba del Editor: búsqueda web (activada por defecto en los modelos que navegan) y **Adjuntar archivos** de texto o imágenes, según el modelo elegido. Los íconos verdes muestran qué puede hacer el modelo actual.
- Abrir los links de las respuestas en la pestaña **Navegador**, con barra de direcciones, atrás y adelante, o en tu navegador predeterminado. La primera vez la app descarga el componente WebView2 de Microsoft (~10 MB, verificado por firma digital).
- Escuchar el resultado con voces de Windows o voces neuronales de Edge, con pausa, velocidad y resaltado de la palabra que se lee.
- Exportar a **PDF** y **MP3**, copiar como Markdown o texto plano. Estas acciones y **Play** usan lo que muestra la Vista previa: la respuesta de la IA si hay una, o el texto del Editor.
- Elegir tema claro u oscuro.

## Instalación

Necesitás Windows 10 u 11 y [Git](https://git-scm.com/download/win). Si no tenés Git, instalalo primero:

```powershell
winget install --id Git.Git -e --source winget
```

Después abrí **PowerShell** (no hace falta como administrador) y pegá este comando:

```powershell
git clone https://github.com/corbaz/txt-preview.git "$env:LOCALAPPDATA\txt-preview"; powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\txt-preview\install.ps1"
```

El instalador:

1. Descarga la app en `%LOCALAPPDATA%\txt-preview`.
2. Crea el acceso directo **TXT Preview** en el escritorio.
3. Si no tenés PowerShell 7, lo instala (la app lo necesita para mostrar bien los acentos).
4. Si tenés Python, instala `edge-tts` para las voces en línea.
5. Abre la aplicación.

## Primeros pasos

1. Creá una API key gratuita en [console.groq.com/keys](https://console.groq.com/keys).
2. En la app, abrí **Configuración**, pegá la API key y tocá **Guardar**.
3. Tocá **Actualizar modelos** y elegí uno en el selector de la parte superior. `openai/gpt-oss-120b` es una buena opción general; `qwen/qwen3.8-27b` entiende imágenes.
4. Volvé al **Editor**, escribí algo y probá **Consultar IA**.

La API key se guarda cifrada para tu usuario de Windows en `%LOCALAPPDATA%\TXT Preview\settings.json`. Nunca se sube al repositorio.

## Voces y audio (opcional)

| Para | Necesitás | Cómo instalarlo |
|------|-----------|-----------------|
| Voces de Windows | Nada extra | — |
| Voces neuronales de Edge | Python y `edge-tts` | `winget install Python.Python.3.12` y volver a ejecutar `install.ps1` |
| Reproducir voces de Edge y exportar MP3 | FFmpeg (`ffplay`, `ffprobe`, `ffmpeg`) | `winget install Gyan.FFmpeg` |

Después de instalar Python o FFmpeg, cerrá y volvé a abrir la app.

## Actualizaciones

Al abrir la app, si hay una versión nueva aparece un aviso que pregunta si querés actualizar; si aceptás, se actualiza y se reinicia sola. También podés tocar **Buscar actualización** en **Configuración**. La actualización nunca pisa cambios que hayas hecho en los archivos de la app: si los hay, te avisa y no actualiza.

## Problemas frecuentes

| Mensaje o síntoma | Solución |
|-------------------|----------|
| `git` no se reconoce | Instalá Git con el comando de arriba y abrí una ventana nueva de PowerShell. |
| `destination path ... already exists` | La app ya está instalada. Ejecutá solo `powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\txt-preview\install.ps1"`. |
| Mensaje rojo "Error al conectar con la API" | Revisá la API key en **Configuración** y tu conexión a internet. |
| No suenan las voces de Edge | Instalá Python y FFmpeg (ver tabla de voces). |

Los mensajes de la app usan colores: verde para información, amarillo para advertencias y rojo para errores.

## Desinstalación

Cerrá la app y ejecutá en PowerShell:

```powershell
Remove-Item "$env:LOCALAPPDATA\txt-preview" -Recurse -Force
Remove-Item "$env:LOCALAPPDATA\TXT Preview" -Recurse -Force
Remove-Item "$([Environment]::GetFolderPath('Desktop'))\TXT Preview.lnk"
```

La segunda línea borra tu configuración y la API key guardada.

---

## Para desarrolladores

La app es un único script de PowerShell 7 con WinForms ([`txt.ps1`](txt.ps1)). Para ejecutarla desde un clon:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\txt.ps1
```

### Pruebas

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

### Publicar una versión

La actualización automática compara el archivo [`VERSION`](VERSION) (formato `v:yy.mm.dd-HH.mm`) con el de `origin/main`. Cada cambio en la app publicado en `main` tiene que actualizar `VERSION`; si no, los usuarios no reciben el aviso. Los cambios solo de documentación no lo necesitan.

### Seguridad

Las credenciales no forman parte del código ni del repositorio. No agregues archivos `.env`, `settings.json`, `.rdp` ni API keys al control de versiones.

### Documentación

Las decisiones y tareas de diseño se guardan en [`docs/sdd/`](docs/sdd/) y [`odd/tasks/`](odd/tasks/).
