"""Hardware/display-free checks for Sol's Phase 1 UI modules.

Run with: python test_ui_foundation.py
These checks intentionally parse Tk modules instead of importing them so they
also run in headless CI images where tkinter is not installed.
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent


def parsed(name):
    path = ROOT / name
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def class_members(tree, class_name):
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == class_name)
    return {n.name for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def main():
    pod = parsed("air_pod.py")
    hud = parsed("hud.py")
    win = parsed("win_windows.py")

    pod_members = class_members(pod, "AirPod")
    for method in ("render", "say", "ask", "answer_by_voice",
                   "has_question", "set_idle_text", "show", "hide", "toggle",
                   "preview_visible", "preview_size"):
        check(f"AirPod.{method}", method in pod_members)

    hud_members = class_members(hud, "HUD")
    for method in ("set_status", "set_error", "show_confirmation",
                   "close_overlay", "run", "_handle_close"):
        check(f"HUD.{method}", method in hud_members)

    # Guard the frozen shutdown contract: HUD._handle_close must not destroy
    # root/panel itself. AirOS owns final destruction after worker shutdown.
    cls = next(n for n in hud.body
               if isinstance(n, ast.ClassDef) and n.name == "HUD")
    close_fn = next(n for n in cls.body
                    if isinstance(n, ast.FunctionDef) and n.name == "_handle_close")
    close_source = ast.unparse(close_fn)
    check("HUD close does not destroy Tk", ".destroy(" not in close_source)

    top_functions = {n.name for n in win.body if isinstance(n, ast.FunctionDef)}
    check("configure_windows_process exists",
          "configure_windows_process" in top_functions)

    # Importing win_windows is safe everywhere; off Windows it is a no-op.
    import win_windows
    scale = win_windows.configure_windows_process()
    check("DPI scale is numeric", isinstance(scale, (int, float)))
    check("DPI scale is positive", scale > 0)
    if sys.platform != "win32":
        check("non-Windows DPI no-op", scale == 1.0)

    print("All Phase 1 UI foundation checks passed.")


if __name__ == "__main__":
    main()
