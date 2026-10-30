# Propuesta: catálogo resiliente de voces Edge

## Problema

TXT consulta `python -m edge_tts --list-voices` una sola vez durante el inicio. Si esa consulta falla de forma transitoria, el error se descarta y durante toda la sesión sólo aparecen las voces locales de Windows. Además, la detección de Python depende de `$LASTEXITCODE`, cuyo valor puede no quedar disponible al iniciar PowerShell desde algunos hosts de terminal.

## Objetivo

Mantener disponibles las últimas voces Edge conocidas cuando la consulta en línea falla temporalmente, informar claramente el modo degradado y hacer que la detección de Python no dependa del estado global de la terminal.

## Alcance

- Detectar Python mediante el código de salida del proceso ejecutado.
- Consultar el catálogo Edge con salida y error capturados y un tiempo máximo.
- Reintentar una vez los fallos transitorios.
- Guardar el último catálogo válido bajo `%LOCALAPPDATA%\TXT Preview`.
- Recuperar ese catálogo cuando Edge no responde temporalmente.
- No usar la caché si falta Python o el módulo `edge_tts`.
- Mostrar una advertencia cuando se usa la caché o no hay catálogo disponible.
- Documentar diagnóstico, recuperación y ubicación de la caché.

## Fuera de alcance

- Distribuir una lista de voces fija dentro del repositorio.
- Permitir síntesis Edge sin conexión a Internet.
- Cambiar los filtros de idioma o género.
- Cambiar la instalación de Python, FFmpeg o `edge-tts`.

## Riesgos

- Un catálogo guardado puede contener una voz retirada posteriormente; la consulta en línea seguirá teniendo prioridad en cada inicio.
- Los reintentos pueden demorar el inicio; cada proceso queda acotado por timeout y sólo se hace un reintento.
- Una caché dañada debe ignorarse sin impedir el uso de voces Windows.

## Plan de validación

- Tests TDD para catálogo en línea, reintento, caché válida, caché dañada y módulo ausente.
- Test de detección de Python sin `$LASTEXITCODE`.
- Suite completa `python -m unittest discover -s tests`.
- Parser de PowerShell sin errores.
- Smoke test real que confirme 92 voces Edge, 5 Windows y escritura de caché.
