# Configuración de Groq

## Objetivo

Añadir una pestaña **Configuración** a la derecha de la navegación principal para que cada usuario cargue su API key, consulte los modelos disponibles y elija el modelo usado por las acciones de IA.

## Alcance de la primera implementación

- Guardar la API key fuera del repositorio mediante protección de Windows.
- Consultar dinámicamente `/openai/v1/models`.
- Mostrar modelo, proveedor, contexto y capacidades conocidas.
- Elegir el modelo activo.
- Identificar soporte de texto, búsqueda web, visión, archivos, audio, TTS y seguridad.
- Adjuntar documentos de texto o imágenes cuando el modelo lo permita.
- Mostrar una versión `v:yy.mm.dd-HH.mm` con horario de Buenos Aires en la esquina inferior derecha.

## Fuera de alcance

- Conversaciones con historial persistente.
- Carga de archivos al endpoint Batch.
- Administración de facturación o límites de Groq.
