# Especificación

1. **Editor** y **Vista previa** permanecen a la izquierda; **Configuración** aparece a la derecha.
2. El selector del modelo activo permanece visible en la barra superior, junto a **Configuración**, sin depender de la pestaña abierta.
3. La API key se muestra en un campo enmascarado y se almacena cifrada para el usuario de Windows.
4. **Actualizar modelos** valida la key y consulta la lista activa de Groq.
5. La lista informa ID, proveedor, contexto y capacidades conocidas.
6. El modelo seleccionado se guarda y es utilizado por todas las acciones de IA.
7. Los modelos GPT-OSS compatibles pueden activar búsqueda web desde una franja de contexto situada al comienzo del Editor.
8. **Adjuntar archivos** aparece inmediatamente después de **Pegar** solamente cuando el modelo activo admite documentos o imágenes.
9. La franja superior del Editor enumera los archivos que serán enviados a Groq y permite quitarlos; estos controles no aparecen dentro de Configuración.
10. Qwen 3.8 permite adjuntar hasta tres imágenes compatibles.
11. Los modelos de texto admiten adjuntos de texto incorporados como documentos de contexto.
12. La interfaz impide adjuntar tipos no compatibles con el modelo seleccionado.
13. La esquina inferior derecha muestra la versión en formato `v:yy.mm.dd-HH.mm`, calculada en horario de Buenos Aires al preparar la versión.
14. El repositorio no contiene valores con prefijo `gsk_` ni archivos de configuración del usuario.
15. Consultar, resumir, corregir y traducir pueden ejecutarse con el Editor vacío cuando existe al menos un adjunto; sin texto ni adjuntos, la solicitud se bloquea.

## Verificación

- Pruebas estáticas para selección de modelo, credenciales, capacidades y versión.
- Análisis sintáctico de PowerShell.
- Pruebas Python existentes.
