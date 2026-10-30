# Especificación: catálogo resiliente de voces Edge

## Requisitos

1. TXT **MUST** ejecutar el Python candidato y comprobar el `ExitCode` del proceso, sin depender de `$LASTEXITCODE`.
2. La consulta `edge_tts --list-voices` **MUST** capturar `stdout`, `stderr` y código de salida.
3. Cada consulta **MUST** finalizar dentro de un tiempo acotado; un proceso excedido **MUST** terminarse.
4. TXT **MUST** reintentar una vez una consulta fallida antes de degradarse.
5. Un resultado en línea **MUST** considerarse válido sólo si contiene al menos una voz Edge compatible y parseable.
6. Un catálogo válido **MUST** guardarse de forma atómica en `%LOCALAPPDATA%\TXT Preview\edge-voices.json`.
7. Si la consulta falla temporalmente, TXT **MUST** cargar el último catálogo válido guardado.
8. Si falta Python o `edge_tts`, TXT **MUST NOT** presentar voces de una caché que no podrá sintetizar.
9. Una caché ausente o dañada **MUST NOT** impedir que TXT muestre las voces Windows.
10. Cuando se use la caché, TXT **MUST** mostrar una advertencia visible indicando que se usa el último catálogo guardado.
11. Cuando no exista catálogo Edge utilizable, TXT **MUST** mostrar un error accionable y conservar las voces Windows.
12. La consulta en línea **SHOULD** tener prioridad en cada inicio para refrescar automáticamente la caché.

## Escenarios

### Consulta normal

**Given** Python y `edge_tts` funcionan \
**When** TXT inicia \
**Then** muestra el catálogo recibido y lo guarda como último catálogo válido.

### Fallo transitorio con recuperación

**Given** existe un catálogo válido guardado \
**And** la consulta en línea falla en sus dos intentos \
**When** TXT inicia \
**Then** muestra las voces Edge guardadas junto con las voces Windows \
**And** avisa que está usando el último catálogo guardado.

### Primer intento fallido

**Given** la primera consulta falla y la segunda responde con voces válidas \
**When** TXT inicia \
**Then** usa el resultado en línea \
**And** actualiza la caché \
**And** no presenta una advertencia de modo degradado.

### Dependencia ausente

**Given** Python responde que no existe el módulo `edge_tts` \
**When** TXT inicia \
**Then** no carga la caché Edge \
**And** conserva las voces Windows \
**And** muestra cómo reparar la dependencia.

### Caché dañada

**Given** la consulta en línea falla y `edge-voices.json` no es válido \
**When** TXT inicia \
**Then** ignora la caché \
**And** conserva las voces Windows \
**And** informa que no pudo cargar el catálogo Edge.

## Criterios de aceptación

- Los tests reproducen el fallo anterior y pasan con la implementación nueva.
- Un fallo transitorio simulado conserva voces Edge desde la caché.
- El smoke real informa el catálogo Edge esperado y crea una caché válida.
- No hay errores de parser ni regresiones en la suite completa.
