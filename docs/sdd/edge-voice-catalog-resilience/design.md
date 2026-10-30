# Diseño: catálogo resiliente de voces Edge

## Componentes afectados

- `txt.ps1`: detección de Python, consulta, parseo, persistencia y carga del catálogo.
- `tests/test_edge_voice_catalog.py`: contratos y escenarios TDD.
- `README.md`: funcionamiento y resolución de problemas.
- `CHANGELOG.md` y `VERSION`: publicación de la mejora.

## Contratos

`Test-PythonCandidate` inicia el ejecutable con `--version`, espera con timeout y devuelve un booleano basado en `Process.ExitCode`.

`ConvertFrom-EdgeVoiceCatalogText` transforma la salida tabular de `edge_tts` en objetos con `Name`, `Culture`, `Gender` y `DisplayName`. Un catálogo vacío no es válido.

`Invoke-EdgeVoiceCatalogProcess` ejecuta `python -m edge_tts --list-voices`, lee ambas salidas en forma asíncrona y devuelve `ExitCode`, `Output` y `Error`. Si vence el tiempo máximo, termina el árbol del proceso y devuelve un error de timeout.

`Get-EdgeVoiceCatalog` realiza hasta dos intentos. Ante un resultado válido, lo persiste y devuelve `Source = Online`. Ante un fallo no atribuible a dependencia ausente, intenta leer caché y devuelve `Source = Cache`. En otro caso devuelve `Source = None` con un mensaje accionable.

## Persistencia

La caché se guarda en `%LOCALAPPDATA%\TXT Preview\edge-voices.json` con versión de esquema, fecha de actualización y colección de voces. La escritura usa un archivo temporal en el mismo directorio y `Move-Item -Force` para evitar archivos parciales. La caché no contiene secretos.

## Integración con la interfaz

La carga ocurre antes de completar el selector de voces. El resultado alimenta las tablas ya existentes y no cambia sus filtros. La advertencia queda preparada durante el inicio y se presenta con `Show-Message` en `Form.Shown`, cuando los controles y el tema ya están listos.

## Testing

- Los procesos se encapsulan para poder sustituir la consulta por resultados deterministas.
- Los tests usan directorios temporales y cubren online, reintento, caché, corrupción y módulo ausente.
- Un contrato estático comprueba que `Find-PythonCommand` no usa `$LASTEXITCODE`.
- La suite completa y el parser protegen las rutas no relacionadas.

## Riesgos y decisiones

- Se conserva la última lista indefinidamente porque sólo se usa tras intentar actualizarla; esto maximiza disponibilidad sin impedir el refresco.
- No se carga caché cuando falta el módulo: mostrar voces imposibles de reproducir sería engañoso.
- Dos intentos equilibran recuperación y tiempo de inicio; cada intento queda acotado.
