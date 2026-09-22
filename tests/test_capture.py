"""Testes de capture.py — crop de tela + find_anchor.

Usa mocks de pyautogui (sem display no CI) para validar a lógica:
    - make_crop: região ao redor do cursor (margem 60), clamp em bordas,
      multimonitor (coords negativas), grava PNG via .save();
    - find_anchor: cascata 0.9 → 0.8 → 0.7, fallback confidence=None
      quando opencv ausente, AnchorNotFound quando nada acerta;
    - _clamp_box: comportamento de clamp em retângulo virtual.

Sem hardware: todos os mocks vivem aqui.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest


# ───────────────────────────────────────────────────────────────────────────
# Mocks
# ───────────────────────────────────────────────────────────────────────────
class _MockBox:
    """Imita pyautogui.Box(left, top, width, height)."""

    def __init__(self, left: int, top: int, width: int, height: int):
        self.left = left
        self.top = top
        self.width = width
        self.height = height

    def __repr__(self):
        return (
            f"Box(left={self.left}, top={self.top}, "
            f"width={self.width}, height={self.height})"
        )


class _CroppedImg:
    """Screenshot mock — guarda a região pedida e implementa .save()."""

    def __init__(self):
        self.save_called = 0
        self.size = (120, 120)
        self.region_used = None

    def save(self, p, **kw):
        self.save_called += 1
        Path(p).write_bytes(b"PNG-fake")
        self.last_path = p

    def close(self):
        pass


@pytest.fixture
def mock_pgui(monkeypatch):
    """Mock do módulo pyautogui (screenshot + locateOnScreen).

    Atributos controláveis pelos tests:
        per_confidence:  {confidence: Box | None}
        next_result:     Box | None  (usado quando confidence não está em per_confidence)
        raise_on_confidence:  bool (simula opencv ausente)
        last_screenshot:  última imagem devolvida por screenshot()
        locate_calls:     lista de confidences (ou None) tentadas
    """
    import pyautogui as real

    state = {
        "per_confidence": {},
        "next_result": None,
        "raise_on_confidence": False,
        "last_screenshot": None,
        "locate_calls": [],
    }

    def fake_screenshot(region=None):
        img = _CroppedImg()
        img.region_used = region
        state["last_screenshot"] = img
        return img

    def fake_locate_on_screen(image, confidence=None, **kw):
        state["locate_calls"].append(confidence)
        if state["raise_on_confidence"] and confidence is not None:
            # simula opencv ausente
            raise AssertionError(
                "OpenCV is required for the confidence keyword argument"
            )
        if confidence in state["per_confidence"]:
            return state["per_confidence"][confidence]
        return state["next_result"]

    monkeypatch.setattr(real, "screenshot", fake_screenshot)
    monkeypatch.setattr(real, "locateOnScreen", fake_locate_on_screen)

    # expõe como namespace simples (mock_pgui.per_confidence etc.)
    # — last_screenshot precisa ser property p/ refletir atualizações em state
    class _NS:
        per_confidence = state["per_confidence"]
        next_result_holder = state  # referência ao dict
        locate_calls = state["locate_calls"]

        @property
        def next_result(self):
            return state["next_result"]

        @next_result.setter
        def next_result(self, v):
            state["next_result"] = v

        @property
        def raise_on_confidence(self):
            return state["raise_on_confidence"]

        @raise_on_confidence.setter
        def raise_on_confidence(self, v):
            state["raise_on_confidence"] = v

        @property
        def last_screenshot(self):
            return state["last_screenshot"]

    ns = _NS()
    return ns


# ───────────────────────────────────────────────────────────────────────────
# crop() — região ao redor do cursor, com clamp
# ───────────────────────────────────────────────────────────────────────────
def test_default_margin_is_60():
    from macro_recorder.capture import CROP_MARGIN
    assert CROP_MARGIN == 60


def test_crop_region_normal(mock_pgui, tmp_path: Path):
    """Cursor em (500, 500) → região (440, 440, 120, 120)."""
    from macro_recorder.capture import make_crop
    out = tmp_path / "a01.png"
    region, path = make_crop(500, 500, screen_size=(1920, 1080), out_path=out)
    assert region == (440, 440, 120, 120)
    assert path == out
    assert mock_pgui.last_screenshot.region_used == region
    assert out.exists()


def test_crop_region_clamps_at_top_left(mock_pgui, tmp_path: Path):
    """Cursor perto da origem: left/top clamp em 0; width/height seguem."""
    from macro_recorder.capture import make_crop
    out = tmp_path / "a01.png"
    L, T, W, H = make_crop(10, 10, screen_size=(1920, 1080), out_path=out)[0]
    assert L == 0
    assert T == 0
    # cursor 10,10 + margem 60 → até (70, 70), clamp em 0 à esquerda -> 70 px
    assert W == 70
    assert H == 70


def test_crop_region_clamps_at_bottom_right(mock_pgui, tmp_path: Path):
    """Cursor perto da borda inferior direita de 1920x1080."""
    from macro_recorder.capture import make_crop
    out = tmp_path / "a01.png"
    L, T, W, H = make_crop(1915, 1075, screen_size=(1920, 1080), out_path=out)[0]
    assert L == 1855
    assert T == 1015
    assert L + W == 1920
    assert T + H == 1080


def test_crop_region_negative_coords_multimonitor(mock_pgui, tmp_path: Path):
    """Segundo monitor à esquerda: coord negativa é válida."""
    from macro_recorder.capture import make_crop
    out = tmp_path / "a01.png"
    L, T, W, H = make_crop(
        -50, 100,
        screen_size=(1920, 1080),
        virtual_size=(3840, 1080),
        virtual_origin=(-1920, 0),
        out_path=out,
    )[0]
    assert (L, T, W, H) == (-110, 40, 120, 120)


def test_crop_no_vargs_uses_pyautogui_size(mock_pgui, tmp_path: Path, monkeypatch):
    """Sem screen_size/virtual_size, usa screenshot().size como área (exato)."""
    from macro_recorder.capture import make_crop
    out = tmp_path / "a01.png"
    # mock: screenshot() devolve _CroppedImg com size (120, 120) por default
    # cursor (50, 50) com margem 60:
    #   left  = 50-60 = -10 → clamp em 0
    #   right = 50+60 = 110 → dentro de 120, ok
    #   top/bottom idem → (0, 0, 110, 110)
    L, T, W, H = make_crop(50, 50, out_path=out)[0]
    assert (L, T, W, H) == (0, 0, 110, 110)


# ───────────────────────────────────────────────────────────────────────────
# find_anchor() — cascata confidence 0.9 → 0.8 → 0.7
# ───────────────────────────────────────────────────────────────────────────
def test_find_anchor_first_hit(mock_pgui, tmp_path: Path):
    """Confidence 0.9 direto acerta."""
    from macro_recorder.capture import find_anchor
    box = _MockBox(100, 200, 120, 120)
    mock_pgui.per_confidence[0.9] = box
    crop = tmp_path / "a01.png"; crop.write_bytes(b"fake")
    cx, cy = find_anchor(crop, step_no=1)
    assert (cx, cy) == (160, 260)
    assert mock_pgui.locate_calls == [0.9]


def test_find_anchor_fallback(mock_pgui, tmp_path: Path):
    """0.9 não acha; 0.8 acha; 0.7 não é tentado."""
    from macro_recorder.capture import find_anchor
    box = _MockBox(50, 50, 100, 100)
    mock_pgui.per_confidence[0.9] = None
    mock_pgui.per_confidence[0.8] = box
    crop = tmp_path / "a01.png"; crop.write_bytes(b"fake")
    cx, cy = find_anchor(crop, step_no=2)
    assert (cx, cy) == (100, 100)
    assert mock_pgui.locate_calls == [0.9, 0.8]


def test_find_anchor_not_found(mock_pgui, tmp_path: Path):
    """Nenhuma confidence acha → AnchorNotFound com passo + instrução."""
    from macro_recorder.capture import AnchorNotFound, find_anchor
    mock_pgui.per_confidence = {0.9: None, 0.8: None, 0.7: None}
    crop = tmp_path / "a03.png"; crop.write_bytes(b"fake")
    with pytest.raises(AnchorNotFound) as e:
        find_anchor(crop, step_no=3)
    msg = str(e.value).lower()
    assert "3" in msg
    assert "âncora" in msg or "anchor" in msg


def test_find_anchor_opencv_missing_fallback(mock_pgui, tmp_path: Path):
    """Sem opencv: confidence<1 lança → cai para confidence=None (match exato)."""
    from macro_recorder.capture import find_anchor
    box = _MockBox(10, 20, 40, 40)
    mock_pgui.raise_on_confidence = True
    mock_pgui.next_result = box
    crop = tmp_path / "a01.png"; crop.write_bytes(b"fake")
    cx, cy = find_anchor(crop, step_no=1)
    # primeira tentativa com confidence (0.9), depois confiança=None
    assert mock_pgui.locate_calls[0] == 0.9
    assert None in mock_pgui.locate_calls
    assert (cx, cy) == (30, 40)


def test_find_anchor_missing_crop(tmp_path: Path):
    """Crop inexistente → FileNotFoundError (não AnchorNotFound)."""
    from macro_recorder.capture import find_anchor
    with pytest.raises(FileNotFoundError):
        find_anchor(tmp_path / "a01.png", step_no=1)


# ───────────────────────────────────────────────────────────────────────────
# _clamp_box (unit)
# ───────────────────────────────────────────────────────────────────────────
def test_clamp_box_inside():
    from macro_recorder.capture import _clamp_box
    L, T, R, B = _clamp_box(100, 200, 500, 600,
                            virtual_origin=(0, 0), virtual_size=(1920, 1080))
    assert (L, T, R, B) == (100, 200, 500, 600)


def test_clamp_box_outside_left_top():
    from macro_recorder.capture import _clamp_box
    L, T, R, B = _clamp_box(-20, -30, 500, 500,
                            virtual_origin=(0, 0), virtual_size=(1920, 1080))
    assert L == 0 and T == 0


def test_clamp_box_multimonitor_negative_origin():
    from macro_recorder.capture import _clamp_box
    # virtual: x ∈ [-1920, 1920], y ∈ [0, 1080]
    L, T, R, B = _clamp_box(-20, -30, 500, 500,
                            virtual_origin=(-1920, 0), virtual_size=(3840, 1080))
    # top -30 fica acima da borda superior do virtual (y=0) → clamp em 0
    assert (L, T, R, B) == (-20, 0, 500, 500)


def test_clamp_box_no_area():
    """Virtual size (0, 0) → sem clamp."""
    from macro_recorder.capture import _clamp_box
    assert _clamp_box(-5, -6, 7, 8, virtual_origin=(0, 0), virtual_size=(0, 0)) == (-5, -6, 7, 8)
