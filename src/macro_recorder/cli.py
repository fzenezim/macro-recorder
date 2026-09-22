"""CLI do Macro Recorder — entry point `mrec`.

Subcomandos:
    mrec record    grava uma macro (F9 liga/desliga)
    mrec replay    reproduz uma pasta de gravação (--dry-run só imprime)

O código do `record` e do `replay` vive nos módulos `listener.py` e
`replay.py` deste pacote; a CLI apenas despacha.
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser

from macro_recorder import __version__


def _build_parser() -> ArgumentParser:
    p = ArgumentParser(
        prog="mrec",
        description=(
            "Gravador de macro estilo Excel — grava cliques e teclas e "
            "reproza por âncora visual (locateOnScreen)."
        ),
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"mrec {__version__}",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "record",
        help="grava uma macro (F9 liga/desliga; MREC_HOTKEY sobrescreve)",
    )
    rp = sub.add_parser("replay", help="reproduz uma pasta de gravação")
    rp.add_argument("folder", help="pasta contendo recording.json")
    rp.add_argument(
        "--dry-run",
        action="store_true",
        help="imprime os passos sem agir sobre a tela",
    )
    return p


def main(argv: list | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "record":
        from macro_recorder.listener import run_record
        return run_record()
    if args.cmd == "replay":
        from macro_recorder.replay import run_replay
        return run_replay(args.folder, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
