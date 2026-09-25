"""Entry point:  python -m macro_recorder [record|replay|--gui ...]

Permite o GUI usar subprocess([python, -m, macro_recorder, replay, <pasta>]).
Com --gui abre a GUI directly (para PyInstaller --noconsole).
"""

import sys


def main() -> int:
    if "--gui" in sys.argv or ("-g" in sys.argv):
        # abre a GUI directly
        from macro_recorder.gui import main as gui_main
        gui_main()
        return 0

    from macro_recorder.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
