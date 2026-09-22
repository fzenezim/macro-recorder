"""Testes de exporter_md — gera passo-a-passo.md correto."""
from datetime import datetime
from pathlib import Path
import macro_recorder.exporter_md as md
from macro_recorder.events import Recording, Step, Action


# helpers para criar steps
def _rec(steps, name="rec", dur=5.0):
    return Recording(
        meta={"name": name},
        created_at=datetime(2026, 9, 2, 8, 0, 0),
        duration_s=dur,
        steps=steps,
    )


def _step(action, t=0.1, **kw):
    return Step(action=action, t=t, **kw)


# ── basic ─────────────────────────────────────────────────────────
def test_empty_recording_returns_header():
    rec = _rec([], dur=0.0)
    out = md.to_markdown(rec, [])
    assert "sem passos" in out


def test_md_header_contains_recording_name_and_duration():
    rec = _rec([], name="meu", dur=3.5)
    steps = [Step(action=Action.MOVE.value, t=0.0, x=0, y=0)]
    out = md.to_markdown(rec, steps)
    assert "meu" in out
    assert "3.50" in out


def test_md_contains_step_count_in_resumo():
    rec = _rec([], dur=1.0)
    steps = [Step(action=Action.CLICK.value, t=0.0, x=1, y=2)]
    out = md.to_markdown(rec, steps)
    assert "Total de passos: **1**" in out


# ── per-step formatting ───────────────────────────────────────────
def test_click_line_has_coords_and_crop():
    rec = _rec([], dur=1.0)
    s = Step(action=Action.CLICK.value, t=0.0, x=100, y=200, crop="a01.png")
    out = md.to_markdown(rec, [s])
    assert "Clique (100, 200)" in out
    assert "assets/a01.png" in out


def test_double_click_line():
    rec = _rec([], dur=1.0)
    s = Step(action=Action.DOUBLE_CLICK.value, t=0.0, x=1, y=1)
    out = md.to_markdown(rec, [s])
    assert "Duplo clique (1, 1)" in out


def test_right_click_line():
    rec = _rec([], dur=1.0)
    s = Step(action=Action.RIGHT_CLICK.value, t=0.0, x=5, y=6)
    out = md.to_markdown(rec, [s])
    assert "Clique direito (5, 6)" in out


def test_key_shortcut_combo():
    rec = _rec([], dur=1.0)
    s = Step(action=Action.KEY.value, t=0.25, keys=["ctrl", "s"])
    out = md.to_markdown(rec, [s])
    assert "`ctrl+s`" in out


def test_type_line_with_actual_text():
    rec = _rec([], dur=1.0)
    s = Step(action=Action.TYPE.value, t=0.1, text="olá mundo")
    out = md.to_markdown(rec, [s])
    assert "`olá mundo`" in out


def test_type_line_redacted():
    rec = _rec([], dur=1.0)
    s = Step(action=Action.TYPE.value, t=0.1, text="***", redacted=True)
    out = md.to_markdown(rec, [s])
    assert "***" in out
    assert "redigido" in out


def test_scroll_line():
    rec = _rec([], dur=1.0)
    s = Step(action=Action.SCROLL.value, t=0.1, x=10, y=20, dx=0, dy=-3)
    out = md.to_markdown(rec, [s])
    assert "Scroll (0, -3)" in out


def test_move_line():
    rec = _rec([], dur=1.0)
    s = Step(action=Action.MOVE.value, t=0.1, x=100, y=200)
    out = md.to_markdown(rec, [s])
    assert "Mover para (100, 200)" in out


# ── export_md writes file ─────────────────────────────────────────
def test_export_writes_file(tmp_path):
    rec = _rec([], dur=1.0)
    s = Step(action=Action.CLICK.value, t=0.0, x=1, y=2)
    out = md.export_md(rec, [s], tmp_path / "out" / "passo-a-passo.md")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Clique (1, 2)" in text
