"""Path resolution helpers for dev vs. PyInstaller one-file builds.

In dev mode:
    _get_exe_dir()  -> directory containing app.py (source tree root)
    _get_app_dir()  -> same as _get_exe_dir()

In PyInstaller one-file builds:
    _get_app_dir()  -> sys._MEIPASS (temp extracted dir with bundled assets)
    _get_exe_dir()  -> directory containing the .exe (persistent data location)

The exe directory is where aib_instance/ lives so data persists across runs.
"""

import os
import sys


def _get_exe_dir() -> str:
    """Return the directory containing the running executable.

    - PyInstaller one-file (running from temp): resolves the actual .exe
      location on disk via /proc/self/exe (Linux) or ctypes Win32 API
      (Windows), then returns its parent directory.
    - PyInstaller one-file (frozen on disk): returns dirname(sys.executable).
    - Dev mode: returns the project root (parent of agent_engine/).
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller one-file: _MEIPASS is the temp extraction dir.
        # sys.executable points to the actual .exe on disk — use that.
        exe_path = os.path.abspath(sys.executable)
        # On Linux, sys.executable may point to /proc/.../exe -> /tmp/.../._<name>
        # Resolve symlinks to get the real path.
        if os.path.islink(exe_path):
            exe_path = os.path.realpath(exe_path)
        if os.path.isfile(exe_path):
            return os.path.dirname(exe_path)
        # Fallback: try the parent of _MEIPASS
        return os.path.dirname(os.path.abspath(sys._MEIPASS))
    if getattr(sys, 'frozen', False):
        # PyInstaller one-file running from disk (e.g. after moving the exe)
        exe_path = os.path.abspath(sys.executable)
        if os.path.islink(exe_path):
            exe_path = os.path.realpath(exe_path)
        return os.path.dirname(exe_path)
    # Dev mode: walk up from this file until we find the project root
    # (the directory containing app.py, which is the parent of agent_engine/)
    candidate = os.path.dirname(os.path.abspath(__file__))
    while candidate != os.path.dirname(candidate):
        parent = os.path.dirname(candidate)
        if os.path.isfile(os.path.join(parent, "app.py")):
            return parent
        candidate = parent
    # Ultimate fallback
    return os.path.dirname(os.path.abspath(__file__))


def get_exe_dir() -> str:
    """Public: directory where persistent data (aib_instance/) should live."""
    return _get_exe_dir()


def get_app_dir() -> str:
    """Public: directory containing bundled assets (templates, static, agent_engine).

    In dev mode this is the project root (where app.py lives).
    In PyInstaller builds it is sys._MEIPASS (temp extraction dir).
    """
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # Dev mode: walk up from this file until we find the project root
    candidate = os.path.dirname(os.path.abspath(__file__))
    while candidate != os.path.dirname(candidate):
        parent = os.path.dirname(candidate)
        if os.path.isfile(os.path.join(parent, "app.py")):
            return parent
        candidate = parent
    return os.path.dirname(os.path.abspath(__file__))
