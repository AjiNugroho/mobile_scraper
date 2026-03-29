"""
Device manager — ADB device discovery and exclusive allocation.

Each Celery worker process calls `acquire_device()` at task start and
`release_device()` at task end (or on failure).  A threading.Semaphore
per serial ensures only one task runs on a given device at a time.

Because Celery workers are separate *processes* (not threads), we use a
cross-process lock backed by a file lock (via `filelock`) so that multiple
worker processes on the same machine don't double-assign the same device.
"""

import logging
import subprocess
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)

# Directory where per-device lock files are stored
_LOCK_DIR = Path("/tmp/mobilescraper_locks")
_LOCK_DIR.mkdir(parents=True, exist_ok=True)

# How long (seconds) to wait for a device lock before giving up
_LOCK_TIMEOUT = 0  # non-blocking — fail immediately if device is busy


# ── ADB helpers ───────────────────────────────────────────────────────────────

def list_connected_devices() -> list[str]:
    """
    Return serial numbers of all currently connected ADB devices.
    Raises RuntimeError if `adb` is not available or returns an error.
    """
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        raise RuntimeError("'adb' binary not found. Is Android SDK platform-tools in PATH?")

    lines = result.stdout.strip().splitlines()
    # First line is always "List of devices attached"
    serials: list[str] = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])

    logger.info("Connected ADB devices: %s", serials)
    return serials


def _lock_path(serial: str) -> Path:
    # Sanitise serial so it's safe as a filename
    safe = serial.replace(":", "_").replace("/", "_")
    return _LOCK_DIR / f"{safe}.lock"


# ── Public API ────────────────────────────────────────────────────────────────

@contextmanager
def acquire_device(serial: str):
    """
    Context manager that acquires an exclusive file lock for *serial*.

    Usage::

        with acquire_device(serial) as serial:
            run_scraper(serial)

    Raises `DeviceBusyError` if the device is already in use.
    Raises `DeviceDisconnectedError` if the device is no longer visible.
    """
    lock = FileLock(str(_lock_path(serial)))
    try:
        lock.acquire(timeout=_LOCK_TIMEOUT)
    except Timeout:
        raise DeviceBusyError(f"Device {serial!r} is already in use by another worker.")

    try:
        # Verify the device is still connected after we acquired the lock
        if serial not in list_connected_devices():
            raise DeviceDisconnectedError(f"Device {serial!r} disconnected before task started.")

        logger.info("Acquired device %s", serial)
        yield serial
    finally:
        lock.release()
        logger.info("Released device %s", serial)


def pick_available_device() -> str | None:
    """
    Return the serial of the first device that is connected *and* not
    currently locked by another worker, or None if all are busy.
    """
    for serial in list_connected_devices():
        lock = FileLock(str(_lock_path(serial)))
        try:
            lock.acquire(timeout=0)
            lock.release()
            return serial
        except Timeout:
            continue
    return None


# ── Custom exceptions ─────────────────────────────────────────────────────────

class DeviceBusyError(RuntimeError):
    """Raised when all devices are occupied."""


class DeviceDisconnectedError(RuntimeError):
    """Raised when a device disconnects during a task."""
