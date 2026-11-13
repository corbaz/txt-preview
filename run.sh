#!/usr/bin/env bash
# Ejecuta TXT Preview en macOS (también funciona en Linux): ./run.sh
# Si el clone no conserva el permiso de ejecución, corré una vez: chmod +x run.sh
set -euo pipefail
cd "$(dirname "$0")"
exec python3 app/main.py "$@"
