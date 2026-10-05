# Especificación actual

1. La interfaz ofrece las vistas **Editor** y **Vista previa**.
2. La vista previa convierte Markdown a HTML con tema claro u oscuro.
3. Las acciones de IA operan de forma asíncrona y muestran su estado.
4. La lectura permite elegir idioma, género y voz.
5. La lectura permite reproducir, pausar, continuar y detener.
6. La velocidad puede ajustarse entre `0,50x` y `2,00x`.
7. El texto pronunciado se resalta en la vista previa.
8. La aplicación permite exportar PDF y MP3.
9. Ninguna API key queda escrita en el código fuente.

## Verificación

- El script supera el análisis sintáctico de PowerShell.
- Las pruebas Python del generador Edge finalizan correctamente.
- Una búsqueda de secretos no encuentra valores que comiencen con `gsk_`.
