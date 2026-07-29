#!/usr/bin/env bash
# Read-only preflight for the card printer console. Prints nothing but checks;
# safe to run any time over SSH. Reports what's missing before you print.
#
#   ./doctor.sh
PRINTER="${CARDPRINT_PRINTER:-Fargo-DTC-1250e}"
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
bad()  { printf '  \033[31mMISS\033[0m %s\n' "$1"; }
note() { printf '       %s\n' "$1"; }

echo "== Card printer preflight ($(date)) =="

echo "Architecture"
note "$(uname -m) — $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"

echo "Tooling"
if command -v python3 >/dev/null 2>&1; then ok "python3 ($(python3 --version 2>&1))"; else bad "python3 not found"; fi
for bin in lp lpstat lpoptions; do
  if command -v "$bin" >/dev/null 2>&1; then ok "$bin ($(command -v "$bin"))"; else bad "$bin not found — sudo apt install cups-client"; fi
done
if command -v magick >/dev/null 2>&1; then ok "imagemagick ($(magick -version | head -1 | cut -d' ' -f1-3))"
elif command -v convert >/dev/null 2>&1; then ok "imagemagick/convert ($(convert -version | head -1 | cut -d' ' -f1-3))"
else bad "imagemagick (magick/convert) not found"; fi

echo "CUPS service"
if systemctl is-active --quiet cups 2>/dev/null; then ok "cups is running"; else bad "cups not active — sudo systemctl enable --now cups"; fi

echo "Printer queue: $PRINTER"
if lpstat -p "$PRINTER" >/dev/null 2>&1; then
  ok "$(lpstat -p "$PRINTER" | head -1)"
  COUNT=$(lpoptions -p "$PRINTER" -l 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$COUNT" -gt 0 ]]; then ok "driver exposes $COUNT option groups"; else bad "lpoptions -l returned nothing — PPD not readable by this user?"; fi
else
  bad "queue '$PRINTER' not registered — add it with lpadmin (see README)"
fi

echo "Fargo CUPS filter (arch must match host — the classic 'filter failed' on ARM)"
FILT=$(ls /usr/libexec/cups/filter/rastertofargo-* 2>/dev/null | head -1)
if [[ -n "$FILT" ]]; then
  [[ -x "$FILT" ]] && ok "present: $(basename "$FILT")" || bad "not executable: $FILT — sudo chmod 755 it"
  AINFO=$(file -b "$FILT" 2>/dev/null)
  note "$AINFO"
  HA=$(uname -m)
  case "$HA" in
    aarch64|arm64) echo "$AINFO" | grep -qiE 'aarch64|arm64|ARM aarch64' && ok "matches host ($HA)" || bad "filter is NOT ARM64 — jobs will 'filter failed'; get the ARM driver build" ;;
    armv7l|armhf)  echo "$AINFO" | grep -qiE 'ARM,|armhf|EABI' && ok "matches host ($HA)" || bad "filter arch may not match host $HA" ;;
    x86_64)        echo "$AINFO" | grep -qiE 'x86-64|x86_64|amd64' && ok "matches host ($HA)" || bad "filter arch may not match host $HA" ;;
    *)             note "host $HA — verify the filter arch above matches by eye" ;;
  esac
else
  note "rastertofargo filter not found in /usr/libexec/cups/filter — driver may live elsewhere, or isn't installed"
fi

echo "Group membership (needed to submit jobs)"
if id -nG "$USER" | grep -qw lp; then ok "$USER is in group 'lp'"; else bad "$USER not in 'lp' — sudo usermod -aG lp $USER, then reboot"; fi

echo "Python venv"
if [[ -x "$(dirname "$0")/.venv/bin/python" ]]; then ok ".venv present"; else note ".venv not built yet — ./run.sh or ./install.sh will create it"; fi

echo "== done =="
