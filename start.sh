#!/bin/sh
export MALLOC_ARENA_MAX=2
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 bot.py
fi
exec python bot.py
