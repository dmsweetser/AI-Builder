# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for AI-Builder.

Produces a single executable that:
  - Bundles all Python dependencies
  - Uses a RELATIVE ./aib_instance directory (next to the executable)
    for configs, model downloads, chat history, etc.
  - Includes templates/, static/, oneshot_engine/, and agent_engine/
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Resolve paths relative to this spec file
here = Path(__file__).parent.resolve()
app_dir = here

# Collect all sub-packages we need
hidden_imports = [
    "flask",
    "dotenv",
    "azure.ai.inference",
    "azure.ai.inference.models",
    "azure.core.credentials",
    "agent_engine",
    "agent_engine.tools",
    "agent_engine.tools.base",
    "agent_engine.tools.checkers",
    "agent_engine.tools.files",
    "agent_engine.tools.misc",
    "agent_engine.tools.search",
    "oneshot_engine",
    "oneshot_engine.parser",
    "oneshot_engine.modifier",
    "oneshot_engine.action_manager",
    "oneshot_engine.code_utility",
    "oneshot_engine.engine",
]

# Collect data files (templates, static, etc.)
aib_data = []
for pkg_dir in ["templates", "static"]:
    pkg_path = app_dir / pkg_dir
    if pkg_path.exists():
        aib_data.append((str(pkg_path), pkg_dir))

# Also bundle oneshot_engine and agent_engine as data so they're
# findable at runtime (they're importable as packages but PyInstaller
# sometimes misses submodules in one-shot mode).
for pkg_dir in ["oneshot_engine", "agent_engine"]:
    pkg_path = app_dir / pkg_dir
    if pkg_path.exists():
        aib_data.append((str(pkg_path), pkg_dir))

# base_config.xml
if (app_dir / "base_config.xml").exists():
    aib_data.append((str(app_dir / "base_config.xml"), "."))

a = Analysis(
    ['ui.py'],
    pathex=[],
    binaries=[],
    datas=aib_data,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ai-builder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ai-builder',
)

# --- Additional: standalone one-file executable ---
exe_onefile = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ai-builder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
