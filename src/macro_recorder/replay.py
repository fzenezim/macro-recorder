# -*- coding: utf-8 -*-
"""Replay: executa o replay.py gerado por exporter_py.

Suporta --dry-run (apenas imprime os passos).
"""
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

def _is_dry_run(args: List[str]) -> bool:
    return "--dry-run" in args

def _extract_dry_run(args: List[str]) -> List[str]:
    return [a for a in args if a != "--dry-run"]


def replay_from_dir(record_dir: Path, dry_run: bool = False,
                    verbose: bool = True) -> int:
    """Executa o replay.py gerado em `record_dir`.
    
    Retorna 0 no sucesso, 1 no falha, 2 em abortado (failsafe).
    """
    record_dir = Path(record_dir)
    if not record_dir.is_dir():
        print(f"[erro] pasta nao existe: {record_dir}")
        return 1

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


def run_replay(folder: str, dry_run: bool = False) -> int:
    """Executa o replay da pasta informada."""
    from pathlib import Path
    return replay_from_dir(Path(folder), dry_run=dry_run)
