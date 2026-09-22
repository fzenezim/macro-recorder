"""Testes do modelo de dados (Step / Recording).

Sem hardware: injetamos dicts sintéticos e validamos round-trip JSON.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from macro_recorder.events import Action, Recording, Step


# ───────────────────────────────────────────────────────────────────────────
# Step round-trip
# ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "step",
    [
        Step(action=Action.CLICK.value, t=1.0, x=120, y=340, crop="assets/a01.png"),
        Step(action=Action.DOUBLE_CLICK.value, t=1.4, x=120, y=340),
        Step(action=Action.TYPE.value, t=2.0, text="olá mundo"),
        Step(action=Action.KEY.value, t=2.5, keys=["ctrl", "s"]),
        Step(action=Action.SCROLL.value, t=3.0, dx=0, dy=-3),
        Step(action=Action.TYPE.value, t=4.0, text="***", redacted=True),
    ],
    ids=["click", "double_click", "type", "key", "scroll", "redacted"],
)
def test_step_roundtrip(step: Step):
    d = step.to_dict()
    again = Step.from_dict(d)
    assert again == step


# ───────────────────────────────────────────────────────────────────────────
# Step.to_dict omite campos nulos
# ───────────────────────────────────────────────────────────────────────────
def test_step_to_dict_omits_none():
    d = Step(action=Action.CLICK.value, t=0.5, x=1, y=2).to_dict()
    assert "text" not in d
    assert "keys" not in d
    assert "dx" not in d
    assert "redacted" not in d  # False não é serializado


# ───────────────────────────────────────────────────────────────────────────
# Recording round-trip e save/load
# ───────────────────────────────────────────────────────────────────────────
def _sample_recording() -> Recording:
    return Recording(
        created_at="2026-09-02T10:00:00Z",
        duration_s=4.2,
        steps=[
            Step(action=Action.CLICK.value, t=0.3, x=120, y=340, crop="assets/a01.png"),
            Step(action=Action.TYPE.value, t=1.0, text="olá mundo"),
            Step(action=Action.KEY.value, t=1.5, keys=["ctrl", "s"]),
        ],
        meta={"hotkey": "f9"},
    )


def test_recording_roundtrip():
    d = _sample_recording()
    again = Recording.from_dict(d.to_dict())
    assert again == d


def test_recording_save_load(tmp_path: Path):
    rec = _sample_recording()
    target = tmp_path / "recording.json"
    rec.save_json(target)
    assert target.exists()
    loaded = Recording.load_json(target)
    assert loaded == rec
    # o JSON é legível e usa UTF-8 (sem \u escapes p/ acentos)
    raw = target.read_text(encoding="utf-8")
    assert "olá mundo" in raw  # texto acentado preservado


# ───────────────────────────────────────────────────────────────────────────
# counts() para o resumo ao parar
# ───────────────────────────────────────────────────────────────────────────
def test_recording_counts():
    rec = _sample_recording()
    c = rec.counts()
    assert c["total"] == 3
    assert c["click"] == 1
    assert c["type"] == 1
    assert c["key"] == 1
    assert c["scroll"] == 0
