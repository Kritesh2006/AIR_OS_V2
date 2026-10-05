"""Windows-specific process helpers for AIR OS.

Phase 1 only configures DPI awareness and a small no-activate helper used by
AirPod. Window enumeration / targeted close support belongs to Phase 2.
Every function is a harmless no-op off Windows so tests remain portable.
"""

from __future__ import annotations

import sys

BASE_DPI = 96.0


def configure_windows_process() -> float:
    """Enable the best available DPI awareness and return a UI scale.

    Must be called before creating any Tk object. Failure is intentionally
    non-fatal: AIR should still launch even if Windows has already configured
    DPI awareness or an API is unavailable.
    """
    if sys.platform != "win32":
        return 1.0

    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return 1.0

    user32 = ctypes.windll.user32
    configured = False

    # Windows 10 Creators Update+: PER_MONITOR_AWARE_V2 pseudo-handle == -4.
    try:
        fn = user32.SetProcessDpiAwarenessContext
        fn.argtypes = [wintypes.HANDLE]
        fn.restype = wintypes.BOOL
        configured = bool(fn(ctypes.c_void_p(-4)))
    except Exception:
        pass

    # Windows 8.1+ fallback.
    if not configured:
        try:
            shcore = ctypes.windll.shcore
            fn = shcore.SetProcessDpiAwareness
            fn.argtypes = [ctypes.c_int]
            fn.restype = ctypes.c_long
            fn(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            configured = True
        except Exception:
            pass

    # Vista+ fallback.
    if not configured:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    dpi = BASE_DPI
    try:
        fn = user32.GetDpiForSystem
        fn.argtypes = []
        fn.restype = wintypes.UINT
        value = int(fn())
        if value > 0:
            dpi = float(value)
    except Exception:
        pass

    scale = dpi / BASE_DPI
    return scale if 0.5 <= scale <= 4.0 else 1.0


def make_window_noactivate(hwnd: int) -> bool:
    """Make a top-level window non-activating on Windows.

    AirPod uses this so appearing/updating in the top-left does not steal
    keyboard focus from the user's current application. Returns False when
    unsupported; callers should continue normally.
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        get_style = user32.GetWindowLongPtrW
        set_style = user32.SetWindowLongPtrW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_style.restype = ctypes.c_ssize_t

        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        style = int(get_style(hwnd, GWL_EXSTYLE))
        set_style(hwnd, GWL_EXSTYLE,
                  style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        return True
    except Exception:
        return False
