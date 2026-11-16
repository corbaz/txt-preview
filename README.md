# TXT Preview

Aplicación de escritorio para **Windows y macOS**, con una sola base de código (Python + pywebview) que en ambas plataformas ofrece lo mismo: un editor de texto, una vista previa Markdown, herramientas de IA (consultar, resumir, corregir y traducir con [Groq](https://groq.com) o con tus suscripciones de Claude, OpenAI y Gemini mediante bridges locales), lectura en voz alta con voces neuronales de Edge y resaltado de la palabra que se lee, y exportación a PDF y MP3.

Las mejoras publicadas en cada versión se detallan en [`CHANGELOG.md`](CHANGELOG.md).

## Qué podés hacer

- Escribir o pegar texto y verlo formateado en **Vista previa**.
- **Consultar IA**: tu consulta queda en el Editor y la respuesta aparece en **Vista previa**. Con `openai/gpt-oss-20b` o `openai/gpt-oss-120b`, la aplicación obliga a Groq a investigar en la web y muestra las fuentes devueltas por el servicio.
- **Resumir**, **Corregir gramática y ortografía** y **Traducir** inglés ↔ español reemplazan el texto del Editor.
- En la barra de IA, arriba del Editor: **Consultar IA**, **Resumir**, **Corregir Gramática y Ortografía**, **Traducir EN→ES** y **ES→EN**, búsqueda web (en los modelos que navegan, activada por defecto) y **Adjuntar archivos**: texto, PDF, Word (.docx), PowerPoint (.pptx) e imágenes (hasta 3, en los modelos con visión). Los formatos antiguos .doc y .ppt **no están soportados**: guardalos primero como .docx o .pptx.
- Abrir los links de las respuestas en la pestaña **Navegador**, dentro de la misma ventana.
- Las marcas internas de cita de búsqueda web (como `【2†L58-L62】`) se limpian, pero las URL reales que Groq devuelve se conservan en una sección **Fuentes**.
- Escuchar el resultado con **voces neuronales de Edge**, con pausa, **Repetir** del último audio, control de velocidad y resaltado de la palabra que se lee. Si seleccionás un fragmento en la Vista previa, **Play** lee solo esa selección; si hacés clic en una palabra, lee desde ahí hasta el final.
- Exportar a **PDF** y **MP3**, copiar como Markdown o texto plano. Copiar y Pegar usan el portapapeles nativo (`pbcopy`/`pbpaste` en macOS), no la API limitada de WKWebView. Estas acciones y **Play** usan lo que muestra la Vista previa: la respuesta de la IA si hay una, o el texto del Editor.
- Elegir tema claro u oscuro.

## Instalación

Necesitás [Git](https://git-scm.com/downloads), Python 3.10 o superior, FFmpeg y algunos paquetes de Python (`pywebview`, `markdown`, `pymupdf`, `edge-tts`, `truststore`). El instalador de cada sistema se encarga de todo lo que falte; `truststore` hace que Python use el almacén de certificados nativo (Keychain en macOS / CryptoAPI en Windows), en macOS la ventana usa el WKWebView que ya trae el sistema, y en Windows el doctor verifica que esté el runtime WebView2.

### macOS

```bash
git clone https://github.com/corbaz/txt-preview.git
cd txt-preview
./install.sh
./run.sh
```

Si ya lo tenías clonado, en vez del clone hacé `git pull` y volvé a correr `./install.sh`. Los scripts ya vienen con permiso de ejecución; si igual da `permission denied`, corré una vez `chmod +x run.sh install.sh` o usá `bash install.sh`.

Para actualizar, reparar dependencias y abrir la app con un solo alias (clone en `~/txt-preview`):

```bash
echo 'alias txtpreview="cd ~/txt-preview && git pull --ff-only -q && bash install.sh && bash run.sh"' >> ~/.zshrc
source ~/.zshrc
```

Después solo ejecutá `txtpreview`.

`install.sh` hace esto:

1. Pide Homebrew: si no lo tenés, te muestra el comando para instalarlo y te pide volver a ejecutar el script.
2. Instala Python y FFmpeg con `brew install python` y `brew install ffmpeg` (solo si faltan).
3. Instala los paquetes de la app: `pip install --user -r app/requirements.txt edge-tts`, incluido `truststore` para las conexiones TLS de Groq y Edge TTS.
4. Corre el doctor de dependencias.

Todo el detalle queda en `install.log`, en la misma carpeta; por pantalla solo salen los errores, las advertencias y los avisos (por ejemplo, el informe del doctor cuando falta algo).

Si Python 3.14 muestra `CERTIFICATE_VERIFY_FAILED` o `Basic Constraints of CA cert not marked critical`, actualizá el clon y repetí el instalador; no desactives la verificación TLS:

```bash
git pull
./install.sh
python3 app/doctor.py
```

### Windows

Abrí **PowerShell** (no hace falta como administrador) y pegá este comando:

```powershell
$d = "$env:LOCALAPPDATA\txt-preview"; if (Test-Path "$d\.git") { git -C $d pull --ff-only } else { git clone https://github.com/corbaz/txt-preview.git $d }; powershell -NoProfile -ExecutionPolicy Bypass -File "$d\install.ps1"
```

El mismo comando sirve para reinstalar o reparar una instalación existente. `install.ps1` hace esto:

1. Clona la app en `%LOCALAPPDATA%\txt-preview` (o la actualiza si ya estaba).
2. Instala lo que falte: Python 3.12, los paquetes de la app (`app\requirements.txt` y `edge-tts`) y FFmpeg, todo vía `winget`.
3. Corre el doctor de dependencias.
4. Crea el acceso directo **TXT Preview** en el escritorio y abre la aplicación.

Después podés abrirla desde el acceso directo del escritorio o ejecutando `run.cmd` desde el clone.

### Doctor

El doctor comprueba que todo esté instalado y explica cómo arreglar lo que falte:

```bash
python app/doctor.py            # en macOS puede ser: python3 app/doctor.py
```

Imprime una tabla con un check por dependencia (`git`, `python`, `pip`, `pywebview`, `markdown`, `pymupdf`, `edge-tts`, `ffmpeg`, `webview-runtime`), el detalle de cada una y, si falta algo, la **Solución** con el comando exacto.

Para una IA o un script hay tres modos:

- `--json`: salida en JSON, pensada para que un agente la lea sin ambigüedad.
- `--fix`: intenta instalar lo que falta. Puede instalar con `pip` los paquetes de Python (`pywebview`, `markdown`, `pymupdf`, `edge-tts`); el resto (git, Python, FFmpeg, WebView2) recibe la sugerencia con su comando de `brew`/`winget`.
- Códigos de salida: `0` todo OK, `1` falta algo (sin `--fix`), `2` corrió `--fix` y sigue faltando algo.

Un agente de IA puede correr el doctor, parsear el `--json` y ejecutar el campo `fix` de cada check que salga con `"ok": false`. Ejemplo de ese JSON:

```json
{
  "ok": false,
  "platform": "macos",
  "checks": [
    { "id": "edge-tts", "ok": false,
      "detail": "Falta el paquete de Python edge-tts (voces Edge en línea).",
      "fix": "python -m pip install --user edge-tts" },
    { "id": "python", "ok": true,
      "detail": "Python 3.12.1 (python3)", "fix": null }
  ]
}
```

### Resumen de requisitos

| Requisito | Detalle | Quién lo instala |
|-----------|---------|------------------|
| Git | Lo usa clonar y actualizar con `git pull`. | Vos (una vez): `brew install git` / `winget install --id Git.Git -e` |
| Python 3.10+ | Corre la app y sus pruebas. | El instalador de tu sistema |
| FFmpeg | Reproduce las voces Edge y exporta MP3. | El instalador: `brew install ffmpeg` / `winget install --id Gyan.FFmpeg -e` |
| Paquetes de Python | `pywebview`, `markdown`, `pymupdf`, `edge-tts`, `truststore`. | El instalador, o `python app/doctor.py --fix` |
| Runtime de web | macOS trae WKWebView integrado (nada que instalar); en Windows el doctor verifica el WebView2 runtime y sugiere `winget install --id Microsoft.EdgeWebView -e` si falta. | Automático / doctor |

## Primeros pasos

1. Creá una API key gratuita en [console.groq.com/keys](https://console.groq.com/keys).
2. Guardala desde **Configuración → API key de Groq** (almacenamiento seguro del sistema) o definí `GROQ_API_KEY` antes de abrir la app.
3. Elegí `openai/gpt-oss-120b` o `openai/gpt-oss-20b` para **Consultar IA** con investigación web obligatoria; la app rechaza con un mensaje claro los modelos sin búsqueda.
4. En el **Editor**, escribí algo y probá **Consultar IA**: la respuesta investigada y sus fuentes aparecen en **Vista previa**.
5. Con la respuesta en Vista previa podés tocar **Play** para escucharla con una voz Edge, adjuntar archivos en el Editor para la próxima consulta, o exportar el resultado a **PDF** o **MP3**.

### Modelos por suscripción (bridges locales)

Además de Groq, la app puede usar tus suscripciones de Claude, OpenAI (Codex) y Gemini a través de los bridges del repo `web-chat`. Cada bridge escucha solo en `127.0.0.1`, así que nadie de la red puede usarlo, y pide usuario y contraseña.

| Bridge | Puerto | Variable de contraseña |
|--------|--------|------------------------|
| Claude | 4098 | `CLAUDE_BRIDGE_PASSWORD` |
| Codex (OpenAI) | 4094 | `CODEX_BRIDGE_PASSWORD` |
| Gemini | 4092 | `GEMINI_BRIDGE_PASSWORD` |

1. Arrancá los bridges que quieras usar y definí sus contraseñas en las variables de entorno (`CLAUDE_BRIDGE_PASSWORD`, `CODEX_BRIDGE_PASSWORD`, `GEMINI_BRIDGE_PASSWORD`) o dejá que la app lea el `password.txt` que genera cada bridge cuando no le pasás ninguna (en Windows, en `%LOCALAPPDATA%\prompting\<bridge>\`; en macOS, en `~/Library/Application Support/prompting/<bridge>/`). No hace falta una API key de Groq para usarlos.
2. El ruteo de los modelos de los bridges ya está integrado en la lógica de la app; que sus modelos aparezcan en el selector, agrupados por proveedor, es parte de los próximos pasos de integración.

## Actualizar

Como la app corre directo del clone en los dos sistemas, actualizar es un `git pull` en la carpeta `txt-preview` — nada más. Después de una actualización grande, si el doctor detecta una dependencia nueva que falta, corré `./install.sh` (macOS) o `install.ps1` (Windows) de nuevo y listo. La app también va a incorporar un chequeo de actualizaciones dentro de la ventana (en desarrollo).

## Para desarrolladores

La app vive en [`app/`](app/): `main.py` arranca la ventana con pywebview, `txt_core/` tiene la lógica compartida y `www/` la interfaz (HTML/CSS/JS). Las pruebas corren igual en los dos sistemas:

```bash
python -m unittest discover -s app/tests
```

Cada push pasa por la matriz de CI de Windows y macOS ([`.github/workflows/cross-platform.yml`](.github/workflows/cross-platform.yml)), que corre el doctor y la suite de pruebas en los dos sistemas: así un cambio hecho en Windows no rompe la Mac del otro usuario.

[![cross-platform](https://github.com/corbaz/txt-preview/actions/workflows/cross-platform.yml/badge.svg)](https://github.com/corbaz/txt-preview/actions/workflows/cross-platform.yml)

La versión anterior de PowerShell está documentada al final de este README. Las decisiones y tareas de diseño se guardan en [`docs/sdd/`](docs/sdd/) y [`odd/tasks/`](odd/tasks/).

### Seguridad

Las credenciales no forman parte del código ni del repositorio. No agregues archivos `.env`, API keys ni contraseñas al control de versiones.

---

## Versión anterior (solo Windows)

Antes de la versión multiplataforma, TXT Preview era un único script de PowerShell 7 con WinForms: [`txt.ps1`](txt.ps1). Esa versión **sigue siendo funcional en Windows** (se ejecuta con `powershell -NoProfile -ExecutionPolicy Bypass -File .\txt.ps1` desde un clon) y desaparecerá cuando se complete el cambio a la app Python; en macOS nunca corrió.

Su instalación usaba el mismo comando de clonación de arriba, pero terminaba instalando ese script y sus componentes de Windows (PowerShell 7, WebView2, PdfPig). Desde que la app es multiplataforma, el mismo `install.ps1` instala la versión Python, que es la documentada en las secciones de arriba. La documentación completa de la versión anterior está en el historial de este archivo ([`CHANGELOG.md`](CHANGELOG.md) detalla los cambios de ambas).
