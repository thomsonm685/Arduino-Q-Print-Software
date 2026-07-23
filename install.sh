#!/usr/bin/env bash
# Installs the card printer console as a systemd service.
# Run from the repository root: ./install.sh
set -euo pipefail

APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
PRINTER="${CARDPRINT_PRINTER:-Fargo-DTC-1250e}"

say() { printf '\n\033[1;35m==>\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$1"; }

if [[ $EUID -eq 0 && -z "${SUDO_USER:-}" ]]; then
  warn "Running as root with no SUDO_USER. The service will run as root."
fi

say "Installing system packages"
sudo apt-get update
sudo apt-get install -y \
  cups cups-client cups-bsd imagemagick \
  python3 python3-venv python3-pip

say "Adding $RUN_USER to the printer groups"
sudo usermod -aG lpadmin "$RUN_USER"
sudo usermod -aG lp "$RUN_USER"

say "Checking CUPS"
sudo systemctl enable --now cups
if ! lpstat -p "$PRINTER" >/dev/null 2>&1; then
  warn "Printer '$PRINTER' is not registered with CUPS."
  warn "Add it first, then re-run this script:"
  warn "  lpinfo -v"
  warn "  sudo lpadmin -p $PRINTER -E -v usb://HID%20Global/DTC1250e?serial=XXXX -P /path/to/Fargo_DTC1250e.ppd"
  warn "  sudo cupsenable $PRINTER && sudo cupsaccept $PRINTER"
else
  echo "  found $PRINTER"
fi

say "Building the Python environment"
python3 -m venv "$APPDIR/.venv"
"$APPDIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$APPDIR/.venv/bin/pip" install -r "$APPDIR/requirements.txt"

say "Installing the service"
sed -e "s|__APPDIR__|$APPDIR|g" -e "s|__USER__|$RUN_USER|g" \
    -e "s|CARDPRINT_PRINTER=Fargo-DTC-1250e|CARDPRINT_PRINTER=$PRINTER|" \
    "$APPDIR/systemd/cardprint.service" | sudo tee /etc/systemd/system/cardprint.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now cardprint
sleep 2
sudo systemctl --no-pager --lines=5 status cardprint || true

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
say "Done"
echo "  Open http://${IP:-localhost}:8080"
echo "  Logs:    journalctl -u cardprint -f"
echo "  Restart: sudo systemctl restart cardprint"
echo
warn "If $RUN_USER was just added to the lp group, reboot before printing."
