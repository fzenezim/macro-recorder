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
    assert "def run(data_row=None):" in text
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


# ── bug fix: crop steps must NOT pass fixed x/y to _click ─────────
# Quando o passo tem `crop` (âncora visual), a linha gerada DEVE usar
# x=None, y=None para forçar o _locate (matcher visual). Passar os
# valores fixos da gravação (x=500, y=300) faz o replay clicar no
# ponto onde O USUÁRIO CLICOU NA GRAVAÇÃO, ignorando a âncora — ou
# seja, o clique cai na posição errada se a janela se moveu.
def test_click_step_with_crop_uses_none_xy():
    """Step de CLICK com crop deve gerar _click(crop=..., x=None, y=None)."""
    steps = [Step(action=Action.CLICK.value, t=0.5, x=500, y=300, crop="a01.png")]
    text = pyexp.to_python(steps)
    # a linha do _click deve ter x=None e y=None (não x=500, y=300)
    click_lines = [ln for ln in text.splitlines() if "_click(" in ln]
    assert click_lines, "nenhuma linha de _click foi gerada"
    line = click_lines[0]
    assert "x=None" in line, f"esperava x=None, got: {line!r}"
    assert "y=None" in line, f"esperava y=None, got: {line!r}"
    # os valores fixos da gravação NÃO devem aparecer
    assert "x=500" not in line
    assert "y=300" not in line


def test_double_click_step_with_crop_uses_none_xy():
    steps = [Step(action=Action.DOUBLE_CLICK.value, t=1.0, x=100, y=200, crop="a02.png")]
    text = pyexp.to_python(steps)
    line = next(ln for ln in text.splitlines() if "_double_click(" in ln)
    assert "x=None" in line and "y=None" in line
    assert "x=100" not in line and "y=200" not in line


def test_right_click_step_with_crop_uses_none_xy():
    steps = [Step(action=Action.RIGHT_CLICK.value, t=1.0, x=300, y=400, crop="a03.png")]
    text = pyexp.to_python(steps)
    line = next(ln for ln in text.splitlines() if "_right_click(" in ln)
    assert "x=None" in line and "y=None" in line
    assert "x=300" not in line and "y=400" not in line


def test_click_step_without_crop_uses_fixed_xy():
    """Step de CLICK SEM crop deve manter os valores fixos (comportamento atual)."""
    steps = [Step(action=Action.CLICK.value, t=0.5, x=500, y=300)]
    text = pyexp.to_python(steps)
    # a linha do PASSO (dentro de run), não o def do helper
    lines = [ln for ln in text.splitlines()
             if "_click(x=500" in ln or ("_click(" in ln and "def " not in ln and "x=500" in ln)]
    assert lines, "nenhuma linha do passo _click com x=500 encontrada"
    line = lines[0]
    assert "x=500" in line
    assert "y=300" in line
    assert "crop=" not in line
