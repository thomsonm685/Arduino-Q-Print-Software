"""FastAPI service for driving a Fargo DTC1250e over CUPS."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, imaging, jobs, printer

app = FastAPI(title="Card Printer", docs_url="/api/docs", redoc_url=None)

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
MAX_UPLOAD_BYTES = 40 * 1024 * 1024


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()


# --- Printer -----------------------------------------------------------------


@app.get("/api/printer")
def printer_info() -> dict[str, Any]:
    return {
        "name": config.PRINTER,
        "canvas": {"width": config.CANVAS_W, "height": config.CANVAS_H},
        "defaults": config.DEFAULT_PRINT_OPTIONS,
        "saved_defaults": printer.current_defaults(),
        "options": printer.list_options(),
    }


@app.get("/api/status")
def printer_status() -> dict[str, Any]:
    return printer.status()


@app.post("/api/cancel-all")
def cancel_all() -> dict[str, Any]:
    return printer.cancel_all().as_dict()


# --- Uploads and preview -----------------------------------------------------


def _upload_dir(upload_id: str) -> Path:
    path = config.UPLOADS_DIR / upload_id
    path.mkdir(parents=True, exist_ok=True)
    return path


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Use PNG, JPEG, BMP, TIFF or WebP.")

    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 40 MB.")

    upload_id = uuid.uuid4().hex[:12]
    target = _upload_dir(upload_id) / f"source{suffix}"
    target.write_bytes(payload)

    return {
        "upload_id": upload_id,
        "filename": file.filename,
        "bytes": len(payload),
        "source_url": f"/api/file/{upload_id}/source",
    }


def _resolve_source(upload_id: str) -> Path:
    folder = config.UPLOADS_DIR / upload_id
    for candidate in sorted(folder.glob("source.*")):
        return candidate
    raise HTTPException(404, "That image is no longer on disk. Upload it again.")


def _render(upload_id: str, adjustments: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    source = _resolve_source(upload_id)
    adj = imaging.Adjustments.from_payload(adjustments)
    target = source.parent / "print.png"
    result = imaging.process(source, target, adj)
    if not result.ok:
        raise HTTPException(500, {"message": "ImageMagick failed.", "detail": result.as_dict()})
    return target, {"adjustments": adj.as_dict(), "magick": result.as_dict()}


@app.post("/api/preview")
def preview(payload: dict[str, Any]) -> dict[str, Any]:
    upload_id = str(payload.get("upload_id", ""))
    target, meta = _render(upload_id, payload.get("adjustments", {}))
    return {
        "preview_url": f"/api/file/{upload_id}/print?v={int(target.stat().st_mtime)}",
        "density": imaging.density_note(target),
        **meta,
    }


@app.get("/api/file/{upload_id}/{which}")
def serve_file(upload_id: str, which: str) -> FileResponse:
    folder = config.UPLOADS_DIR / upload_id
    if not folder.is_dir():
        raise HTTPException(404, "Not found.")
    if which == "print":
        path = folder / "print.png"
    elif which == "source":
        path = _resolve_source(upload_id)
    else:
        raise HTTPException(404, "Not found.")
    if not path.exists():
        raise HTTPException(404, "Not found.")
    return FileResponse(path)


# --- Printing ----------------------------------------------------------------


@app.post("/api/print")
def start_print(payload: dict[str, Any]) -> dict[str, Any]:
    upload_id = str(payload.get("upload_id", ""))
    try:
        copies = max(1, min(int(payload.get("copies", 1) or 1), 200))
    except (TypeError, ValueError):
        raise HTTPException(400, "copies must be a whole number.")
    try:
        delay = max(0.0, min(float(payload.get("delay", 3) or 0), 120.0))
    except (TypeError, ValueError):
        raise HTTPException(400, "delay must be a number of seconds.")
    name = (str(payload.get("name") or "Card")).strip()[:60] or "Card"

    options = dict(config.DEFAULT_PRINT_OPTIONS)
    for key, value in (payload.get("options") or {}).items():
        if isinstance(key, str) and key.isidentifier() and value not in (None, ""):
            options[key] = str(value)

    target, meta = _render(upload_id, payload.get("adjustments", {}))
    density = imaging.density_note(target)

    if density["level"] == "warn" and not payload.get("acknowledge_density"):
        return JSONResponse(
            status_code=409,
            content={"error": "density", "density": density},
        )

    job = jobs.create(
        name=name,
        copies=copies,
        delay=delay,
        options=options,
        adjustments=meta["adjustments"],
        source=_resolve_source(upload_id),
        processed=target,
        density=density,
    )
    return {"job": job.as_dict(), "command_preview": " ".join(printer.build_lp_argv(str(target), options, name))}


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": jobs.listing()}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "No such job.")
    return job.as_dict()


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str) -> dict[str, Any]:
    job = jobs.stop(job_id)
    if not job:
        raise HTTPException(404, "No such job.")
    return job.as_dict()


@app.post("/api/jobs/{job_id}/confirm")
def confirm_job(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    job = jobs.confirm(job_id, bool(payload.get("ok", True)))
    if not job:
        raise HTTPException(404, "No such job.")
    return job.as_dict()


# --- Presets -----------------------------------------------------------------


def _read_presets() -> dict[str, Any]:
    if config.PRESETS_FILE.exists():
        try:
            return json.loads(config.PRESETS_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


@app.get("/api/presets")
def get_presets() -> dict[str, Any]:
    return {"presets": _read_presets()}


@app.put("/api/presets/{name}")
def save_preset(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    presets = _read_presets()
    presets[name[:40]] = payload
    config.PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.PRESETS_FILE.write_text(json.dumps(presets, indent=2))
    return {"presets": presets}


@app.delete("/api/presets/{name}")
def delete_preset(name: str) -> dict[str, Any]:
    presets = _read_presets()
    presets.pop(name, None)
    config.PRESETS_FILE.write_text(json.dumps(presets, indent=2))
    return {"presets": presets}


# --- Static ------------------------------------------------------------------

app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")


def main() -> None:
    import uvicorn

    config.ensure_dirs()
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
