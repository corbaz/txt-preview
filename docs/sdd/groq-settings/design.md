# Diseño

La navegación superior mantiene un grupo izquierdo para **Editor** y **Vista previa**, y crea un grupo derecho para **Configuración** junto al selector global de modelo. La pestaña nueva contiene la credencial, las acciones para guardar/actualizar y una lista detallada de modelos.

La configuración se guarda bajo `%LOCALAPPDATA%\TXT Preview\settings.json`. La API key se protege con DPAPI mediante `ConvertFrom-SecureString`; el modelo y las preferencias no sensibles se almacenan como JSON normal.

La lista se obtiene desde Groq y se combina con un catálogo local de capacidades conocidas. Los modelos desconocidos siguen apareciendo con capacidades conservadoras.

Los adjuntos de texto se envían como documentos de contexto. Las imágenes se codifican como URL de datos para el contenido multimodal de Qwen. La búsqueda web agrega la herramienta `browser_search` solamente en modelos compatibles.

El botón **Adjuntar archivos** pertenece a la fila principal de acciones, después de **Pegar**. El catálogo de capacidades controla su visibilidad: se muestra para modelos de chat que aceptan texto o imágenes y se oculta para audio, TTS, seguridad u otros modelos no compatibles.

El Editor reserva una franja superior llamada **Contexto IA**. Allí se muestra **Usar web** únicamente para modelos compatibles, se enumeran con el texto “Se enviarán a Groq” todos los adjuntos activos y se permite quitarlos. Configuración queda limitada a credenciales, actualización del catálogo e información de modelos.

La validación de entrada considera dos fuentes equivalentes de contexto: el texto del Editor y los adjuntos activos. Las acciones de IA continúan si cualquiera de las dos contiene información y solo se bloquean cuando ambas están vacías.

El layout de la botonera inferior conserva las coordenadas relativas de cada fila y calcula un desplazamiento común para centrarla. El cálculo final se repite en el evento `Shown`, cuando WinForms ya informa la visibilidad y el ancho efectivos de los controles, además de ejecutarse ante cambios posteriores de tamaño o capacidades del modelo.

La acción **Limpiar chat** restablece conjuntamente el texto y la colección de adjuntos, y actualiza de inmediato la franja de contexto. La paleta incorpora el color semántico `Notice`: verde claro en tema oscuro y verde profundo en tema claro. Se aplica a los mensajes de estado y al resumen cuando existen adjuntos, mientras que el estado vacío permanece atenuado.

Configuración incorpora actualización desde el propio clon. Al entrar por primera vez ejecuta `git fetch origin main`, lee `VERSION` desde `FETCH_HEAD` y lo compara con la versión local sin modificar los archivos de trabajo. Si existe una versión posterior, **Actualizar ahora** verifica que la rama sea `main`, exige un árbol limpio y ejecuta `git pull --ff-only origin main`. Cualquier divergencia o cambio local detiene la operación en lugar de sobrescribir contenido. Como el proceso en ejecución conserva el código ya cargado, el usuario debe reiniciar la aplicación después de una actualización correcta.
