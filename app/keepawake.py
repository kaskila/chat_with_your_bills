"""Keep the computer from sleeping while receipts are being processed.

Uses Windows' SetThreadExecutionState (the same request video players use): the
system may still turn the screen off, but will not go to sleep until the work is
done. The user's power settings are not changed. Does nothing on other systems.
"""

import ctypes
import sys
from contextlib import contextmanager

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def _set(flags: int) -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
        except (AttributeError, OSError):
            pass


@contextmanager
def keep_awake():
    """``with keep_awake(): ...`` - no sleep while the block runs (on the calling thread)."""
    _set(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        _set(_ES_CONTINUOUS)
