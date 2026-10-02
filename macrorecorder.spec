# -*- coding: utf-8 -*-
"""Spec PyInstaller para macrorecorder.exe — GUI one-file, self-contained.

Estratégia:
- Entrypoint: src/macro_recorder/gui.py  (abre a GUI direto, sem console).
- O botao de Replay executa `runtime_python() -m macro_recorder replay <pasta>`.
- No .exe, runtime_python() extrai para <TEMP>/mrec_runtimes/<hash>/venv um
  venv a partir do python-build-standalone embutido (build/_bundle/python_standalone)
  e usa o site-packages embutido (build/_bundle/site-packages) + pacote (build/_bundle/macro_recorder).
- O build_exe.py (na raiz) popula build/_bundle/ ANTES de rodar o PyInstaller.
- Se MREC_WITH_STANDALONE nao foi usado no build, o replay cai para python no
  PATH (documentado no README).
"""
import os
import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH)
SRC = SPEC_DIR / "src"
BUNDLE = SPEC_DIR / "build" / "_bundle"
if not SRC.exists():
    raise SystemExit(f"src/ não encontrado em {SRC}")

sys.path.insert(0, str(SRC))

# ---------------------------------------------------------------------------
# Datas: o que entra no bundle
# ---------------------------------------------------------------------------
datas = []

# 1) pacote macro_recorder (para o .pth do mini-venv)
pkg = BUNDLE / "macro_recorder"
if pkg.exists():
    datas.append((str(pkg), "macro_recorder"))
else:
    # fallback: usa src/macro_recorder (o build_exe.py não rodou)
    datas.append((str(SRC / "macro_recorder"), "macro_recorder"))
    print("[spec] build/_bundle/macro_recorder não existe; usando src/ (rebuild via build_exe.py recomendado)")

# 2) site-packages (deps runtime)
site = BUNDLE / "site-packages"
if site.exists():
    datas.append((str(site), "site-packages"))

# 3) python standalone (opcional; permite replay sem Python no PATH)
standalone = BUNDLE / "python_standalone"
if standalone.exists() and any(standalone.iterdir()):
    datas.append((str(standalone), "python_standalone"))
else:
    print("[spec] python_standalone ausente; o replay dependerá do Python no PATH")

# ---------------------------------------------------------------------------
# hiddenimports (análise do PyInstaller)
# ---------------------------------------------------------------------------
hiddenimports = [
    "macro_recorder",
    "macro_recorder.gui",
    "macro_recorder.cli",
    "macro_recorder.listener",
    "macro_recorder.capture",
    "macro_recorder.exporter_md",
    "macro_recorder.exporter_py",
    "macro_recorder.replay",
    "macro_recorder._host_runtime",
    "customtkinter",
    "pyautogui",
    "mouseinfo",
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",
    "PIL",
    "PIL.Image",
    "mss",
    "mss.windows",
    "ctypes",
]

# ---------------------------------------------------------------------------
a = Analysis(
    [str(SRC / "macro_recorder" / "gui.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch", "tensorflow", "pandas", "scipy", "matplotlib",
        "pytest", "IPython", "jupyter", "notebook",
    ],
    win_no_prefer_redirects=False,
    win_system_prefer_redirects=False,
    win_exe_prefer_redirects=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="macrorecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI (sem console)
    icon=None,
)
