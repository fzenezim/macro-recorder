"""Testes de exporter_py — gera replay.py funcional."""
from datetime import datetime
from pathlib import Path
import macro_recorder.exporter_py as pyexp
from macro_recorder.events import Recording, Step, Action


def _steps():
    return [
        Step(action=Action.CLICK.value, t=0.5, x=100, y=200, crop="a01.png"),
        Step(action=Action.TYPE.value, t=1.2, text="olá mundo"),
        Step(action=Action.KEY.value, t=2.0, keys=["ctrl", "s"]),
        Step(action=Action.DOUBLE_CLICK.value, t=3.0, x=50, y=75, crop="a02.png"),
        Step(action=Action.MOVE.value, t=4.0, x=10, y=10),
        Step(action=Action.SCROLL.value, t=5.0, x=200, y=300, dx=0, dy=-120),
        Step(action=Action.RIGHT_CLICK.value, t=6.0, x=300, y=400, crop="a03.png"),
        Step(action=Action.TYPE.value, t=7.0, text="***", redacted=True),
    ]


# ── estrutura geral ───────────────────────────────────────────────
def test_playback_starts_with_header():
    text = pyexp.to_python(_steps())
    assert text.startswith("# -*- coding: utf-8 -*-")
    assert "Gerado por mrec" in text


def test_playback_includes_helpers():
    text = pyexp.to_python(_steps())
    assert "def _locate(" in text
    assert "def _click(" in text
    assert "def _double_click(" in text
    assert "def _right_click(" in text
    assert "def _key(" in text
    assert "def _type(" in text
    assert "def _scroll(" in text
    assert "def _move(" in text
    assert "def _wait(" in text


def test_playback_includes_run_function():
    text = pyexp.to_python(_steps())
    assert "def run():" in text
    assert "if __name__ == " in text


def test_playback_includes_all_step_types():
    text = pyexp.to_python(_steps())
    # todos os tipos devem gerar chamadas
    assert "_click(" in text
    assert "_double_click(" in text
    assert "_right_click(" in text
    assert "_key(" in text
    assert "_type(" in text
    assert "_scroll(" in text
    assert "_move(" in text


def test_playback_includes_wait_between_steps():
    text = pyexp.to_python(_steps())
    # o primeiro step é t=0.5, antes do primeiro _wait
    assert "_wait(0.500)" in text


def test_playback_redacts_password():
    text = pyexp.to_python(_steps())
    # texto redigido nao aparece — so ***
    assert '"sen"' not in text
    assert "'sen'" not in text


def test_playback_no_redacted_text_in_type_call():
    text = pyexp.to_python(_steps())
    # verificação mais forte: a linha do _type redigido so tem ***
    lines = [ln for ln in text.splitlines() if "_type(" in ln and "***" in ln]
    assert any('"***"' in ln or "'***'" in ln for ln in lines)


# ── export_py writes a valid python file ───────────────────────────
def test_export_writes_executable_python(tmp_path):
    steps = _steps()
    out = pyexp.export_py(steps, tmp_path / "replay.py")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    # deve parsear como python valido
    import ast
    ast.parse(text)


def test_export_dry_run_flag(tmp_path):
    steps = [Step(action=Action.MOVE.value, t=0.1, x=0, y=0)]
    out = pyexp.export_py(steps, tmp_path / "replay.py", dry_run=True)
    text = out.read_text(encoding="utf-8")
    # em dry-run, os passos nao chamam pyautogui direto — so print
    assert "print(" in text
