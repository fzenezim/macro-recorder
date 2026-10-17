# -*- coding: utf-8 -*-
"""Spec PyInstaller para macrorecorder.exe — GUI one-DIR, self-contained.

Estratégia:
- Entrypoint: src/macro_recorder/gui.py  (abre a GUI direto, sem console).
- O botao de Replay executa `runtime_python() -m macro_recorder replay <pasta>`.
- No .exe (onedir), runtime_python() monta em <EXE>/_mrec_runtimes/<hash>/venv
  um venv a partir do python-build-standalone embutido (build/_bundle/python_standalone)
  + site-packages embutido (build/_bundle/site-packages) + pacote (build/_bundle/macro_recorder).
- O build_exe.py (na raiz) popula build/_bundle/ ANTES de rodar o PyInstaller.
- Se MREC_WITH_STANDALONE nao foi usado no build, o replay cai para python no
  PATH (documentado no README).
- Por que onedir (nao onefile): o self-extract para %TEMP% de cada lancamento
  e o padrao classico de unpacking de malware, e os motores ML/comportamentais
  do VirusTotal (SentinelOne "Static AI - Suspicious PE", Elastic, Bkav...)
  batem nisso. Em onedir os arquivos ficam persistentes ao lado do exe.
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

# 4) icone da pasta onedir (o Explorer de Win 10/11 le o primeiro *.ico da
#    pasta de distribuicao; o icone do PE so aparece no proprio .exe, nao na
#    pasta onedir — entao ship um .ico nomeado junto para a pasta/zip ficarem
#    "limpos" e com identidade consistente).
if (SPEC_DIR / "icon.ico").exists():
    # icone fica NO .exe (RT_ICON) e a build_exe.py copia um .ico para a raiz
    # do onedir (o Explorer de Win 10/11 le o icone da pasta a partir de la).
    # Nao se usa 'datas' porque a dest "." cai em _internal, nao na raiz visivel.
    pass

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
    "macro_recorder.excel_data",
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
    "openpyxl",
    "pyperclip",
    "cv2",
    "numpy",
]

# ---------------------------------------------------------------------------
# Versao/metadados do PE (legibilidade p/ AVs e usuarios)
# ---------------------------------------------------------------------------
from PyInstaller.utils.win32.versioninfo import (  # noqa: E402
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
    VarFileInfo, VarStruct, StringStruct,
)

_company = "fzenezim"
_product = "Macro Recorder"
_filedesc = "Macro Recorder - grava e reproduz mouse/teclado"
_copyright = "Copyright (c) 2026 fzenezim"

version = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(1, 0, 0, 0),
        prodvers=(1, 0, 0, 0),
        mask=0x3F,
        flags=0x0,
        OS=4,  # VOS_NT
        fileType=2,  # VFT_APP
        subtype=0,
    ),
    kids=[
        StringFileInfo(
            kids=[
                StringTable(
                    name="040904B0",
                    kids=[
                        StringStruct("CompanyName", _company),
                        StringStruct("FileDescription", _filedesc),
                        StringStruct("FileVersion", "1.0.0.0"),
                        StringStruct("InternalName", "macrorecorder"),
                        StringStruct("LegalCopyright", _copyright),
                        StringStruct("OriginalFilename", "macrorecorder.exe"),
                        StringStruct("ProductName", _product),
                        StringStruct("ProductVersion", "1.0.0.0"),
                    ],
                )
            ]
        ),
        VarFileInfo(
            kids=[
                VarStruct(
                    "Translation",
                    kids=[1033, 1200],  # Portuguese (Brazil): lang=1033, codepage=1200
                )
            ]
        ),
    ],
)

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
    [],
    name="macrorecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI (sem console)
    icon=str(SPEC_DIR / "icon.ico") if (SPEC_DIR / "icon.ico").exists() else None,
    version=version,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="macrorecorder",
)
