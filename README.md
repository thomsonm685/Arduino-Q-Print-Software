# Card Printer Console

A small web console for a Fargo DTC1250e attached to an Arduino UNO Q (or any
Debian box) running CUPS. Upload artwork, adjust it, pick driver options, print
a run of cards.

It is a thin, honest wrapper around the command that already works on the bench:

```
lp -d Fargo-DTC-1250e -o PageSize=CR80 -o Resolution=300dpi -o Ribbon=YMCKO card.png
```

Every ImageMagick and `lp` invocation is logged verbatim on the job record.

## Install

Assumes the Fargo CUPS driver and the printer queue are already set up.

```bash
git clone <your-repo-url> card-printer
cd card-printer
chmod +x install.sh
./install.sh
```

Then open `http://<uno-ip>:8080`.

If the printer queue does not exist yet:

```bash
lpinfo -v
sudo lpadmin -p Fargo-DTC-1250e -E \
  -v 'usb://HID%20Global/DTC1250e?serial=C1150719' \
  -P /path/to/Fargo_DTC1250e.ppd
sudo cupsenable Fargo-DTC-1250e && sudo cupsaccept Fargo-DTC-1250e
```

## How a run works

1. Drop an image on the card preview. It is composited onto a 1110 × 638
   canvas at 300 dpi.
2. Adjust scale, X/Y offset, brightness, saturation, gamma, contrast and
   sharpen. The preview re-renders through ImageMagick, so what you see is the
   actual file that will be sent.
3. Driver options are read live from `lpoptions -p <printer> -l`, so the list
   matches whatever driver version is installed. The exact `lp` command is
   shown under the options panel before you commit.
4. Set copies and a gap between cards, then print. Copies are submitted as
   separate CUPS jobs so a failure on card 3 of 10 is visible as card 3.
5. Each run finishes in **check the output**. Confirm or flag it.

## Why the console asks you to confirm

CUPS reports a job as completed even when the printer aborts internally — dark,
high-coverage art has stalled the DTC1250e mid-pass with no error surfacing.
Two guards exist because of that:

- **Ink coverage check.** Mean luminance is measured before submitting. Below
  the threshold you get a warning and have to acknowledge it.
- **Operator confirmation.** Job state is not trusted as proof a card exists.
  Confirming builds a real failure record in `~/.local/share/cardprint/history.jsonl`.

## Configuration

Set in `/etc/systemd/system/cardprint.service`, then
`sudo systemctl restart cardprint`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CARDPRINT_PRINTER` | `Fargo-DTC-1250e` | CUPS queue name |
| `CARDPRINT_PORT` | `8080` | HTTP port |
| `CARDPRINT_HOST` | `0.0.0.0` | Bind address |
| `CARDPRINT_CANVAS_W` / `_H` | `1110` / `638` | Calibrated canvas in pixels |
| `CARDPRINT_DENSITY_WARN` | `0.32` | Mean luminance below this warns |
| `CARDPRINT_DATA` | `~/.local/share/cardprint` | Jobs, presets, history |
| `CARDPRINT_CLEANUP_HOURS` | `24` | Working files removed after |

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/printer` | Name, canvas, parsed driver options |
| `GET` | `/api/status` | Printer state and state-reasons |
| `POST` | `/api/upload` | Multipart image upload |
| `POST` | `/api/preview` | Re-render with adjustments, return density |
| `POST` | `/api/print` | Start a run (409 if too dark and unacknowledged) |
| `GET` | `/api/jobs` | Run history |
| `POST` | `/api/jobs/{id}/stop` | Stop a run and clear the CUPS queue |
| `POST` | `/api/jobs/{id}/confirm` | Record whether cards came out |
| `POST` | `/api/cancel-all` | `cancel -a` |

Interactive docs at `/api/docs`.

## Troubleshooting

**Options panel is empty** — `lpoptions -p Fargo-DTC-1250e -l` returned nothing.
The service user needs the PPD to be readable and the queue to exist.

**Print button works but nothing happens** — check `lpstat -t` and
`journalctl -u cardprint -f`. A flashing red pause on the printer is usually the
ribbon, not the software.

**Permission denied on print** — the service user must be in the `lp` group. A
reboot after `usermod` is the reliable fix.

**Art is clipped on the left and bottom** — known behaviour on full-bleed cards.
Nudge Offset X positive and Offset Y negative, drop Scale to ~98%, and save the
values you land on.
