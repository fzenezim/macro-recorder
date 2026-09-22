"""Unit tests for EventCollector in listener.py.

Injects synthetic pynput-style events (no real listeners) and validates how
they are grouped into Steps: type merging, click/double-click, shortcuts,
scroll, move absorption, password redaction, and the F9 hotkey.
"""

import json
from pathlib import Path
from macro_recorder.events import Action
from macro_recorder.listener import EventCollector, FakeKey


# ── fakes ─────────────────────────────────────────────────────────────


class _TestClock:
    """Clock sintetico: now()/tick(dt) para controlar o tempo nos tests."""

    def __init__(self, start: float = 0.0):
        self.now_ = start

    def now(self) -> float:
        return self.now_

    def tick(self, dt: float) -> float:
        self.now_ += dt
        return self.now_


class FakeMouseEvent:
    """Fake de um evento de mouse pynput (move/click/scroll)."""

    def __init__(self, x=0, y=0, button=None, dx=0, dy=0, t=0.0):
        self.x = x
        self.y = y
        self.button = button
        self.dx = dx
        self.dy = dy
        self.t = t


class FakeKeyPress:
    def __init__(self, key):
        self.key = key


class FakeKeyRelease:
    def __init__(self, key):
        self.key = key


def _key(name):
    """Devolve um FakeKey com o nome dado (modificadores, f-teclas, etc.)."""
    return FakeKey(name)


def _collector(tmp_path, **kw):
    """Cria um EventCollector com um clock sintetico apontando para tmp_path."""
    kw.setdefault("clock", _TestClock())
    kw.setdefault("out_dir", tmp_path)
    return EventCollector(**kw)


def _char(c, ch):
    """Digitacao completa de um char + pequeno avanco de relogio."""
    c.on_key_press(FakeKeyPress(key=ch))
    c.on_key_release(FakeKeyRelease(key=ch))
    c._clock.tick(0.05)


def _click(c, x, y, button="left", dt=0.0):
    if dt:
        c._clock.tick(dt)
    c.on_mouse_click(FakeMouseEvent(x=x, y=y, button=button))


# ── TYPE ──────────────────────────────────────────────────────────────


def test_single_char_emits_type_step(tmp_path):
    c = _collector(tmp_path)
    _char(c, "a")
    steps = c.build(0.0)
    types = [s for s in steps if s.action == Action.TYPE.value]
    assert len(types) == 1
    assert types[0].text == "a"
    assert types[0].redacted is False


def test_sequential_chars_merge_into_one_type(tmp_path):
    c = _collector(tmp_path)
    for ch in "abc":
        _char(c, ch)
    steps = c.build(0.0)
    types = [s for s in steps if s.action == Action.TYPE.value]
    assert len(types) == 1
    assert types[0].text == "abc"


def test_type_respects_char_order(tmp_path):
    c = _collector(tmp_path)
    for ch in "olá":
        _char(c, ch)
    steps = c.build(0.0)
    types = [s for s in steps if s.action == Action.TYPE.value]
    assert len(types) == 1
    assert types[0].text == "olá"


def test_long_gap_splits_type_steps(tmp_path):
    c = _collector(tmp_path)
    _char(c, "a")
    c._clock.tick(0.6)
    _char(c, "b")
    steps = c.build(0.0)
    types = [s for s in steps if s.action == Action.TYPE.value]
    assert len(types) == 2
    assert types[0].text == "a"
    assert types[1].text == "b"


# ── CLICK / DOUBLE ────────────────────────────────────────────────────


def test_click_event(tmp_path):
    c = _collector(tmp_path)
    c.on_mouse_move(FakeMouseEvent(x=100, y=200))
    _click(c, 100, 200, "left")
    steps = c.build(0.0)
    clicks = [s for s in steps if s.action == Action.CLICK.value]
    assert len(clicks) == 1
    assert (clicks[0].x, clicks[0].y) == (100, 200)


def test_double_click_same_point(tmp_path):
    c = _collector(tmp_path)
    _click(c, 100, 200, "left")
    c._clock.tick(0.1)
    _click(c, 100, 200, "left")
    steps = c.build(0.0)
    doubles = [s for s in steps if s.action == Action.DOUBLE_CLICK.value]
    assert len(doubles) == 1
    assert (doubles[0].x, doubles[0].y) == (100, 200)


def test_double_click_different_position(tmp_path):
    c = _collector(tmp_path)
    _click(c, 100, 200, "left")
    c._clock.tick(0.1)
    _click(c, 200, 200, "left")
    steps = c.build(0.0)
    clicks = [s for s in steps if s.action == Action.CLICK.value]
    doubles = [s for s in steps if s.action == Action.DOUBLE_CLICK.value]
    assert len(clicks) == 2
    assert len(doubles) == 0


def test_two_clicks_far_apart_are_two_clicks(tmp_path):
    c = _collector(tmp_path)
    _click(c, 100, 200, "left")
    c._clock.tick(0.5)
    _click(c, 100, 200, "left")
    steps = c.build(0.0)
    clicks = [s for s in steps if s.action == Action.CLICK.value]
    doubles = [s for s in steps if s.action == Action.DOUBLE_CLICK.value]
    assert len(clicks) == 2
    assert len(doubles) == 0


def test_right_click(tmp_path):
    c = _collector(tmp_path)
    _click(c, 50, 60, "right")
    steps = c.build(0.0)
    rights = [s for s in steps if s.action == Action.RIGHT_CLICK.value]
    assert len(rights) == 1
    assert (rights[0].x, rights[0].y) == (50, 60)


