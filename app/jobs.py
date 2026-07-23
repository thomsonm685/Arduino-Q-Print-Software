"""Sequential print queue.

One worker thread, one card at a time. Copies are submitted as separate CUPS
jobs rather than `lp -n`, so a failure on card 3 of 10 is visible as card 3 and
the run can be stopped there.
"""

from __future__ import annotations

import json
import queue
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import config, imaging, printer

_lock = threading.Lock()
_jobs: dict[str, "Job"] = {}
_pending: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None
_stop_requested: set[str] = set()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    name: str
    copies: int
    delay: float
    options: dict[str, str]
    adjustments: dict[str, Any]
    source: str
    processed: str
    state: str = "queued"          # queued|printing|awaiting_confirmation|confirmed|failed|cancelled
    printed: int = 0
    created: str = field(default_factory=now)
    finished: str | None = None
    density: dict[str, Any] = field(default_factory=dict)
    log: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["source"] = Path(self.source).name
        data["processed"] = Path(self.processed).name
        return data

    def note(self, event: str, detail: Any = None) -> None:
        self.log.append({"at": now(), "event": event, "detail": detail})


def create(
    name: str,
    copies: int,
    delay: float,
    options: dict[str, str],
    adjustments: dict[str, Any],
    source: Path,
    processed: Path,
    density: dict[str, Any],
) -> Job:
    job = Job(
        id=uuid.uuid4().hex[:12],
        name=name,
        copies=copies,
        delay=delay,
        options=options,
        adjustments=adjustments,
        source=str(source),
        processed=str(processed),
        density=density,
    )
    # Snapshot the processed image to a per-job file. The upload's print.png is
    # rewritten by every preview, so without this a second preview mid-run would
    # change the image an in-flight run is still sending to the printer.
    snapshot = config.PRINTS_DIR / f"{job.id}.png"
    try:
        config.PRINTS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(processed, snapshot)
        job.processed = str(snapshot)
    except OSError as exc:
        job.note("snapshot_failed", repr(exc))
    with _lock:
        _jobs[job.id] = job
    job.note("queued", {"copies": copies, "options": options})
    _pending.put(job.id)
    _ensure_worker()
    return job


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def listing(limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.created, reverse=True)
    return [j.as_dict() for j in jobs[:limit]]


def confirm(job_id: str, printed_ok: bool) -> Job | None:
    job = get(job_id)
    if not job or job.state != "awaiting_confirmation":
        return job
    job.state = "confirmed" if printed_ok else "failed"
    job.finished = now()
    job.note("operator_confirmed", {"ok": printed_ok})
    _archive(job)
    return job


def stop(job_id: str) -> Job | None:
    """Stop a run and clear anything of its already sitting in the CUPS queue."""
    job = get(job_id)
    if not job:
        return None
    _stop_requested.add(job_id)
    if job.state == "printing":
        job.note("cancel_requested")
        job.note("cancel_all", printer.cancel_all().as_dict())
    elif job.state == "queued":
        job.state = "cancelled"
        job.finished = now()
        job.note("cancelled_before_start")
    return job


# --- Worker ------------------------------------------------------------------


def _ensure_worker() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_loop, name="cardprint-worker", daemon=True)
        _worker.start()


def _loop() -> None:
    while True:
        job_id = _pending.get()
        job = get(job_id)
        if job is None or job.state == "cancelled":
            _stop_requested.discard(job_id)
            continue
        try:
            _run_job(job)
        except Exception as exc:  # a crashed card must not take the queue with it
            job.state = "failed"
            job.finished = now()
            job.note("worker_error", repr(exc))
            _archive(job)
        finally:
            _stop_requested.discard(job_id)
            _cleanup_old()


def _run_job(job: Job) -> None:
    job.state = "printing"
    job.note("started")

    for index in range(1, job.copies + 1):
        if job.id in _stop_requested:
            job.state = "cancelled"
            job.finished = now()
            job.note("stopped", {"after": job.printed})
            _archive(job)
            return

        title = f"{job.name} {index}/{job.copies}"
        submission = printer.submit(job.processed, job.options, title)
        job.note(f"card_{index}_submitted", submission.ran.as_dict())

        if not submission.ran.ok:
            job.state = "failed"
            job.finished = now()
            job.note("submit_failed", {"card": index})
            _archive(job)
            return

        if submission.cups_job_id:
            job.note(f"card_{index}_wait", printer.wait_for_job(submission.cups_job_id))

        job.printed = index
        job.note("printer_status", printer.status())

        if index < job.copies and job.delay > 0:
            time.sleep(job.delay)

    job.state = "awaiting_confirmation"
    job.note(
        "awaiting_confirmation",
        "CUPS reports every card as sent. Confirm the cards physically came out.",
    )


# --- Persistence -------------------------------------------------------------


def _archive(job: Job) -> None:
    try:
        config.HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with config.HISTORY_FILE.open("a") as handle:
            handle.write(json.dumps(job.as_dict()) + "\n")
    except OSError:
        pass


def _cleanup_old() -> None:
    """Remove working files for finished jobs past the retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.CLEANUP_AFTER_HOURS)
    with _lock:
        jobs = list(_jobs.values())
    for job in jobs:
        if job.state in ("queued", "printing", "awaiting_confirmation"):
            continue
        try:
            finished = datetime.fromisoformat(job.finished or job.created)
        except ValueError:
            continue
        if finished < cutoff:
            # Drop this job's image snapshot, then forget the job.
            try:
                Path(job.processed).unlink()
            except OSError:
                pass
            with _lock:
                _jobs.pop(job.id, None)

    # Sweep upload folders (source + preview render) that have aged out. Their
    # mtime bumps on every preview, so an actively edited upload is never swept.
    try:
        for folder in config.UPLOADS_DIR.iterdir():
            if not folder.is_dir():
                continue
            try:
                mtime = datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc)
            except OSError:
                continue
            if mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
    except OSError:
        pass
