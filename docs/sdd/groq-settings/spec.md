# Especificación

1. **Editor** y **Vista previa** permanecen a la izquierda; **Configuración** aparece a la derecha.
2. La API key se muestra en un campo enmascarado y se almacena cifrada para el usuario de Windows.
3. **Actualizar modelos** valida la key y consulta la lista activa de Groq.
4. La lista informa ID, proveedor, contexto y capacidades conocidas.
5. El modelo seleccionado se guarda y es utilizado por todas las acciones de IA.
6. Los modelos GPT-OSS compatibles pueden activar búsqueda web.
7. Qwen 3.8 permite adjuntar hasta tres imágenes compatibles.
8. Los modelos de texto admiten adjuntos de texto incorporados como documentos de contexto.
9. La interfaz impide adjuntar tipos no compatibles con el modelo seleccionado.
10. La esquina inferior derecha muestra la versión en formato `v:yy.mm.dd-HH.mm`, calculada en horario de Buenos Aires al preparar la versión.
11. El repositorio no contiene valores con prefijo `gsk_` ni archivos de configuración del usuario.

## Verificación

- Pruebas estáticas para selección de modelo, credenciales, capacidades y versión.
- Análisis sintáctico de PowerShell.
- Pruebas Python existentes.
