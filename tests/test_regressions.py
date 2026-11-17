# -*- coding: utf-8 -*-
"""Regressão — correções de F9/minimizar + clique exato (crop_off).

Bug 1 (GUI):
    - minimizar usa iconify() (taskbar), não withdrawn() (some da tela);
    - start-when-ready: GUI espera o listener pynput ativo antes do 1º F9
      programático → o F9 de PARAR funciona.
Bug 2 (replay):
    - make_cascading_crops devolve o offset do clique DENTRO do crop;
    - o listener grava step.crop_off;
    - o replay clica em top_left + crop_off (ponto exato), não no centro;
    - confidence floor 0.8 (nunca abaixo) e cascata a partir da conf da GUI;
    - pausa fixa (MREC_PAUSE) entre passos.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from macro_recorder.events import Step, Action


# ───────────────────────────────────────────────────────────────────────────
# capture.make_cascading_crops — 4º retorno = offset do clique
# ───────────────────────────────────────────────────────────────────────────
class _FakeImg:
    """Imagem fake: .save() grava um PNG real (com cores) via PIL."""

    def __init__(self, region, w=120, h=120):
        self.region = region
        self.size = (w, h)

    def save(self, p, **kw):
        from PIL import Image
        img = Image.new("RGB", (max(2, self.size[0]), max(2, self.size[1])), "white")
        px = img.load()
        for i in range(0, img.width, 4):
            for j in range(0, img.height, 4):
                px[i, j] = ((i * 7) % 256, (j * 13) % 256, (i + j) % 256)
        img.save(p, "PNG")

    def close(self):
        pass


@pytest.fixture
def cascaded_img(monkeypatch, tmp_path):
    """Mock do pyautogui.screenshot devolvendo imagem com cores únicas."""
    import pyautogui as real

    def fake_screenshot(region=None, **kw):
        w = region[2] if region else 120
        h = region[3] if region else 120
        return _FakeImg(region, w, h)

    monkeypatch.setattr(real, "screenshot", fake_screenshot)
    return tmp_path


def test_make_cascading_crops_returns_click_offset(cascaded_img):
    """4ª posição do retorno = (x-L, y-T) do crop escolhido (1ª tentativa)."""
    from macro_recorder.capture import make_cascading_crops
    region, chosen, saved, off = make_cascading_crops(
        500, 400, out_path=cascaded_img / "a01.png",
        screen_size=(1920, 1080),
    )
    assert len(saved) >= 1
    L, T, W, H = region
    # 120x120 (margem 60) em volta de (500, 400):
    assert (L, T, W, H) == (440, 340, 120, 120)
    # offset do clique dentro do crop = (500-440, 400-340)
    assert off == (60, 60)
    assert chosen.name == "a01.png"


def test_make_cascading_crops_offset_asymmetric(cascaded_img):
    """Clamp na borda → offset assimétrico (clique não fica no centro)."""
    from macro_recorder.capture import make_cascading_crops
    region, chosen, saved, off = make_cascading_crops(
        5, 400, out_path=cascaded_img / "a02.png",
        screen_size=(1920, 1080),
    )
    L, T, W, H = region
    assert L == 0  # clampado na borda esquerda
    assert T == 340  # 400-60
    # clique em (5, 400) → offset (5, 60) DENTRO do crop
    assert off == (5, 60)


def test_make_cascading_crops_offset_clamped_at_border(cascaded_img, monkeypatch):
    """Clique perto da borda → região clampada, offset reflete o clamp."""
    from macro_recorder.capture import make_cascading_crops
    region, chosen, saved, off = make_cascading_crops(
        30, 20, out_path=cascaded_img / "a03.png",
        screen_size=(1920, 1080),
    )
    L, T, W, H = region
    assert L == 0 and T == 0  # clampada na borda
    assert off == (30 - 0, 20 - 0)


# ───────────────────────────────────────────────────────────────────────────
# events — round-trip crop_off
# ───────────────────────────────────────────────────────────────────────────
def test_step_crop_off_roundtrip():
    s = Step(action=Action.CLICK.value, t=1.0, x=100, y=200,
             crop="assets/a01.png", crop_off=(41, 57))
    d = s.to_dict()
    assert d["crop_off"] == [41, 57]
    s2 = Step.from_dict(d)
    assert s2.crop_off == (41, 57)
    assert isinstance(s2.crop_off, tuple)


def test_step_crop_off_default_none():
    s = Step(action=Action.CLICK.value, t=1.0, x=100, y=200)
    assert s.crop_off is None
    # to_dict omite o campo quando é None (compatível com gravações antigas)
    assert s.to_dict().get("crop_off") is None
    assert Step.from_dict(s.to_dict()).crop_off is None


# ───────────────────────────────────────────────────────────────────────────
# exporter_py — offset, confidence, pausa no replay gerado
# ───────────────────────────────────────────────────────────────────────────
def test_exporter_click_step_emits_off(tmp_path):
    """Passo com crop_off → linha do replay usa off=(dx,dy)."""
    import macro_recorder.exporter_py as pyexp
    steps = [Step(action=Action.CLICK.value, t=0.5, x=100, y=200,
                  crop="a01.png", crop_off=(41, 57))]
    text = pyexp.to_python(steps)
    line = next(ln for ln in text.splitlines()
                if "_click(" in ln and "def " not in ln)
    assert "off=(41, 57)" in line
    assert "x=None" in line and "y=None" in line


def test_exporter_no_off_when_absent(tmp_path):
    """Passo sem crop_off → linha do replay NÃO usa off=.
    (fallback para o centro do crop no _locate)"""
    import macro_recorder.exporter_py as pyexp
    steps = [Step(action=Action.CLICK.value, t=0.5, x=100, y=200,
                  crop="a01.png")]
    text = pyexp.to_python(steps)
    line = next(ln for ln in text.splitlines()
                if "_click(" in ln and "def " not in ln)
    assert "off=" not in line


def test_exporter_confidence_floor_is_08(tmp_path):
    """Qualquer conf da GUI ≥ 0.8; nunca gera confidence abaixo de 0.8."""
    import macro_recorder.exporter_py as pyexp
    for conf in (0.5, 0.7, 0.75, 0.8, 0.9):
        text = pyexp.to_python([Step(action=Action.CLICK.value, t=0.5,
                                     x=1, y=1, crop="a01.png")],
                               confidence=conf)
        assert "0.7)" not in text.replace(" ", ""), \
            f"conf={conf} gerou cascade abaixo do floor 0.8"
    # conf 0.9 → cascade (0.9, 0.85, 0.8)
    text = pyexp.to_python([Step(action=Action.CLICK.value, t=0.5,
                                 x=1, y=1, crop="a01.png")], confidence=0.9)
    assert "0.85" in text and "0.8" in text
    # conf 0.8 → floor exato
    text = pyexp.to_python([Step(action=Action.CLICK.value, t=0.5,
                                 x=1, y=1, crop="a01.png")], confidence=0.8)
    assert "(0.8,)" in text


def test_confs_for_floor_and_cascade():
    import macro_recorder.exporter_py as pyexp
    assert pyexp._confs_for(0.9) == (0.9, 0.85, 0.8)
    assert pyexp._confs_for(0.95) == (0.95, 0.9, 0.85, 0.8)
    assert pyexp._confs_for(0.8) == (0.8,)
    # floor: valores pedidos abaixo de 0.8 viram 0.8
    assert pyexp._confs_for(0.7) == (0.8,)
    assert pyexp._confs_for(0.5) == (0.8,)
    # nunca sobe acima do pedido
    assert pyexp._confs_for(0.95)[0] == 0.95


def test_exporter_pause_call_between_steps(tmp_path):
    """Passos de clique separados por _pause() (MREC_PAUSE) no replay."""
    import macro_recorder.exporter_py as pyexp
    steps = [
        Step(action=Action.CLICK.value, t=0.5, x=100, y=200, crop="a01.png",
             crop_off=(10, 10)),
        Step(action=Action.DOUBLE_CLICK.value, t=3.0, x=50, y=75,
             crop="a02.png", crop_off=(20, 20)),
    ]
    text = pyexp.to_python(steps)
    # o helper existe...
    assert "def _pause():" in text
    # ...e é chamado entre os passos (2 cliques → 2 _pause)
    pauses = [ln for ln in text.splitlines()
              if ln.strip() == "_pause()"]
    assert len(pauses) >= 2
    # env MREC_PAUSE lido no header
    assert "MREC_PAUSE" in text


def test_exported_replay_compiles(tmp_path):
    """O replay.py gerado é Python válido (compila)."""
    import compileall
    import macro_recorder.exporter_py as pyexp
    steps = [
        Step(action=Action.CLICK.value, t=0.5, x=100, y=200, crop="a01.png",
             crop_off=(41, 57)),
        Step(action=Action.TYPE.value, t=1.0, text="olá"),
        Step(action=Action.DOUBLE_CLICK.value, t=2.0, x=50, y=75,
             crop="a02.png", crop_off=(10, 20)),
        Step(action=Action.RIGHT_CLICK.value, t=3.0, x=300, y=400,
             crop="a03.png"),
        Step(action=Action.KEY.value, t=4.0, keys=["ctrl", "s"]),
    ]
    out = pyexp.export_py(steps, tmp_path / "replay.py", confidence=0.9)
    assert out.exists()
    compileall.compile_file(str(out), quiet=1)
    text = out.read_text(encoding="utf-8")
    assert "off=(41, 57)" in text
    assert "off=(10, 20)" in text
    assert "off=" not in text.split("_right_click(crop='a03.png'")[1].split("\n")[0]


# ───────────────────────────────────────────────────────────────────────────
# GUI — iconify (não withdrawn) + start-when-ready
# ───────────────────────────────────────────────────────────────────────────
def test_gui_source_uses_iconify_not_withdrawn():
    """O código-fonte da GUI não usa mais state('withdrawn').

    Lê o arquivo direto (import do gui exigiria customtkinter instalado).
    """
    src = (
        Path(__file__).resolve().parent.parent
        / "src" / "macro_recorder" / "gui.py"
    ).read_text(encoding="utf-8")
    assert 'state("withdrawn")' not in src, \
        "GUI ainda minimiza com withdrawn (some da tela, sem taskbar)"
    assert "self.iconify()" in src
    # start-when-ready presente: o 1º F9 programático espera o gate
    # rec._ready (setado pelo run() quando o hook pynput já está ativo).
    assert "_start_when_ready" in src
    assert "rec._ready" in src


def test_recorder_has_ready_gate():
    """Recorder expõe wait_ready (gate do F9 programático da GUI)."""
    from macro_recorder.listener import Recorder
    assert hasattr(Recorder, "wait_ready")
    import threading
    rec = Recorder.__new__(Recorder)  # sem __init__ (pynput) — só o event
    rec._ready = threading.Event()
    assert rec.wait_ready(timeout=0.01) is False
    rec._ready.set()
    assert rec.wait_ready(timeout=0.01) is True
