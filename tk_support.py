"""Locate bundled Tcl/Tk data for Windows Python virtual environments.

Some Python 3.13 installations find the Tk DLL but miss their own tcl directory
inside a venv. This only sets variables for this process, never Windows globally.
"""
import os
from pathlib import Path
import sys
import tkinter


def prepare_tk():
    if sys.platform == "win32":
        base = Path(sys.base_prefix) / "tcl"
        for variable, directory, marker in (
            ("TCL_LIBRARY", f"tcl{tkinter.TclVersion}", "init.tcl"),
            ("TK_LIBRARY", f"tk{tkinter.TkVersion}", "tk.tcl"),
        ):
            candidate = base / directory
            if (candidate / marker).is_file():
                os.environ.setdefault(variable, str(candidate))


def check_tk():
    prepare_tk()
    root = tkinter.Tk()
    root.withdraw()
    root.update_idletasks()
    root.destroy()


if __name__ == "__main__":
    check_tk()
    print("Tk window check passed.")
