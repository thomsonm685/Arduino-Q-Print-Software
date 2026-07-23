#!/usr/bin/env bash
# Start the card printer console in the foreground.
# First run builds the virtualenv; later runs just launch. Ctrl-C to stop.
#
#   ./run.sh
#
# Override any setting inline, e.g.:
#   CARDPRINT_PORT=9000 CARDPRINT_PRINTER=Fargo-DTC-1250e ./run.sh
set -euo pipefail

APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APPDIR"

if [[ ! -x .venv/bin/python ]]; then
  echo "==> First run: creating virtualenv"
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt
fi

PORT="${CARDPRINT_PORT:-8080}"
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
echo "==> Starting on http://${IP:-localhost}:${PORT}  (Ctrl-C to stop)"
exec .venv/bin/python -m app.main
