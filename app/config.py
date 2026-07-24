"""Runtime configuration. Everything is overridable by environment variable."""

import os
import shutil
from pathlib import Path

# --- Printer -----------------------------------------------------------------
PRINTER = os.environ.get("CARDPRINT_PRINTER", "Fargo-DTC-1250e")

# Options always sent unless the UI overrides them. This is the recommended
# production command from the calibration spec, not the minimal bench command:
# the three that printed successfully on the bench (PageSize/Resolution/Ribbon)
# plus the single-sided, full-thickness, no-rotation, zero-lineup defaults.
DEFAULT_PRINT_OPTIONS = {
    "PageSize": "CR80",
    "Resolution": "300dpi",
    "Ribbon": "YMCKO",
    "CardThickness": "30",
    "PrintBothSides": "False",
    "RotateFront180": "False",
    "RotateBack180": "False",
    "ImageHOffset": "0",   # driver-level horizontal lineup, in printer units
    "ImageVOffset": "0",   # driver-level vertical lineup, in printer units
    # The driver defaults to RGBW (a 4-channel mode with an added white channel);
    # feeding it standard 3-channel RGB there misaligns the channels and shifts
    # hues (greens read blue). Plain RGB is the correct match for our output.
    "ColorModel": "RGB",
    # ColorMatching None does a crude linear RGB->dye conversion that maps nuanced
    # greens toward blue. ICC2 applies a real colour profile and prints true green;
    # confirmed on the bench to beat both None and ICC1.
    "ColorMatching": "ICC2",
}

# --- Image -------------------------------------------------------------------
# Calibrated print canvas, in pixels, at 300 dpi on a CR80 card.
CANVAS_W = int(os.environ.get("CARDPRINT_CANVAS_W", 1110))
CANVAS_H = int(os.environ.get("CARDPRINT_CANVAS_H", 638))

# Mean luminance below this triggers the too-dark warning. The DTC1250e stalls
# on high-coverage art without reporting anything back to CUPS.
DENSITY_WARN_THRESHOLD = float(os.environ.get("CARDPRINT_DENSITY_WARN", 0.32))

# --- Storage -----------------------------------------------------------------
DATA_DIR = Path(os.environ.get("CARDPRINT_DATA", Path.home() / ".local/share/cardprint"))
# Uploads and their live preview render live here, keyed by upload id.
UPLOADS_DIR = DATA_DIR / "uploads"
# Each job snapshots its processed image here, keyed by job id, so a later
# preview of the same upload can't mutate an in-flight run's image.
PRINTS_DIR = DATA_DIR / "prints"
PRESETS_FILE = DATA_DIR / "presets.json"
HISTORY_FILE = DATA_DIR / "history.jsonl"

# Delete a job's working files this many hours after it finishes.
CLEANUP_AFTER_HOURS = float(os.environ.get("CARDPRINT_CLEANUP_HOURS", 24))

# --- Server ------------------------------------------------------------------
HOST = os.environ.get("CARDPRINT_HOST", "0.0.0.0")
PORT = int(os.environ.get("CARDPRINT_PORT", 8080))

STATIC_DIR = Path(__file__).parent / "static"


def imagemagick_cmd() -> list[str]:
    """ImageMagick 7 ships `magick`; ImageMagick 6 ships `convert`."""
    if shutil.which("magick"):
        return ["magick"]
    if shutil.which("convert"):
        return ["convert"]
    raise RuntimeError(
        "ImageMagick not found. Install it with: sudo apt install imagemagick"
    )


def ensure_dirs() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    PRINTS_DIR.mkdir(parents=True, exist_ok=True)
