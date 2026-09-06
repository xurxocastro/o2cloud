#!/usr/bin/env bash
# Script de sincronización con prevención de reposo en macOS

set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Uso: $0 <directorio_local> <directorio_remoto> [argumentos_adicionales...]"
    echo "Ejemplo: $0 /Volumes/MiDisco/Fotos /Fotos --up"
    exit 1
fi

LOCAL_DIR="$1"
REMOTE_DIR="$2"
shift 2

echo "Iniciando sincronización de '$LOCAL_DIR' hacia '$REMOTE_DIR'..."

# Si estamos en macOS, usar caffeinate para evitar suspensión de pantalla/red/sistema
if command -v caffeinate >/dev/null 2>&1; then
    echo "Ejecutando con 'caffeinate' para evitar reposo del sistema..."
    exec caffeinate -dimsu o2cloud sync "$LOCAL_DIR" "$REMOTE_DIR" --up "$@"
else
    exec o2cloud sync "$LOCAL_DIR" "$REMOTE_DIR" --up "$@"
fi
