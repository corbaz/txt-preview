# Diseño

La navegación superior mantiene un grupo izquierdo para **Editor** y **Vista previa**, y crea un grupo derecho para **Configuración**. La pestaña nueva contiene campos de credencial y modelo, acciones para guardar/actualizar y una lista detallada de modelos.

La configuración se guarda bajo `%LOCALAPPDATA%\TXT Preview\settings.json`. La API key se protege con DPAPI mediante `ConvertFrom-SecureString`; el modelo y las preferencias no sensibles se almacenan como JSON normal.

La lista se obtiene desde Groq y se combina con un catálogo local de capacidades conocidas. Los modelos desconocidos siguen apareciendo con capacidades conservadoras.

Los adjuntos de texto se envían como documentos de contexto. Las imágenes se codifican como URL de datos para el contenido multimodal de Qwen. La búsqueda web agrega la herramienta `browser_search` solamente en modelos compatibles.
