# -*- coding: utf-8 -*-
"""Replay: executa o replay.py gerado por exporter_py.

Suporta --dry-run (apenas imprime os passos).
"""
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def _stage_data(record_dir: Path, data_path: Optional[str], verbose: bool) -> Optional[int]:
    """Copiam data_path -> record_dir/data.xlsx quando fornecido.

    O replay.py gerado lê sempre 'data.xlsx' ao lado. Se data_path é de fora
    da pasta, é copiado pra lá (data.xlsx) antes de executar. None = nada.
    """
    if not data_path:
        return None
    src = Path(data_path).expanduser()
    if not src.exists():
        if verbose:
            print(f"[mrec] ⚠  --data aponta pro arquivo ausente: {src}")
        return 3
    dst = record_dir / "data.xlsx"
    if src.resolve() != dst.resolve():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if verbose:
            print(f"[mrec] 📊 data.xlsx de {src.name} -> {dst}")
    else:
        if verbose:
            print(f"[mrec] 📊 data.xlsx = {dst.name}")
    return None


def replay_from_dir(record_dir: Path, dry_run: bool = False,
                    verbose: bool = True,
                    data_path: Optional[str] = None) -> int:
    """Executa o replay.py gerado em `record_dir`.

    Se ``data.xlsx`` existir na pasta, o replay itera uma vez por linha e
    substitui {placeholder} nos passos TYPE (1 linha = 1 execução). A flag
    ``data_path`` copia o xlsx informado pra lá antes de rodar.

    Retorna 0 no sucesso, 1 no falha, 2 em abortado (failsafe), 3 em data ausente.
    """
    record_dir = Path(record_dir)
    if not record_dir.is_dir():
        print(f"[erro] pasta nao existe: {record_dir}")
        return 1

    _err = _stage_data(record_dir, data_path, verbose)
    if _err is not None:
        return _err

    replay_py = record_dir / "replay.py"
    recording_json = record_dir / "recording.json"
    if not replay_py.exists():
        print(f"[erro] replay.py nao existe em {record_dir}")
        return 1

    if verbose:
        print(f"[mrec] replay de {record_dir.name}")
        if dry_run:
            print("[mrec] modo DRY-RUN — so imprime, nao executa\n")
        else:
            print("[mrec] modo EXECUCAO — move o mouse! (Failsafe: mouse top-left aborta)\n")

    # executa subprocess
    cmd = [sys.executable, str(replay_py)]
    if dry_run:
        # injecta --dry-run como arg p/ o replay.py ler
        cmd.append("--dry-run")

    if verbose:
        print(f"[mrec] cmd: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("[erro] timeout na execucao")
        return 1
    except Exception as e:
        print(f"[erro] {e}")
        return 1

    if verbose and result.stdout:
        print(result.stdout)
    if verbose and result.stderr:
        print(result.stderr, file=sys.stderr)

    return result.returncode


def run_replay(folder: str, dry_run: bool = False,
               data_path: Optional[str] = None) -> int:
    """Executa o replay da pasta informada."""
    return replay_from_dir(Path(folder), dry_run=dry_run, data_path=data_path)
