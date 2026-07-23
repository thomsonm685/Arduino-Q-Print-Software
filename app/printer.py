"""Thin wrappers around the CUPS command line tools.

Every shell-out returns the exact argv, stdout, stderr and exit code so the UI
can show what actually ran. Nothing here hides a command from the operator.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from . import config


@dataclass
class Ran:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    seconds: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": " ".join(self.argv),
            "returncode": self.returncode,
            "stdout": self.stdout.strip(),
            "stderr": self.stderr.strip(),
            "seconds": round(self.seconds, 2),
        }


def run(argv: list[str], timeout: int = 120) -> Ran:
    started = time.monotonic()
    try:
        # CUPS tools and the Fargo PPD can emit non-UTF-8 bytes (locale, Latin-1
        # in the PPD). errors="replace" keeps a stray byte from 500-ing the API.
        proc = subprocess.run(
            argv, capture_output=True, text=True, errors="replace",
            timeout=timeout, check=False,
        )
        return Ran(argv, proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started)
    except subprocess.TimeoutExpired:
        return Ran(argv, 124, "", f"timed out after {timeout}s", time.monotonic() - started)
    except FileNotFoundError as exc:
        return Ran(argv, 127, "", str(exc), time.monotonic() - started)


# --- Option discovery --------------------------------------------------------

_OPTION_LINE = re.compile(r"^(\S+)/([^:]*):\s*(.*)$")


def list_options() -> list[dict[str, Any]]:
    """Parse `lpoptions -p PRINTER -l` into a schema the UI can render.

    Output lines look like:
        Ribbon/Ribbon Type: *YMCKO YMCK K Custom
    The choice prefixed with * is the current default.
    """
    res = run(["lpoptions", "-p", config.PRINTER, "-l"], timeout=20)
    options: list[dict[str, Any]] = []
    if not res.ok:
        return options

    for line in res.stdout.splitlines():
        match = _OPTION_LINE.match(line.strip())
        if not match:
            continue
        keyword, label, raw_choices = match.groups()
        choices, default = [], None
        for choice in raw_choices.split():
            if choice.startswith("*"):
                choice = choice[1:]
                default = choice
            choices.append(choice)
        if not choices:
            continue
        options.append(
            {
                "keyword": keyword,
                "label": label.strip() or keyword,
                "choices": choices,
                "default": default or choices[0],
            }
        )
    options.sort(key=lambda o: o["keyword"].lower())
    return options


def current_defaults() -> dict[str, str]:
    """Parse `lpoptions -p PRINTER` (the saved per-printer defaults)."""
    res = run(["lpoptions", "-p", config.PRINTER], timeout=20)
    defaults: dict[str, str] = {}
    if res.ok:
        for token in res.stdout.split():
            if "=" in token:
                key, value = token.split("=", 1)
                defaults[key] = value.strip("'\"")
    return defaults


# --- Status ------------------------------------------------------------------


def status() -> dict[str, Any]:
    """Printer state plus state-reasons.

    CUPS marks jobs completed even when the printer aborts internally, so
    state-reasons are the more useful signal. They are still not proof that a
    card came out correctly, which is why jobs end in operator confirmation.
    """
    res = run(["lpstat", "-l", "-p", config.PRINTER], timeout=20)
    text = res.stdout

    state = "unknown"
    if "is idle" in text:
        state = "idle"
    elif "now printing" in text or "is printing" in text:
        state = "printing"
    elif "disabled" in text:
        state = "disabled"

    reasons = [
        line.strip()
        for line in text.splitlines()[1:]
        if line.strip() and not line.strip().startswith("printer ")
    ]

    queued = run(["lpstat", "-o", config.PRINTER], timeout=20)
    return {
        "printer": config.PRINTER,
        "state": state,
        "reasons": reasons,
        "queued": [l for l in queued.stdout.splitlines() if l.strip()],
        "raw": text.strip(),
        "reachable": res.ok,
    }


# --- Printing ----------------------------------------------------------------

_JOB_ID = re.compile(r"request id is (\S+)")


@dataclass
class Submission:
    cups_job_id: str | None
    ran: Ran
    waits: list[dict[str, Any]] = field(default_factory=list)


def build_lp_argv(image_path: str, options: dict[str, str], title: str) -> list[str]:
    argv = ["lp", "-d", config.PRINTER, "-t", title]
    for key, value in options.items():
        if value is None or value == "":
            continue
        argv += ["-o", f"{key}={value}"]
    argv.append(image_path)
    return argv


def submit(image_path: str, options: dict[str, str], title: str) -> Submission:
    argv = build_lp_argv(image_path, options, title)
    res = run(argv, timeout=120)
    match = _JOB_ID.search(res.stdout)
    return Submission(cups_job_id=match.group(1) if match else None, ran=res)


def wait_for_job(cups_job_id: str, timeout: int = 240, poll: float = 2.0) -> dict[str, Any]:
    """Block until CUPS stops listing the job as pending or processing."""
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        res = run(["lpstat", "-o", config.PRINTER], timeout=15)
        last = res.stdout
        if cups_job_id not in res.stdout:
            return {"left_queue": True, "waited": round(timeout - (deadline - time.monotonic()), 1)}
        time.sleep(poll)
    return {"left_queue": False, "waited": timeout, "queue": last.strip()}


def cancel_all() -> Ran:
    return run(["cancel", "-a", config.PRINTER], timeout=30)
