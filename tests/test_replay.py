"""Testes de replay.py — executa replay.py gerado."""
from pathlib import Path
import unittest.mock as mock

import macro_recorder.replay as replay
from macro_recorder.events import Step, Action, Recording


def _mk_record(tmp_path: Path, steps: list) -> Path:
    d = tmp_path / "rec"
    d.mkdir()
    # grava um replay.py minimo (fakes)
    (d / "replay.py").write_text(
        "import sys\n"
        "print('dry-run' if '--dry-run' in sys.argv else 'exec')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    (d / "recording.json").write_text("{}", encoding="utf-8")
    (d / "assets").mkdir()
    return d


# ── basic ─────────────────────────────────────────────────────────
def test_replay_nonexistent_dir_fails(tmp_path):
    rc = replay.replay_from_dir(tmp_path / "nope")
    assert rc == 1


def test_replay_without_replay_py_fails(tmp_path):
    d = tmp_path / "rec"
    d.mkdir()
    rc = replay.replay_from_dir(d)
    assert rc == 1


def test_replay_executes_replay_py(tmp_path):
    d = _mk_record(tmp_path, [])
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        rc = replay.replay_from_dir(d, verbose=False)
    assert rc == 0
    args, _ = run.call_args
    # o cmd inclui o replay.py
    assert any("replay.py" in str(a) for a in args[0])


def test_replay_dry_run_passes_flag(tmp_path):
    d = _mk_record(tmp_path, [])
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        replay.replay_from_dir(d, dry_run=True, verbose=False)
    args, _ = run.call_args
    flags = [a for a in args[0] if a.startswith("--")]
    assert "--dry-run" in flags
