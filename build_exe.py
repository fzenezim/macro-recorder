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
    "openpyxl",
    "pyperclip",
    "opencv-python",
    "numpy",
    "pywin32",
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
        "pyautogui": ["pyautogui", "pygetwindow", "mouseinfo", "pymsgbox", "PyGetText"],
        "mouseinfo": ["mouseinfo"],
        "pynput": ["pynput"],
        "Pillow": ["PIL", "Pillow"],
        "mss": ["mss"],
        "openpyxl": ["openpyxl", "et_xmlfile"],
        "pyperclip": ["pyperclip"],
        "opencv-python": ["cv2", "opencv_python"],
        "numpy": ["numpy"],
        "pywin32": ["win32com", "win32ui", "win32con", "win32api", "win32process", "win32gui", "win32api", "Pythonwin", "pywintypes"],
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
    A URL e a estrutura da pasta variam entre releases — se o download fallar
    com 404, atualize PYS_SA_URL para a release mais recente em
    https://github.com/astral-sh/python-build-standalone/releases
    (procure por cpython-3.11.x+YYYYMMDD-x86_64-pc-windows-msvc-install_only.tar.gz).
    Versao verificada: 3.11.17+20261013-win64."""
    if STANDALONE.exists() and (STANDALONE / ( "python.exe" if os.name == "nt" else "python3")).exists():
        log("python standalone ja presente, pulando download")
        return
    log("Baixando python-build-standalone 3.11.17 (win64)...")
    url = os.environ.get(
        "MREC_PYS_URL",
        "https://github.com/astral-sh/python-build-standalone/releases/download/"
        "20261013/cpython-3.11.17%2B20261013-x86_64-pc-windows-msvc-install_only.tar.gz",
    )
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
    log("Rodando PyInstaller (onedir)...")
    # Nao uso --clean: o clear do cache do PyInstaller (C:\AppData\Local\pyinstaller)
    # briga com o reparse point do OneDrive na pasta build/ e deixa PermissionError
    # em build/macrorecorder/localpycs. Limpar manualmente o output e suficiente.
    subprocess.run([str(VENV_PY), "-m", "PyInstaller", "macrorecorder.spec", "--noconfirm"], check=True)


def place_icon() -> None:
    """Coloca um .ico na raiz do onedir (o Explorer de Win 10/11 le o icone da
    pasta a partir do primeiro *.ico da raiz) e remove qualquer .ico espurios
    que o PyInstaller deixou escondidos em _internal/ (icone errando de lugar)."""
    ico = ROOT / "icon.ico"
    onedir = ROOT / "dist" / "macrorecorder"
    if not ico.exists():
        log("icon.ico nao existe na raiz do projeto; pulei o posicionamento")
        return
    if not onedir.exists():
        raise RuntimeError(f"{onedir} nao existe apos o build")
    # raiz visivel do onedir
    root_ico = onedir / "icon.ico"
    if root_ico.exists():
        root_ico.unlink()
    shutil.copy2(ico, root_ico)
    log(f"  + {root_ico.relative_to(ROOT)}")
    # remove o icone que o COLLECT pode ter deixado em _internal/ (buried)
    buried = onedir / "_internal" / "icon.ico"
    if buried.exists():
        buried.unlink()
        log(f"  - removido _internal/icon.ico (buried)")


def package_zip() -> None:
    """Empacota dist/macrorecorder/ em um zip (o artefato que o usuario baixa;
    VT e end-users preferem o zip a uma pasta solta)."""
    log("Empacotando zip...")
    onedir = ROOT / "dist" / "macrorecorder"
    if not onedir.exists():
        raise RuntimeError(f"{onedir} nao existe apos o build")
    zip_path = ROOT / "dist" / "macrorecorder-win64.zip"
    if zip_path.exists():
        zip_path.unlink()
    import zipfile
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(onedir.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(onedir.parent))
    log(f"zip pronto: {zip_path.name} ({zip_path.stat().st_size // 1024 // 1024} MB)")


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
    place_icon()
    package_zip()
    log("DONE -> dist/macrorecorder/  (exe onedir) + dist/macrorecorder-win64.zip")


if __name__ == "__main__":
    main()
