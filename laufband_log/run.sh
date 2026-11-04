#!/usr/bin/with-contenv bashio
bashio::log.info "Starte Laufband-Log ..."
export DATA_DIR=/data
exec python3 -u /app/main.py
