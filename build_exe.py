# build_exe.py
# Prepara os artefatos para o .exe self-contained:
#   1) copia deps (pyautogui, pynput, Pillow, mss, mouseinfo) -> build/_bundle/site-packages
#   2) baixa/usa python-build-standalone -> build/_bundle/python_standalone/
#   3) roda PyInstaller com a spec
# Executar:  .venv\Scripts\python build_exe.py
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
SRC = ROOT / "src"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
BUILD = ROOT / "build" / "_bundle"
SITE = BUILD / "site-packages"
STANDALONE = BUILD / "python_standalone"

# deps runtime (as que o replay precisa; mirror do pyproject.toml)
RUNTIME_DEPS = [
    "pyautogui",
    "mouseinfo",
    "pynput",
    "Pillow",
    "mss",
]


def log(msg: str) -> None:
    print(f"[build-exe] {msg}")


def copy_deps() -> None:
    log("Copiando deps runtime para o bundle...")
    SITE.mkdir(parents=True, exist_ok=True)
    # site-packages do venv
    src_site = VENV_PY.parent.parent / "Lib" / "site-packages"
    if not src_site.exists():
        src_site = Path(sysconfig_paths())  # fallback
    # mapeia pacotes por top-level name
    top_map = {
        "pyautogui": ["pyautogui"],
        "mouseinfo": ["mouseinfo"],
        "pynput": ["pynput"],
        "Pillow": ["PIL", "Pillow"],
        "mss": ["mss"],
    }
    needed = set()
    for v in top_map.values():
        needed.update(v)

    for item in src_site.iterdir():
        if item.name in needed or item.parent != src_site:
            dest = SITE / item.name
            if dest.exists():
                dest.unlink() if dest.is_file() else shutil.rmtree(dest, ignore_errors=True)
            if item.is_dir():
                shutil.copytree(item, dest, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
            log(f"  + {item.name}")
    # também copia dist-info
    for d in src_site.iterdir():
        if d.is_dir() and (d.name.endswith(".dist-info") or d.name.endswith(".egg-info")):
            pkg = d.name.split(".")[0]
            if any(pkg in [x.lower() for x in needed] or pkg.lower() in [x.lower() for x in needed] for _ in [0]):
                dest = SITE / d.name
                if not dest.exists():
                    shutil.copytree(d, dest, symlinks=True, dirs_exist_ok=True)


def copy_package() -> None:
    log("Copia o pacote macro_recorder para o bundle...")
    dest_pkg = BUILD / "macro_recorder"
    if dest_pkg.exists():
        shutil.rmtree(dest_pkg, ignore_errors=True)
    shutil.copytree(SRC / "macro_recorder", dest_pkg, symlinks=True, dirs_exist_ok=True)
    # include pyproject.toml para o eventual pip
    if (SRC / "pyproject.toml").exists():
        shutil.copy2(SRC / "pyproject.toml", BUILD / "pyproject.toml")


def get_standalone() -> None:
    """Baixa python-build-standalone do GitHub (uma unica vez).
    Versiones verificadas: 3.11.9-win64."""
    if STANDALONE.exists() and (STANDALONE / ("python.exe" if os.name == "nt" else "python3")).exists():
        log("python standalone ja presente, pulando download")
        return
    log("Baixando python-build-standalone 3.11.9 (win64)...")
    url = "https://github.com/indygreg/python-build-standalone/releases/download/20240811/cpython-3.11.9+20240811-x86_64-pc-windows-msvc-install_only.tar.gz"
    archive = ROOT / "build" / "pysa.tar.gz"
    download(url, archive)
    log("Extraindo...")
    import tarfile
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(BUILD)
    # o tar extrai em cpython-3.11.9+.../python311/... ou similar
    standalone_dir = _find_standalone_root(BUILD)
    if standalone_dir is None:
        raise RuntimeError("nao encontrei a raiz do standalone após extrair")
    # copia o essencial para build/_bundle/python_standalone
    if STANDALONE.exists():
        shutil.rmtree(STANDALONE, ignore_errors=True)
    os.replace(standalone_dir, STANDALONE)
    log(f"standalone pronto em {STANDALONE}")


def download(url: str, dest: Path) -> None:
    log(f"GET {url}")
    urllib.request.urlretrieve(url, dest)
    log(f"  -> {dest} ({dest.stat().st_size//1024} KB)")


def _find_standalone_root(root: Path) -> Path | None:
    for c in root.iterdir():
        if c.is_dir() and (c / "python.exe").exists():
            return c
        if c.is_dir() and (c / "python3.dll").exists():
            return c
    return None


def run_pyinstaller() -> None:
    log("Rodando PyInstaller...")
    subprocess.run([str(VENV_PY), "-m", "PyInstaller", "macrorecorder.spec", "--noconfirm"], check=True)


def sysconfig_paths() -> str:
    r = subprocess.run([str(VENV_PY), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    copy_package()
    copy_deps()
    # standalone opcional (se o usuario nao quiser baixar, o exe ainda
    # funciona com python no PATH para replay)
    if os.environ.get("MREC_WITH_STANDALONE"):
        get_standalone()
    run_pyinstaller()
    log("DONE -> dist/macrorecorder.exe")


if __name__ == "__main__":
    main()
