#!/usr/bin/env bash
# Instalador de TXT Preview para macOS.
# Uso después de clonar:
#   bash install.sh
#   SKIP_INSTALL=1 bash install.sh    # solo corre el doctor
# Instala Homebrew (si falta), Python, FFmpeg, los paquetes de la app y el
# dictado local (paquetes y modelo, unos 750 MB en la carpeta models), corre el
# doctor y muestra cómo ejecutar la app. No necesita sudo.
# El detalle queda en install.log (misma carpeta); por pantalla solo salen
# los errores, las advertencias y los avisos.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$REPO/app"
LOG="$REPO/install.log"
: > "$LOG"

# log: solo al archivo. info/warn/fail: al archivo y a la pantalla.
log() { echo "$*" >> "$LOG"; }
info() { echo "$*" | tee -a "$LOG"; }
warn() { echo "Advertencia: $*" | tee -a "$LOG" >&2; }
fail() { echo "Error: $*" | tee -a "$LOG" >&2; }

if [ ! -f "$APP_DIR/main.py" ]; then
    fail "No se encontró app/main.py en $REPO."
    exit 1
fi

log "== Doctor de dependencias de TXT Preview (macOS) =="

# 1) Homebrew: gestor de paquetes de macOS, necesario para Python y FFmpeg.
if ! command -v brew >/dev/null 2>&1; then
    fail "Homebrew no está instalado. Instalalo con esta línea y volvé a ejecutar install.sh:"
    echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' | tee -a "$LOG" >&2
    exit 1
fi

PYTHON="${PYTHON:-python3}"

# 2) Python 3.10+ vía brew (el doctor exige 3.10 o superior).
python_ok() {
    "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}
if ! python_ok; then
    info "Instalando Python con Homebrew (detalle en install.log)..."
    brew install python >> "$LOG" 2>&1 || { fail "brew no pudo instalar Python; mirá install.log."; exit 1; }
    PYTHON="${PYTHON:-python3}"
fi
if ! python_ok; then
    fail "No hay un Python 3.10+ disponible. Instalalo con 'brew install python' y volvé a ejecutar install.sh."
    exit 1
fi
log "Python OK: $("$PYTHON" --version 2>&1)"

# 3) FFmpeg: reproduce las voces Edge y exporta MP3.
if ! command -v ffplay >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    info "Instalando FFmpeg con Homebrew (detalle en install.log)..."
    brew install ffmpeg >> "$LOG" 2>&1 || { fail "brew no pudo instalar FFmpeg; mirá install.log."; exit 1; }
fi
log "FFmpeg OK: $(command -v ffplay)"

# 4) Paquetes de la app (requirements.txt + edge-tts).
# Con PEP 668 algunos Pythons de sistema rechazan --user; se reintenta con --break-system-packages.
if [ "${SKIP_INSTALL:-0}" != "1" ]; then
    log "Instalando dependencias de Python (requirements.txt y edge-tts)..."
    if ! "$PYTHON" -m pip install --user -r "$APP_DIR/requirements.txt" edge-tts >> "$LOG" 2>&1; then
        log "pip pidió confirmación por PEP 668; reintentando con --break-system-packages..."
        if ! "$PYTHON" -m pip install --user --break-system-packages -r "$APP_DIR/requirements.txt" edge-tts >> "$LOG" 2>&1; then
            fail "pip no pudo instalar las dependencias de Python; mirá install.log."
            exit 1
        fi
    fi
fi

# 5) Dictado local (botón Micrófono): paquetes y modelo. Si algo falla la app
# abre igual; solo queda sin dictado, y el doctor lo avisa.
if [ "${SKIP_INSTALL:-0}" != "1" ]; then
    log "Instalando los paquetes del dictado (transcribe-cpp, sounddevice, numpy)..."
    if ! "$PYTHON" -m pip install --user transcribe-cpp sounddevice numpy >> "$LOG" 2>&1; then
        if ! "$PYTHON" -m pip install --user --break-system-packages transcribe-cpp sounddevice numpy >> "$LOG" 2>&1; then
            warn "no se pudieron instalar los paquetes del dictado; el botón Micrófono no va a dictar (detalle en install.log)."
        fi
    fi
    if [ ! -f "$REPO/models/nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf" ]; then
        info "Descargando el modelo del dictado (unos 750 MB, una sola vez)..."
        if ! "$PYTHON" "$REPO/dictation_listen.py" --install >> "$LOG" 2>&1; then
            warn "no se pudo descargar el modelo del dictado; el botón Micrófono no va a dictar. Volvé a ejecutar install.sh para reintentar."
        fi
    fi
fi

# 6) Doctor: mismo reporte que usa un humano o un agente de IA.
set +e
DOCTOR_REPORT="$("$PYTHON" "$APP_DIR/doctor.py" 2>&1)"
DOCTOR_EXIT=$?
set -e
log "$DOCTOR_REPORT"
if [ "$DOCTOR_EXIT" -ne 0 ]; then
    # Something is missing: the report is the error, so it goes on screen.
    echo "$DOCTOR_REPORT" >&2
    fail "El doctor detectó algo pendiente: seguí las 'Solución' de arriba y volvé a ejecutar install.sh."
fi

# 7) Cómo abrir la app (en el log).
log ""
log "Listo. Ejecutá la app con:"
log "  cd \"$REPO\" && ./run.sh"
log "Si el clone no trae el permiso de ejecución (git no siempre lo conserva de Windows):"
log "  chmod +x run.sh    # o: git config core.fileMode true y volvé a hacer pull"
log "Después abrí la app y cargá tu API key de Groq en Configuración."
[ "$DOCTOR_EXIT" -eq 0 ] || exit 2
