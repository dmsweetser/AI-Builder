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

    - PyInstaller one-file (running from temp): returns the directory
      of the actual .exe on disk (sys._MEIPASS's parent).
    - PyInstaller one-file (frozen on disk): returns dirname(sys.executable).
    - Dev mode: returns the project root (parent of agent_engine/).
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller one-file: _MEIPASS is the temp extraction dir.
        # The exe is at the same level as _MEIPASS was extracted from,
        # which is sys._MEIPASS's parent directory.
        return os.path.dirname(os.path.abspath(sys._MEIPASS))
    if getattr(sys, 'frozen', False):
        # PyInstaller one-file running from disk (e.g. after moving the exe)
        return os.path.dirname(os.path.abspath(sys.executable))
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
