# Diseño actual

La aplicación está implementada en un script PowerShell WinForms. Un control de pestañas sin encabezado muestra el editor y la vista previa; botones propios controlan la navegación.

Las solicitudes de IA usan la API compatible con OpenAI de Groq. La credencial se obtiene de configuración externa y nunca del código fuente.

La lectura local usa `System.Speech.Synthesis.SpeechSynthesizer`. La lectura Edge genera bloques MP3 en segundo plano, los reproduce con `ffplay` y usa eventos `WordBoundary` para sincronizar el resaltado.
