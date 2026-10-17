# build_exe.py
# Prepara os artefatos para o .exe self-contained:
#   1) instala as deps de RUNTIME (replay) num venv 3.11 limpo
#      -> build/_bundle/site-packages   (compativel com o python_standalone 3.11)
#   2) copia o pacote macro_recorder -> build/_bundle/macro_recorder
#   3) baixa/usa python-build-standalone 3.11 -> build/_bundle/python_standalone/
#   4) roda PyInstaller com a spec (onedir)
# Executar:  .venv\Scripts\python build_exe.py
#
# POR QUE instalar para o 3.11 (nao copiar do .venv dev):
#   O botao de Replay executa `<standalone>/python.exe -m macro_recorder replay`
#   em um mini-venv montado a partir do python_standalone (3.11) + este
#   site-packages embutido. Se este site-packages for copiado do .venv do
#   desenvolvimento (que roda numa versao DIFERENTE do 3.11, ex.: 3.14), os
#   .pyd cp3XX do numpy/cv2 falham no venv 3.11 -> import cv2 ImportError ->
#   pyautogui (que importa cv2 p/ opencv) quebra -> os cliques/mouse NUNCA
#   funcionam no replay (a tela nao "ativa" o menu), e o pyperclip tambem
#   falha -> o texto cai no fallback pyautogui.typewrite (ASCII-only) ->
#   acentos se corrompem ("Olá" vira "Ol'a"). Instalar para o 3.11 resolve os
#   dois defeitos de uma vez.
from __future__ import annotations

import importlib.util
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

# Deps que o subprocess de replay precisa (espelha o runtime do pyproject.toml).
# Sao instaladas no venv 3.11 abaixo (nao copiadas do .venv dev).
RUNTIME_DEPS = [
    "pyautogui",
    "pynput",
    "pyperclip",
    "Pillow",
    "mss",
    "opencv-python",
    "numpy",
    "openpyxl",
    "pywin32",
]


def log(msg: str) -> None:
    print(f"[build-exe] {msg}")


