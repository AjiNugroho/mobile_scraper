"""
Device manager — ADB device discovery and exclusive allocation.

Each Celery worker process calls `acquire_device()` at task start and
`release_device()` at task end (or on failure).

Because Celery workers are separate *processes* (not threads), we use a
cross-process lock backed by a file lock (via `filelock`) so that multiple
worker processes on the same machine don't double-assign the same device.

ADB connectivity
----------------
We use `adbutils` (already a project dependency) to talk to the ADB server
directly over TCP instead of shelling out to the `adb` binary.  This avoids
the version-mismatch problem that occurs when the `adb` binary inside a Docker
container differs from the host's ADB server version (the client would then
refuse to reuse the existing server and spawn its own, finding no devices).

The ADB server host/port are read from the standard environment variables:
  ANDROID_ADB_SERVER_HOST  (default: 127.0.0.1)
  ANDROID_ADB_SERVER_PORT  (default: 5037)

In Docker, set ANDROID_ADB_SERVER_HOST=host.docker.internal so the container
talks to the host's ADB server where the USB devices are registered.
"""

import logging
import os
from contextlib import contextmanager
from pathlib import Path

import adbutils
from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)

# Directory where per-device lock files are stored
_LOCK_DIR = Path("/tmp/mobilescraper_locks")
_LOCK_DIR.mkdir(parents=True, exist_ok=True)

# How long (seconds) to wait for a device lock before giving up
_LOCK_TIMEOUT = 0  # non-blocking — fail immediately if device is busy


# ── ADB client factory ────────────────────────────────────────────────────────

def _adb_client() -> adbutils.AdbClient:
    """
    Return an adbutils client pointed at the correct ADB server.
    Reads ANDROID_ADB_SERVER_HOST / ANDROID_ADB_SERVER_PORT from the
    environment so Docker and local runs both work without code changes.
    """
    host = os.getenv("ANDROID_ADB_SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("ANDROID_ADB_SERVER_PORT", "5037"))
    return adbutils.AdbClient(host=host, port=port)


# ── ADB helpers ───────────────────────────────────────────────────────────────

def list_connected_devices() -> list[str]:
    """
    Return serial numbers of all currently connected ADB devices by querying
    the ADB server directly via adbutils (no `adb` binary subprocess).
    """
    client = _adb_client()
    serials = [d.serial for d in client.device_list()]
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
