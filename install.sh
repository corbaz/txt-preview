#!/usr/bin/env bash
# Instalador de TXT Preview para macOS.
# Uso después de clonar:
#   bash install.sh
#   SKIP_INSTALL=1 bash install.sh    # solo corre el doctor
# Instala Homebrew (si falta), Python, FFmpeg y los paquetes de la app,
# corre el doctor y muestra cómo ejecutar la app. No necesita sudo.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$REPO/app"

if [ ! -f "$APP_DIR/main.py" ]; then
    echo "No se encontró app/main.py en $REPO." >&2
    exit 1
fi

echo "== Doctor de dependencias de TXT Preview (macOS) =="

# 1) Homebrew: gestor de paquetes de macOS, necesario para Python y FFmpeg.
if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew no está instalado." >&2
    echo "Instalalo con esta línea y volvé a ejecutar install.sh:" >&2
    echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' >&2
    exit 1
fi

PYTHON="${PYTHON:-python3}"

# 2) Python 3.10+ vía brew (el doctor exige 3.10 o superior).
python_ok() {
    "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}
if ! python_ok; then
    echo "Instalando Python con Homebrew..."
    brew install python
    PYTHON="${PYTHON:-python3}"
fi
if ! python_ok; then
    echo "No hay un Python 3.10+ disponible. Instalalo con 'brew install python' y volvé a ejecutar install.sh." >&2
    exit 1
fi
echo "Python OK: $("$PYTHON" --version)"

# 3) FFmpeg: reproduce las voces Edge y exporta MP3.
if ! command -v ffplay >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    echo "Instalando FFmpeg con Homebrew..."
    brew install ffmpeg
fi
echo "FFmpeg OK: $(command -v ffplay)"

# 4) Paquetes de la app (requirements.txt + edge-tts).
# Con PEP 668 algunos Pythons de sistema rechazan --user; se reintenta con --break-system-packages.
if [ "${SKIP_INSTALL:-0}" != "1" ]; then
    echo "Instalando dependencias de Python (requirements.txt y edge-tts)..."
    if ! "$PYTHON" -m pip install --user -r "$APP_DIR/requirements.txt" edge-tts; then
        echo "pip pidió confirmación por PEP 668; reintentando con --break-system-packages..."
        "$PYTHON" -m pip install --user --break-system-packages -r "$APP_DIR/requirements.txt" edge-tts
    fi
fi

# 5) Doctor: mismo reporte que usa un humano o un agente de IA.
set +e
"$PYTHON" "$APP_DIR/doctor.py"
DOCTOR_EXIT=$?
set -e
if [ "$DOCTOR_EXIT" -ne 0 ]; then
    echo "El doctor detectó algo pendiente: seguí las 'Solución' de arriba y volvé a ejecutar install.sh." >&2
fi

# 6) Cómo abrir la app.
echo
echo "Listo. Ejecutá la app con:"
echo "  cd \"$REPO\" && ./run.sh"
echo "Si el clone no trae el permiso de ejecución (git no siempre lo conserva de Windows):"
echo "  chmod +x run.sh    # o: git config core.fileMode true y volvé a hacer pull"
echo "Después abrí la app y cargá tu API key de Groq en Configuración."
[ "$DOCTOR_EXIT" -eq 0 ] || exit 2