# ---------------------------------------------------------------------------
# 1) site-packages compativel com o python_standalone (3.11)
# ---------------------------------------------------------------------------
def _pyversion(python: Path) -> str:
    r = subprocess.run(
        [str(python), "-c", "import sys; print('.'.join(map(str, sys.version_info[:2])))"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def _venv_site_for(venv_root: Path) -> Path:
    if os.name == "nt":
        return venv_root / "Lib" / "site-packages"
    return venv_root / "lib" / "python3" / "site-packages"


def _pip(venv_root: Path) -> list[str]:
    pipx = venv_root / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
    if pipx.exists():
        return [str(pipx)]
    py = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return [str(py), "-m", "pip"]


def _validate_site(venv_root: Path) -> list[str]:
    """Importa o pipeline de replay NO interpretador do 3.11; devolve a lista
    de pacotes com problema (deve ser vazia)."""
    py = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    code = (
        "import importlib.util, importlib, sys;"
        "mods=['pyperclip','pyautogui','cv2','pynput','numpy','mss'];"
        "bad=[m for m in mods if not importlib.util.find_spec(m)];"
        "import cv2, numpy, pyautogui;"  # importa de verdade (forca o .pyd)
        "print('\\n'.join(bad));"
        "print('CV2 ' + cv2.__version__ + ' NUMPY ' + numpy.__version__);"
    )
    r = subprocess.run([str(py), "-c", code], capture_output=True, text=True)
    out = (r.stdout or "").strip()
    log(f"  validate: {out.replace(chr(10), ' | ')}")
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()[-3:]
        log("  validate ERR: " + " / ".join(tail))
    bad = [ln for ln in out.splitlines() if ln and not ln.startswith("CV2")]
    return bad


def _bundle_site_packages() -> None:
    """Instala RUNTIME_DEPS num venv 3.11 limpo (do python_standalone embutido)
    e copia o site-packages resultante para build/_bundle/site-packages — o que
    o _mrec_runtimes venv embutir e o que o replay subprocess usa em runtime."""
    log("Instalando deps de replay para o Python 3.11 (standalone)...")
    host_py = STANDALONE / ("python.exe" if os.name == "nt" else "python3")
    if not host_py.exists():
        raise SystemExit(
            "python_standalone ausente; rode com MREC_WITH_STANDALONE=1 "
            "(o site-deps deve ser compativel com a versao do runtime)"
        )
    ver = _pyversion(host_py)
    log(f"  standalone python: {ver}")

    venv_root = BUILD / "_runtime_venv"
    venv_root_sp = _venv_site_for(venv_root)
    if venv_root_sp.exists():
        shutil.rmtree(venv_root_sp, ignore_errors=True)

    # venv limpo COM pip (o standalone do python-build-standalone tem pip)
    subprocess.run([str(host_py), "-m", "venv", str(venv_root)], check=True)

    pip = _pip(venv_root)
    # instala tudo de uma vez; --only-binary quando possivel, senao sdist (pyautogui)
    subprocess.run(
        pip + ["install", "--upgrade", "pip"],
        capture_output=True,
    )
    subprocess.run(
        pip + ["install", "--quiet", "--no-input"] + RUNTIME_DEPS,
        check=True,
        capture_output=False,
    )

    bad = _validate_site(venv_root)
    if bad:
        log(f"  avisando: pacotes sem entrypoint importavel: {bad}")

    # copia o site-packages validado para o bundle
    if SITE.exists():
        shutil.rmtree(SITE, ignore_errors=True)
    shutil.copytree(venv_root_sp, SITE, symlinks=True, dirs_exist_ok=True)
    n = len([p for p in SITE.iterdir()])
    log(f"  site-packages (3.11) pronto em {SITE.relative_to(ROOT)} ({n} itens)")


# ---------------------------------------------------------------------------
# 2) pacote macro_recorder
# ---------------------------------------------------------------------------
def copy_package() -> None:
    log("Copia o pacote macro_recorder para o bundle...")
    dest_pkg = BUILD / "macro_recorder"
    if dest_pkg.exists():
        shutil.rmtree(dest_pkg, ignore_errors=True)
    shutil.copytree(SRC / "macro_recorder", dest_pkg, symlinks=True, dirs_exist_ok=True)
    # include pyproject.toml para o eventual pip
    if (SRC / "pyproject.toml").exists():
        shutil.copy2(SRC / "pyproject.toml", BUILD / "pyproject.toml")


# ---------------------------------------------------------------------------
# 3) python-build-standalone
# ---------------------------------------------------------------------------
def get_standalone() -> None:
    """Baixa python-build-standalone do GitHub (uma unica vez).
    A URL e a estrutura da pasta variam entre releases — se o download fallar
    com 404, atualize para a release mais recente em
    https://github.com/astral-sh/python-build-standalone/releases
    (procure por cpython-3.11.x+YYYYMMDD-x86_64-pc-windows-msvc-install_only.tar.gz).
    Versao verificada: 3.11.17+20261013-win64."""
    target = "python.exe" if os.name == "nt" else "python3"
    if STANDALONE.exists() and (STANDALONE / target).exists():
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
    standalone_dir = _find_standalone_root(BUILD)
    if standalone_dir is None:
        raise RuntimeError("nao encontrei a raiz do standalone após extrair")
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


# ---------------------------------------------------------------------------
# 4) PyInstaller + pos-processing
# ---------------------------------------------------------------------------
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
    root_ico = onedir / "icon.ico"
    if root_ico.exists():
        root_ico.unlink()
    shutil.copy2(ico, root_ico)
    log(f"  + {root_ico.relative_to(ROOT)}")
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


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    # O site-deps precisa existir para o build; o standalone eh obrigatorio
    # (ele define a versao do python do venv de runtime).
    get_standalone()
    copy_package()
    _bundle_site_packages()
    run_pyinstaller()
    place_icon()
    package_zip()
    log("DONE -> dist/macrorecorder/  (exe onedir) + dist/macrorecorder-win64.zip")


if __name__ == "__main__":
    main()