# ── SHORTCUTS ─────────────────────────────────────────────────────────


def test_ctrl_s_emits_key_step(tmp_path):
    c = _collector(tmp_path)
    c.on_key_press(FakeKeyPress(key=_key("ctrl")))
    c._clock.tick(0.02)
    c.on_key_press(FakeKeyPress(key="s"))
    c.on_key_release(FakeKeyRelease(key="s"))
    c._clock.tick(0.02)
    c.on_key_release(FakeKeyRelease(key=_key("ctrl")))
    steps = c.build(0.0)
    keys = [s for s in steps if s.action == Action.KEY.value]
    assert len(keys) == 1
    assert keys[0].keys == ["ctrl", "s"]


def test_ctrl_shift_f4_emits_key_step(tmp_path):
    c = _collector(tmp_path)
    c.on_key_press(FakeKeyPress(key=_key("ctrl")))
    c._clock.tick(0.02)
    c.on_key_press(FakeKeyPress(key=_key("shift")))
    c._clock.tick(0.02)
    c.on_key_press(FakeKeyPress(key=_key("f4")))
    c.on_key_release(FakeKeyRelease(key=_key("shift")))
    c._clock.tick(0.02)
    c.on_key_release(FakeKeyRelease(key=_key("ctrl")))
    steps = c.build(0.0)
    keys = [s for s in steps if s.action == Action.KEY.value]
    assert len(keys) == 1
    assert keys[0].keys == ["ctrl", "shift", "f4"]


def test_alt_a_emits_key_step(tmp_path):
    c = _collector(tmp_path)
    c.on_key_press(FakeKeyPress(key=_key("alt")))
    c._clock.tick(0.02)
    c.on_key_press(FakeKeyPress(key="a"))
    c.on_key_release(FakeKeyRelease(key="a"))
    c._clock.tick(0.02)
    c.on_key_release(FakeKeyRelease(key=_key("alt")))
    steps = c.build(0.0)
    keys = [s for s in steps if s.action == Action.KEY.value]
    assert len(keys) == 1
    assert keys[0].keys == ["alt", "a"]


# ── SCROLL ────────────────────────────────────────────────────────────


def test_scroll_event(tmp_path):
    c = _collector(tmp_path)
    c.on_scroll(FakeMouseEvent(x=0, y=0, dx=0, dy=-3))
    steps = c.build(0.0)
    scrolls = [s for s in steps if s.action == Action.SCROLL.value]
    assert len(scrolls) == 1
    assert scrolls[0].dy == -3
    assert scrolls[0].dx == 0


# ── MOVE ──────────────────────────────────────────────────────────────


def test_move_only_event(tmp_path):
    c = _collector(tmp_path)
    c.on_mouse_move(FakeMouseEvent(x=50, y=60))
    steps = c.build(0.0)
    moves = [s for s in steps if s.action == Action.MOVE.value]
    assert len(moves) <= 1  # move em si nao vira passo


def test_move_then_click(tmp_path):
    c = _collector(tmp_path)
    c.on_mouse_move(FakeMouseEvent(x=50, y=60))
    _click(c, 50, 60, "left")
    steps = c.build(0.0)
    clicks = [s for s in steps if s.action == Action.CLICK.value]
    assert len(clicks) == 1
    assert (clicks[0].x, clicks[0].y) == (50, 60)


# ── SECURITY / redaction ──────────────────────────────────────────────


def test_password_field_redacts_text(tmp_path):
    c = _collector(tmp_path, redact=True, field_name="Password")
    for ch in "secret123":
        _char(c, ch)
    steps = c.build(0.0)
    types = [s for s in steps if s.action == Action.TYPE.value]
    assert len(types) == 1
    assert types[0].text == "***"
    assert types[0].redacted is True


def test_password_never_appears_serialized(tmp_path):
    c = _collector(tmp_path, redact=True, field_name="Password")
    for ch in "senha123":
        _char(c, ch)
    steps = c.build(0.0)
    types = [s for s in steps if s.action == Action.TYPE.value]
    assert len(types) == 1
    blob = json.dumps(types[0].to_dict())
    assert "senha123" not in blob
    assert "***" in blob


def test_non_password_not_redacted(tmp_path):
    c = _collector(tmp_path, redact=True, field_name="User")
    for ch in "hello":
        _char(c, ch)
    steps = c.build(0.0)
    types = [s for s in steps if s.action == Action.TYPE.value]
    assert len(types) == 1
    assert types[0].text == "hello"
    assert types[0].redacted is False


# ── HOTKEY F9 ─────────────────────────────────────────────────────────


def test_hotkey_does_not_emit_step(tmp_path):
    c = _collector(tmp_path)
    c.on_key_press(FakeKeyPress(key=_key("f9")))
    c.on_key_release(FakeKeyRelease(key=_key("f9")))
    c._clock.tick(0.02)
    c.on_key_press(FakeKeyPress(key=_key("f9")))
    c.on_key_release(FakeKeyRelease(key=_key("f9")))
    steps = c.build(0.0)
    emitted = [s for s in steps if s.action in (Action.KEY.value, Action.TYPE.value)]
    assert emitted == []


# ── flag de gravacao ──────────────────────────────────────────────────


def test_default_is_recording(tmp_path):
    c = _collector(tmp_path)
    assert c.is_recording is True
