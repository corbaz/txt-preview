# Diseño

La navegación superior mantiene un grupo izquierdo para **Editor** y **Vista previa**, y crea un grupo derecho para **Configuración** junto al selector global de modelo. La pestaña nueva contiene la credencial, las acciones para guardar/actualizar y una lista detallada de modelos.

La configuración se guarda bajo `%LOCALAPPDATA%\TXT Preview\settings.json`. La API key se protege con DPAPI mediante `ConvertFrom-SecureString`; el modelo y las preferencias no sensibles se almacenan como JSON normal.

La lista se obtiene desde Groq y se combina con un catálogo local de capacidades conocidas. Los modelos desconocidos siguen apareciendo con capacidades conservadoras.

Los adjuntos de texto se envían como documentos de contexto. Las imágenes se codifican como URL de datos para el contenido multimodal de Qwen. La búsqueda web agrega la herramienta `browser_search` solamente en modelos compatibles.

El botón **Adjuntar archivos** pertenece a la fila principal de acciones, después de **Pegar**. El catálogo de capacidades controla su visibilidad: se muestra para modelos de chat que aceptan texto o imágenes y se oculta para audio, TTS, seguridad u otros modelos no compatibles.
