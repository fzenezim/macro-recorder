# -*- coding: utf-8 -*-
"""Bootstrap de runtime para o .exe: monta um mini-venv portable a partir
do bundle PyInstaller, permitindo que o botao de Replay funcione sem
Python no sistema.

Como funciona:
    1. O .exe (one-file) extrai o bundle em <TEMP>/_MEIxxxx/ (auto).
    2. A spec inclui o pacote macro_recorder + deps no `datas` -> em
       <TEMP>/_MEIxxxx/macro_recorder e em <TEMP>/_MEIxxxx/site-packages/*.
    3. No 1o replay, runtime_python() extrai para
       <TEMP>/mrec_runtimes/<hash>/venv um Python "portable" (python-build-
       standalone embutido como `python.exe` no datas) + o site-packages
       do bundle.
    4. Depois o mini-venv está pronto; replay instantaneo.

Em modo dev (venv ativo) runtime_python() retorna o venv normalmente.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import hashlib
from pathlib import Path

_RUNTIME_BASE = "mrec_runtimes"
_STANDALONE = "python_standalone"  # pasta dentro do bundle


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _temp_base() -> Path:
    root = Path(os.environ.get("TEMP") or os.environ.get("TMP") or str(Path.home()))
    return root / _RUNTIME_BASE


def _exe_hash() -> str:
    try:
        p = Path(sys.executable)
        return hashlib.sha1(
            (str(p) + "_" + str(os.path.getsize(p))).encode("utf-8", "ignore")
        ).hexdigest()[:10]
    except Exception:
        return "default"


def _frozen_root() -> Path | None:
    if _frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return None


def runtime_python() -> Path:
    """Retorna o interpretador Python usado no subprocess do replay."""
    if not _frozen():
        return Path(sys.executable)

    vroot = _temp_base() / _exe_hash() / "venv"
    python = vroot / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    # já pronto?
    if python.exists() and _probe(python):
        return python

    meipass = _frozen_root()
    if meipass is None:
        raise RuntimeError("frozen sem _MEIPASS (anormal)")

    # 1) python standalone embutido
    host = meipass / _STANDALONE / ("python.exe" if os.name == "nt" else "python3")
    if not host.exists():
        # fallback: tenta python no PATH
        for cand in ("python", "py"):
            p = shutil.which(cand)
            if p:
                host = Path(p)
                break
    if not host.exists():
        raise FileNotFoundError(
            "Python runtime embutido não encontrado. "
            "Rode o app de dev (venv) ou reconstrua o .exe incluindo "
            "python-build-standalone no bundle."
        )

    # 2) venv limpo
    if vroot.exists():
        shutil.rmtree(vroot, ignore_errors=True)
    vroot.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(host), "-m", "venv", "--without-pip", str(vroot)], check=True)

    # 3) copia site-packages do bundle para o venv
    bundle_site = meipass / "site-packages"   # a spec coloca as deps aqui
    venv_site = _venv_site(vroot)
    venv_site.mkdir(parents=True, exist_ok=True)
    if bundle_site.exists():
        for item in bundle_site.iterdir():
            dest = venv_site / item.name
            if dest.exists():
                continue
            try:
                if item.is_dir():
                    shutil.copytree(item, dest, symlinks=True, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
            except Exception:
                pass

    # 4) .pth para o pacote macro_recorder (no bundle)
    if (meipass / "macro_recorder").exists():
        (venv_site / "_mrec.pth").write_text(f"{meipass}\n", encoding="utf-8")

    # 5) sanity
    if _probe(python):
        return python
    raise RuntimeError("mini-venv falhou no probe; veja <TEMP>/mrec_runtimes/")


def _probe(python: Path) -> bool:
    try:
        r = subprocess.run(
            [str(python), "-c", "import macro_recorder"],
            capture_output=True, timeout=45,
        )
        return r.returncode == 0
    except Exception:
        return False


def _venv_site(vroot: Path) -> Path:
    if os.name == "nt":
        return vroot / "Lib" / "site-packages"
    return vroot / "lib" / "python3" / "site-packages"


if __name__ == "__main__":
    print("runtime_python() ->", runtime_python())
