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
    scaled_w = round(w * adj.scale / 100)
    scaled_h = round(h * adj.scale / 100)
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
