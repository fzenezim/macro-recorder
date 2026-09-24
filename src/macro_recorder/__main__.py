"""Entry point:  python -m macro_recorder [record|replay ...]

Permite o GUI usar subprocess([python, -m, macro_recorder, replay, <pasta>]).
"""

from macro_recorder.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
