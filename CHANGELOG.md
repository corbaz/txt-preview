# Historial de cambios

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
