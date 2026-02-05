#!/bin/bash
echo "=== EJECUTANDO LIMPIEZA PROFUNDA ==="

# Eliminar todos los .pyc y caché
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} +

# Reinstalar desde cero
pip uninstall -y python-telegram-bot telegram
pip cache purge

# Instalar versión específica
pip install --no-cache-dir --force-reinstall python-telegram-bot==20.7

echo "=== LIMPIEZA COMPLETADA ==="
