"""Perceiver protocol — every platform adapter implements this."""
from __future__ import annotations

from typing import Optional, Protocol

from ..actions import Action
from ..types import NormalizedObservation


class Perceiver(Protocol):
    platform_name: str

    def observe(self, goal: str = "", with_screenshot: bool = False,
                screenshot_path: str = "") -> NormalizedObservation: ...

    def act(self, action: Action) -> bool:
        """Execute one action. Returns True when the OS accepted the input;
        success of the *intent* is established by verify(), never here."""
        ...

    def screenshot(self, path: str) -> str: ...

    def windows(self) -> list[dict]: ...

    def focus_window(self, name: str) -> bool: ...

    def sleep_ms(self, ms: int) -> None:
        import time
        time.sleep(ms / 1000.0)


class PerceiverError(RuntimeError):
    pass


def pick_perceiver(prefer: Optional[str] = None) -> Perceiver:
    """Choose the adapter for the current OS (or an explicit override)."""
    import sys
    plat = prefer or sys.platform
    if plat in ("darwin", "macos"):
        from .macos import MacOSPerceiver
        return MacOSPerceiver()
    if plat in ("win32", "windows"):
        from .windows import WindowsPerceiver
        return WindowsPerceiver()
    if plat in ("linux", "linux2"):
        from .linux import LinuxPerceiver
        return LinuxPerceiver()
    raise PerceiverError(f"unsupported platform: {plat}")
