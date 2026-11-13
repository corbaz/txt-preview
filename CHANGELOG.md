# Historial de cambios

## v:26.11.13-08.51

### TXT Preview multiplataforma (Windows + macOS)

- La app se reconstruye en Python + pywebview: una sola base de código que corre igual en Windows (WebView2) y macOS (WKWebView), corriendo directo del clon.
- Núcleo portable verificado con paridad contra el código original: citas de búsqueda web, prompts de Consultar/Resumir/Corregir/Traducir, HTTP de Groq y bridges locales (Claude/Codex/Gemini), catálogo de modelos y capacidades.
- Motor de voz Edge-only en ambas plataformas: bloques de párrafos, reproducción con ffplay, pausa/reanudación por suspensión de proceso (NtSuspendProcess / SIGSTOP), Repetir con seek y cadena atempo, resaltado palabra por palabra con clic para saltar.
- Adjuntos: texto, PDF (PyMuPDF), Word (.docx) y PowerPoint (.pptx) vía OpenXML en Python puro; imágenes (máx. 3). Los formatos antiguos .doc y .ppt ya no se admiten (requerían Office COM en Windows).
- Exportación a PDF y MP3 sin Microsoft Edge headless; copiar como Markdown o texto.
- Configuración persistente multiplataforma: API key cifrada con DPAPI en Windows (migra el settings.json de la versión anterior) y Keychain en macOS; catálogo de voces Edge con caché y selector en Configuración.
- Actualización integrada: VERSION comparado con origin/main y `git pull --ff-only`, sin pisar cambios locales.
- Doctor de dependencias (`python app/doctor.py`): tabla en español para humanos, `--json` para agentes de IA, `--fix` para instalar lo que falta; instaladores por plataforma (`install.ps1` / `install.sh`) y lanzadores (`run.cmd` / `run.sh`).
- CI de GitHub Actions en windows + macos: la suite Python (301 pruebas) y el doctor corren en cada push, para que un cambio hecho en Windows no rompa la Mac sin que se note.
- La versión anterior de solo Windows (txt.ps1) se conserva en el repositorio como legado.

### Validación

- 301 pruebas de la app nueva en verde, sin red, corriendo igual en ambos sistemas; guardas AST impiden llamadas Windows-only sin protección de plataforma.
- Suite legada: 122/123 (el único error es un flakes preexistente de un pwsh temporal bloqueado).
- Smoke real en WebView2 y doctor en vivo (9 comprobaciones OK).


## v:26.10.30-15.28

### Catálogo de voces Edge resistente

- TXT reintenta la consulta inicial de voces Edge y guarda atómicamente el último catálogo válido en `%LOCALAPPDATA%\TXT Preview\edge-voices.json`.
- Un fallo temporal de red o del servicio ya no hace desaparecer las voces: TXT utiliza el catálogo guardado y muestra una advertencia visible.
- Una caché dañada se ignora con seguridad; si falta Python o `edge-tts`, se conserva el catálogo local de Windows y se informa cómo repararlo.
- La detección de Python usa el código de salida del proceso con timeout, sin depender del estado global heredado de la terminal.

### Validación

- Se añadieron pruebas para consulta normal, reintento, recuperación desde caché, caché dañada y dependencia ausente.
- Pasaron 123 pruebas, el parser de PowerShell terminó sin errores y el smoke real confirmó 92 voces Edge, 5 voces Windows y una caché válida de 92 entradas.

## v:26.10.22-09.52

### Proveedores y modelos de IA

- Claude, Codex y Gemini pueden usarse mediante bridges locales junto con Groq, desde un único selector agrupado por proveedor.
- Configuración muestra si cada bridge está apagado, sin contraseña, con contraseña incorrecta o conectado, y vuelve a comprobarlo al guardar o editar la contraseña.
- La lista de modelos admite desplazamiento y muestra en columnas sus capacidades de chat, visión, búsqueda web y adjuntos.
- Los mensajes de espera identifican el proveedor y el modelo que están respondiendo.
- Las imágenes copiadas al portapapeles pueden pegarse como adjuntos cuando el modelo admite visión.

### Voces Edge

- El instalador actualiza `edge-tts` en lugar de conservar una versión antigua que Microsoft pueda rechazar.
- TXT reconoce el error HTTP 403 de una versión obsoleta y ofrece **Actualizar voces** en Configuración.
- La consulta de la versión de `edge-tts` se demora hasta abrir Configuración para no retrasar el inicio.
- Se documentó cómo recuperar el catálogo cuando una instalación nueva de Python no tiene `edge-tts` y cómo corregir el `PATH` cuando FFmpeg está instalado pero TXT no encuentra `ffplay.exe`.

### Validación

- Las rutas de Groq existentes se conservaron y los bridges se limitan a `127.0.0.1`.
- Las contraseñas siguen fuera del repositorio y se guardan cifradas cuando se ingresan desde Configuración.
