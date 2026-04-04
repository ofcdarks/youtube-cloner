#!/bin/bash
# Entrypoint — fix permissions on mounted volumes, then start as appuser

# Fix ownership of output directory (may be owned by root from previous builds)
if [ -d "/app/output" ]; then
    chown -R appuser:appuser /app/output 2>/dev/null || true
fi

# Fix ownership of notebooklm credentials
if [ -d "/home/appuser/.notebooklm" ]; then
    chown -R appuser:appuser /home/appuser/.notebooklm 2>/dev/null || true
fi

# Start app as appuser
exec gosu appuser uvicorn dashboard:app --host 0.0.0.0 --port 8888 --proxy-headers --forwarded-allow-ips '*'
