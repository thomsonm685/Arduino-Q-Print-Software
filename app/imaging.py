"""Image preprocessing. One ImageMagick invocation per job, logged verbatim."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config
from .printer import Ran, run


@dataclass
class Adjustments:
    scale: float = 100.0        # percent of the calibrated canvas
    h_offset: int = 0           # pixels, positive moves right
    v_offset: int = 0           # pixels, positive moves down
    brightness: int = 100       # modulate, 100 = unchanged
    saturation: int = 100       # modulate, 100 = unchanged
    gamma: float = 1.0
    contrast: int = 0           # -4..4, each step is one -contrast pass
    sharpen: float = 1.0        # sigma for -sharpen 0xN, 0 disables
    fit: str = "stretch"        # stretch | contain
    background: str = "white"

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> "Adjustments":
        def num(key, cast, default, low=None, high=None):
            try:
                value = cast(data.get(key, default))
            except (TypeError, ValueError):
                return default
            if low is not None:
                value = max(low, value)
            if high is not None:
                value = min(high, value)
            return value

        return cls(
            scale=num("scale", float, 100.0, 50, 150),
            h_offset=num("h_offset", int, 0, -200, 200),
            v_offset=num("v_offset", int, 0, -200, 200),
            brightness=num("brightness", int, 100, 50, 200),
            saturation=num("saturation", int, 100, 0, 200),
            gamma=num("gamma", float, 1.0, 0.2, 3.0),
            contrast=num("contrast", int, 0, -4, 4),
            sharpen=num("sharpen", float, 1.0, 0.0, 5.0),
            fit=str(data.get("fit")) if data.get("fit") in ("stretch", "contain", "cover") else "stretch",
            background=str(data.get("background", "white"))[:32] or "white",
        )

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def build_argv(source: Path, target: Path, adj: Adjustments) -> list[str]:
    """Scale, position and colour-correct the art onto a CR80 canvas.

    The source is composited onto a canvas of the calibrated size rather than
    resized in place, so scale and offset can push art past the trim edge
    without changing the page geometry CUPS receives.
    """
    magick = config.imagemagick_cmd()
    w, h = config.CANVAS_W, config.CANVAS_H
    # Overscan the art a few % past the card edge (clipped by the canvas) so a
    # full-bleed design leaves no white gap at the trim. Skipped for letterbox
    # (contain), where the white border is the whole point.
    bleed = 1.0 + config.BLEED_PERCENT / 100.0 if adj.fit != "contain" and config.BLEED_PERCENT > 0 else 1.0
    scaled_w = round(w * adj.scale / 100 * bleed)
    scaled_h = round(h * adj.scale / 100 * bleed)
    # stretch: force exact dims (distorts). cover: fill the box, overflow is
    # clipped by the composite. contain: fit inside the box, letterboxed.
    flag = {"stretch": "!", "cover": "^", "contain": ""}[adj.fit]
    resize = f"{scaled_w}x{scaled_h}{flag}"

    argv = [
        *magick,
        "-size", f"{w}x{h}",
        f"xc:{adj.background}",
        # Lanczos is the sharpest general-purpose resampling filter; it matters
        # most when downscaling a high-res badge to the 300 dpi card canvas.
        "(", str(source), "-filter", "Lanczos", "-resize", resize, ")",
        "-gravity", "center",
        "-geometry", f"{adj.h_offset:+d}{adj.v_offset:+d}",
        "-composite",
        "+repage",
    ]

    if adj.brightness != 100 or adj.saturation != 100:
        argv += ["-modulate", f"{adj.brightness},{adj.saturation},100"]
    if adj.gamma != 1.0:
        argv += ["-gamma", f"{adj.gamma}"]
    for _ in range(abs(adj.contrast)):
        argv.append("+contrast" if adj.contrast < 0 else "-contrast")
    if adj.sharpen > 0:
        # Unsharp mask (edge-local contrast) reads sharper on dye-sub than a
        # plain -sharpen convolution and avoids the bright halo on card text.
        # Slider value drives sigma; amount and threshold are fixed for cards.
        argv += ["-unsharp", f"0x{adj.sharpen}+0.8+0.008"]

    # Colour + output. -type TrueColor forces a full 24-bit RGB PNG so the file
    # can never be palette-quantised (which would both shift colours and soften
    # edges). sRGB is the working space the Fargo driver expects. The 300 dpi tag
    # makes the CUPS image filter map pixels 1:1 onto the CR80 imageable area.
    argv += [
        "-alpha", "remove", "-alpha", "off",
        "-colorspace", "sRGB",
        "-type", "TrueColor",
        "-density", "300", "-units", "PixelsPerInch",
        str(target),
    ]
    return argv


def process(source: Path, target: Path, adj: Adjustments) -> Ran:
    return run(build_argv(source, target, adj), timeout=180)


# --- Calibration target ------------------------------------------------------


def build_calibration_argv(target: Path, w: int, h: int, inset: int = 20, labels: bool = True) -> list[str]:
    """A single card for calibrating both print position and colour.

    Draws an edge frame + registration marks (line the print up on the card and
    measure edge clipping) and a strip of pure R/G/B/C/M/Y swatches (see how the
    printer maps colour). Rendered pixel-exact at the print canvas — no resize,
    sharpen or colour change — so what you measure is the printer, not us.

    labels=False drops all text, for headless boards with no fonts installed
    where drawing text would make ImageMagick fail.
    """
    magick = config.imagemagick_cmd()
    cx, cy = w // 2, h // 2
    L = 46  # registration mark arm length
    edge = 12  # full-bleed colour band width, ~1mm at 300dpi

    d: list[str] = ["font-size 22", "text-align center"] if labels else []
    # Full-bleed colour band painted right to pixel 0. On the printed card,
    # wherever you still see white *outside* this blue band the printer isn't
    # reaching that edge — nudge Lineup toward the white side. This is the true
    # edge-to-edge coverage test; ink fills 0..edge, the interior is white.
    d += ["fill #1560BD stroke none", f"rectangle 0,0 {w - 1},{h - 1}",
          "fill white stroke none", f"rectangle {edge},{edge} {w - 1 - edge},{h - 1 - edge}"]
    # Black frame just inside the bleed band — the "safe area" edge.
    d += ["fill none stroke black stroke-width 3", f"rectangle {edge},{edge} {w - 1 - edge},{h - 1 - edge}"]
    # Red inset frame at a known distance, so lost edge is measurable.
    d += ["stroke red stroke-width 2", f"rectangle {inset},{inset} {w - 1 - inset},{h - 1 - inset}"]
    # Corner L registration marks, just inside the red frame.
    for x, y, sx, sy in (
        (inset, inset, 1, 1), (w - 1 - inset, inset, -1, 1),
        (inset, h - 1 - inset, 1, -1), (w - 1 - inset, h - 1 - inset, -1, -1),
    ):
        d += ["stroke black stroke-width 3",
              f"line {x},{y} {x + sx * L},{y}", f"line {x},{y} {x},{y + sy * L}"]
    # Centre crosshair + circle.
    d += ["stroke black stroke-width 2 fill none",
          f"line {cx - 34},{cy} {cx + 34},{cy}", f"line {cx},{cy - 34} {cx},{cy + 34}",
          f"circle {cx},{cy} {cx},{cy - 18}"]

    # Colour swatch strip across the middle.
    swatches = [("#FF0000", "R"), ("#00FF00", "G"), ("#0000FF", "B"),
                ("#00FFFF", "C"), ("#FF00FF", "M"), ("#FFFF00", "Y")]
    margin, gap, band_h = 70, 12, 138
    sw = (w - 2 * margin - gap * (len(swatches) - 1)) // len(swatches)
    sy0 = 116
    for i, (hexcol, letter) in enumerate(swatches):
        x0 = margin + i * (sw + gap)
        d += [f"fill {hexcol} stroke none", f"rectangle {x0},{sy0} {x0 + sw},{sy0 + band_h}"]
        if labels:
            label_col = "black" if letter in ("G", "C", "Y") else "white"
            d += [f"fill {label_col} stroke none", f"text {x0 + sw // 2},{sy0 + band_h // 2 + 8} '{letter}'"]

    # Greyscale ramp below the swatches, dark -> light.
    steps, ramp_y, ramp_h = 8, 364, 58
    rw = (w - 2 * margin) // steps
    for i in range(steps):
        v = round(255 * i / (steps - 1))
        d += [f"fill rgb({v},{v},{v}) stroke none",
              f"rectangle {margin + i * rw},{ramp_y} {margin + (i + 1) * rw},{ramp_y + ramp_h}"]

    # Labels.
    if labels:
        d += ["fill black stroke none font-size 26",
              f"text {cx},{inset + 66} 'CALIBRATION  {w}x{h}px @ 300dpi'",
              f"text {cx},{h - inset - 40} 'blue band = bleed to edge  ·  red = {inset}px inset ({inset / 300 * 25.4:.1f}mm)'"]

    return [
        *magick, "-size", f"{w}x{h}", "xc:white",
        "-fill", "black", "-draw", " ".join(d),
        "-colorspace", "sRGB", "-type", "TrueColor",
        "-density", "300", "-units", "PixelsPerInch", str(target),
    ]


def render_calibration(target: Path, w: int, h: int) -> Ran:
    res = run(build_calibration_argv(target, w, h, labels=True), timeout=120)
    if res.ok:
        return res
    # Text drawing fails on boards with no fonts installed. Retry without labels
    # so the frame + swatches (the parts that actually matter) still render.
    return run(build_calibration_argv(target, w, h, labels=False), timeout=120)


def mean_luminance(path: Path) -> float | None:
    """0.0 is solid black, 1.0 is solid white."""
    magick = config.imagemagick_cmd()
    res = run([*magick, str(path), "-colorspace", "Gray", "-format", "%[fx:mean]", "info:"], timeout=60)
    if not res.ok:
        return None
    try:
        return float(res.stdout.strip())
    except ValueError:
        return None


def density_note(path: Path) -> dict[str, Any]:
    """Warn before the printer stalls on a high-coverage card.

    The DTC1250e can halt mid-card on very dark art and CUPS still reports the
    job as completed, so this check runs before anything is submitted.
    """
    mean = mean_luminance(path)
    if mean is None:
        return {"mean": None, "level": "unknown", "message": "Could not measure ink coverage."}
    if mean < config.DENSITY_WARN_THRESHOLD:
        return {
            "mean": round(mean, 3),
            "level": "warn",
            "message": (
                f"Heavy ink coverage (mean luminance {mean:.2f}). Cards this dark have "
                "stalled the printer mid-pass. Raise brightness or gamma before printing."
            ),
        }
    return {"mean": round(mean, 3), "level": "ok", "message": "Ink coverage is in the range that prints reliably."}
