# Historial de cambios

## v:26.11.14-12.37

### Inicio y barra de contexto como en la versión PowerShell

- Cada inicio arranca en Tema: Oscuro, velocidad 1,00x y la voz Hombre · Español (es-CR-JuanNeural); ya no se restauran el tema, la velocidad ni la voz de la sesión anterior.
- La barra de contexto muestra solo las capacidades que el modelo tiene, y oculta la casilla de búsqueda web y el botón Adjuntar archivos cuando no aplican.
- Al cambiar a un modelo sin visión se quitan las imágenes adjuntas.

## v:26.11.14-12.33

### Lectura de la Vista previa y Navegador en macOS

- Play lee lo que muestra la Vista previa (la respuesta de la IA, o el Editor si no hay respuesta) como texto plano y pasa a esa pestaña; sin contenido avisa «No hay contenido en Vista previa para leer.». Pausar y Repetir también muestran la Vista previa.
- macOS: el navegador integrado no llegaba a crearse por un error en su componente nativo, y por eso solo funcionaba «Abrir en navegador». Corregido; si aun así falla, el motivo aparece en la barra de estado.

## v:26.11.14-12.11

### Modelos de los bridges

- Al cambiar de modelo ya no aparece el mensaje «Modelo: Groq · …» con el proveedor equivocado para los modelos de Claude, Codex o Gemini; la versión PowerShell no muestra ese mensaje.

## v:26.11.14-12.03

### Consultar, Vista previa y exportaciones como en la versión PowerShell

- Consultar vuelve a mostrar la respuesta: antes la Vista previa repetía la pregunta y la respuesta se perdía.
- La Vista previa muestra la barra «Respuesta de la IA. Tu consulta sigue en el Editor.» con «Llevar al editor» y «Ver el editor».
- Copiar, PDF, MP3 y Play trabajan sobre lo que muestra la Vista previa (la respuesta de la IA o el texto del Editor), aunque la pestaña no se haya abierto.
- Consultar usa la búsqueda web solo si la casilla está marcada, y funciona con cualquier modelo de chat, incluidos los bridges.
- Corregir, Resumir, Traducir y Pegar reemplazan el Editor de forma que Ctrl+Z recupera el texto anterior.
- Un pedido a la IA detiene la lectura en curso y descarta el audio de Repetir.
- «Buscar actualización» y «Actualizar ahora» vuelven a funcionar, igual que el aviso de actualización al iniciar.
- Los mensajes de estado usan amarillo para advertencias y rojo para errores; la vista previa vacía muestra «No hay contenido para mostrar.».
- La ventana se titula «Corrector de Prompt» y tiene el mismo tamaño mínimo que la original.

## v:26.11.14-11.55

### Exportar PDF y MP3 eligiendo la carpeta en un árbol

- PDF y MP3 muestran un árbol de carpetas tipo Explorador para elegir dónde guardar, tanto en `txt.ps1` como en la app Python (en macOS, el selector de carpetas del sistema).
- El archivo se nombra solo (`lectura-AAAAMMDD-HHMM.pdf` / `.mp3`) y nunca pisa uno existente: agrega `-2`, `-3`, etc. La siguiente exportación arranca en la última carpeta usada.

### La app Python se comporta como la versión PowerShell

- Cada inicio arranca en `openai/gpt-oss-120b`, sin restaurar el último modelo.
- «Actualizar voces» aparece solo cuando Edge rechaza un `edge-tts` desactualizado (HTTP 403) y actualiza el paquete con `pip`, mostrando la versión resultante.

## v:26.11.14-11.39

### Configuración igual a la versión PowerShell

- La pestaña Configuración replica la original: versión y actualización arriba a la derecha, API key con Guardar y Actualizar modelos, versión de edge-tts, contraseñas y estado de los bridges Claude, Codex y Gemini, y la lista de modelos con columnas Modelo, Proveedor, Contexto, Chat, Visión, Web, Adjuntos y Funciones.
- Las contraseñas de los bridges se guardan cifradas (en Windows, en el mismo campo que usa `txt.ps1`; en macOS, en el llavero) y al salir de la casilla se vuelve a comprobar el bridge.
- Los bridges se comprueban aunque no haya API key de Groq: una suscripción sola es una configuración válida.
- El selector de modelo muestra «Groq · modelo» y «Bridge · modelo», solo con modelos de chat, como el original.

## v:26.11.14-11.32

### Navegador integrado como en la versión PowerShell

- Los links de la Vista previa ya no reemplazan la aplicación entera: se abren en la pestaña Navegador.
- La pestaña Navegador usa una vista web nativa (WebView2 en Windows, WKWebView en macOS) en lugar de un `iframe`, que la mayoría de los sitios bloqueaba.
- Barra igual a la original: Atrás, Adelante, dirección, Ir y Abrir en navegador. La dirección acepta URLs, dominios sueltos y palabras (búsqueda en Google); los links `target="_blank"` quedan dentro de la pestaña.
- La interfaz se sirve sin caché y con versiones en sus archivos: después de actualizar ya no queda un `index.html` viejo mezclado con JavaScript nuevo.

## v:26.11.14-11.06

### Consultar y Resumir con web vuelven a funcionar; una sola API key para ambas apps

- Las consultas con búsqueda web usan `tool_choice: "auto"`, igual que `txt.ps1`. Con `"required"`, Groq devolvía HTTP 400 (`tool_use_failed`) cada vez que el modelo respondía sin buscar.
- Los errores HTTP de Groq muestran el motivo que devuelve la API (por ejemplo, el límite de tokens por minuto en HTTP 429) en lugar de solo el código.
- En Windows, la app Python y `txt.ps1` comparten `settings.json`: la API key guardada en la Configuración de cualquiera de las dos es la que usan ambas (`EncryptedApiKey`), en lugar de caer a la variable de entorno `GROQ_API_KEY`.
- Guardar la configuración en `txt.ps1` conserva el modelo, el tema, la voz y la velocidad de la app Python.

## v:26.11.14-09.47

### Mensajes MP3 legibles en cualquier configuración regional

- El wrapper de exportación MP3 escribe ahora sus mensajes en UTF-8 explícito, de modo que "la síntesis falló" y otros avisos con acentos no se corrompen en Windows con configuración regional distinta a la española (fallo detectado por CI).

## v:26.11.14-09.10

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

- 579/579 pruebas de la aplicación aprobadas; Doctor completo, JavaScript y compilación Python correctos.
- Consulta funcional real contra Groq Browser Search aprobada: búsqueda obligatoria, respuesta y sección **Fuentes** con URL reales.
- Exportación MP3 real ejecutada mediante el nuevo wrapper TLS.
- CI macOS usa cifrado inyectado y almacenamiento temporal en sus pruebas, sin tocar ni contaminar el Keychain real del runner.
- La suite PowerShell acepta el separador de miles propio de la configuración regional (`131.072` o `131,072`) sin relajar las columnas ni capacidades verificadas.

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
