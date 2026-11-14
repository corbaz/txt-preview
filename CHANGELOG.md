# Historial de cambios

## v:26.11.14-08.34

### Certificados nativos en macOS y Python 3.14

- Las conexiones HTTPS de Groq usan ahora el almacén de certificados nativo mediante `truststore` (Keychain en macOS y CryptoAPI en Windows), sin desactivar la verificación TLS.
- La generación de audio y la consulta de voces Edge inyectan el mismo almacén nativo antes de cargar `edge-tts`.
- El catálogo de voces utiliza un wrapper propio compartido con el Doctor, por lo que ambos verifican el mismo camino de red.
- Los errores TLS o de conexión de Groq se convierten en mensajes controlados; el catálogo de modelos cae al respaldo local sin imprimir un traceback de pywebview.
- El Doctor comprueba e instala `truststore` y documenta la reparación del error `Basic Constraints of CA cert not marked critical` de Python 3.14.

### Funciones macOS y Consultar con investigación real

- Todos los botones del puente pywebview muestran ahora un error visible si el puente aún no está listo o una llamada falla; una inicialización fallida ya no desactiva silenciosamente el resto de la aplicación.
- Play muestra el error real del motor en vez de ignorarlo, y las operaciones asíncronas de tema, voz, velocidad, exportación, adjuntos y actualización quedan protegidas contra rechazos invisibles.
- Copiar y Pegar usan el portapapeles nativo: `pbcopy`/`pbpaste` en macOS y PowerShell seguro en Windows, con texto Unicode y multilínea.
- Consultar fuerza `browser_search` con `tool_choice: required` en los modelos GPT-OSS compatibles, por lo que ya no puede degradarse silenciosamente a chat común.
- Groq conserva las URL reales de `executed_tools.search_results`/anotaciones en una sección **Fuentes** y transmite al usuario los errores HTTP/TLS controlados.
- Exportar MP3 usa también un wrapper con el almacén TLS nativo antes de importar Edge TTS.

### Validación

- 577/577 pruebas aprobadas; Doctor completo, JavaScript y compilación Python correctos.
- Consulta funcional real contra Groq Browser Search aprobada: búsqueda obligatoria, respuesta y sección **Fuentes** con URL reales.
- Exportación MP3 real ejecutada mediante el nuevo wrapper TLS.

## v:26.11.13-20.25

### Paridad visual, IA y voz

- Restaurada la interfaz original completa: ventana maximizada, filas inferiores centradas, selector principal de modelos y Vista previa con espaciado correcto.
- Las acciones de IA muestran un indicador grande centrado; Consultar valida navegación web y capacidades reales del modelo sin repetir la pregunta.
- Los modelos muestran capacidades de chat, razonamiento, búsqueda, visión y documentos; las opciones incompatibles quedan bloqueadas.
- El motor de voz elimina procesos superpuestos al cambiar velocidad, saltar por clic, repetir, detener o cerrar la aplicación.
- Repetir respeta la velocidad actual y vuelve a resaltar cada palabra utilizando las marcas guardadas del audio.
- Play detecta español o inglés, mantiene el sexo elegido y aplica la voz predeterminada correspondiente cuando cambia el idioma.
- Los controles Hombre/Mujer/Español/Inglés filtran estrictamente la lista y conservan una voz manual compatible.
- Vista previa se prepara antes de Play para permitir resaltado y salto por palabra desde la primera lectura.
- Los textos largos generan primero un bloque corto para comenzar a hablar más rápido y luego hasta cinco bloques equilibrados.
- Adjuntar utiliza un único diálogo nativo moderno de pywebview; los archivos aparecen como contexto visible y se envían una sola vez a la IA.

### Validación

- 491 pruebas de la aplicación en verde.
- JavaScript validado con `node --check` y Python con `compileall`.
- Verificación real de consulta web Groq y terminación de procesos de audio.

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
