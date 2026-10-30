# Tareas: catálogo resiliente de voces Edge

## Fase 1 — RED

- [x] Añadir tests del parseo y resultado válido.
- [x] Añadir tests del reintento y actualización de caché.
- [x] Añadir tests de recuperación desde caché y caché dañada.
- [x] Añadir test de dependencia ausente sin uso de caché.
- [x] Añadir contrato de detección de Python independiente de `$LASTEXITCODE`.
- Validación: RED observado con 5 fallos y 1 error antes de implementar.

## Fase 2 — GREEN

- [x] Implementar detección acotada de Python por `Process.ExitCode`.
- [x] Implementar consulta acotada y parseo del catálogo.
- [x] Implementar escritura atómica y lectura validada de caché.
- [x] Integrar reintento, fallback y mensajes visibles.
- Validación: 6 tests nuevos y parser en verde.

## Fase 3 — Integración y publicación

- [x] Ejecutar la suite completa: 123 tests en verde.
- [x] Ejecutar smoke test con el Python real: 92 Edge, 5 Windows y 23 en Español/Hombre.
- [x] Actualizar README y CHANGELOG.
- [x] Actualizar `VERSION` con horario de Buenos Aires: `v:26.10.30-15.28`.
- [x] Revisar diff y secretos; incluir sólo archivos del cambio.
- [x] Commit y push de la rama actual y `main` según el flujo existente.

## Dependencias

- Python 3.15 y `edge-tts` instalados para el smoke real.
- PowerShell 7 para parser, WinForms y pruebas de integración.

## Forecast

Revisión mediana: aproximadamente 180–260 líneas de aplicación, tests y documentación SDD.
