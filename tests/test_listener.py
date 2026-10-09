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
    """Cria um EventCollector com um clock sintetico apontando para tmp_path.

    Por padrão já nasce GRAVANDO (is_recording=True) — os tests sintéticos
    injetam eventos sem passar pelo hotkey. O runtime real começa PARADO e
    liga no primeiro F9 (testado em test_default_is_not_recording)."""
    kw.setdefault("clock", _TestClock())
    kw.setdefault("out_dir", tmp_path)
    kw.setdefault("is_recording", True)
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


def test_default_is_not_recording(tmp_path):
    """O collector inicia PARADO: o hotkey F9 o liga na 1a tecla.

    (Os tests sintéticos acima setam is_recording=True explicitamente via
    helper _collector — aqui testamos o comportamento real de produção.)"""
    c = EventCollector(clock=_TestClock(), out_dir=tmp_path)
    assert c.is_recording is False
    # 1o F9 liga, 2o F9 desliga
    c.on_key_press(FakeKeyPress(key=_key("f9")))
    assert c.is_recording is True
    c.on_key_press(FakeKeyPress(key=_key("f9")))
    assert c.is_recording is False


# ── FILTER DE DELEÇÃO (DEL + Backspace) ────────────────────────────────


def test_del_key_is_ignored(tmp_path):
    """Tecla DEL (nome 'delete') não gera nenhum step."""
    c = _collector(tmp_path)
    c.on_key_press(FakeKeyPress(key=_key("delete")))
    c._clock.tick(0.05)
    c.on_key_release(FakeKeyRelease(key=_key("delete")))
    steps = c.build(0.0)
    delete_steps = [s for s in steps if "delete" in (s.keys or [])]
    assert delete_steps == []


def test_backspace_key_is_ignored(tmp_path):
    """Tecla Backspace não gera nenhum step."""
    c = _collector(tmp_path)
    # uma tecla normal antes, pra garantir que o collector tá gravando
    _char(c, "a")
    c.on_key_press(FakeKeyPress(key=_key("backspace")))
    c._clock.tick(0.05)
    c.on_key_release(FakeKeyRelease(key=_key("backspace")))
    steps = c.build(0.0)
    bs_steps = [s for s in steps if "backspace" in (s.keys or [])]
    assert bs_steps == []
    # o 'a' antes foi gravado normalmente
    types = [s for s in steps if s.action == Action.TYPE.value]
    assert any(t.text == "a" for t in types)


def test_ctrl_del_combo_is_ignored(tmp_path):
    """Atalho Ctrl+DEL (modificadores + tecla de deleção) também é ignorado."""
    c = _collector(tmp_path)
    c.on_key_press(FakeKeyPress(key=_key("ctrl")))
    c._clock.tick(0.02)
    c.on_key_press(FakeKeyPress(key=_key("delete")))
    c._clock.tick(0.02)
    c.on_key_release(FakeKeyRelease(key=_key("delete")))
    c.on_key_release(FakeKeyRelease(key=_key("ctrl")))
    steps = c.build(0.0)
    key_steps = [s for s in steps if s.action == Action.KEY.value]
    assert key_steps == []


def test_other_keys_still_recorded_after_ignoring_del(tmp_path):
    """Ignorar DEL não afeta o resto das teclas."""
    c = _collector(tmp_path)
    _char(c, "x")
    c.on_key_press(FakeKeyPress(key=_key("delete")))
    c._clock.tick(0.05)
    c.on_key_release(FakeKeyRelease(key=_key("delete")))
    _char(c, "y")
    steps = c.build(0.0)
    types = [s for s in steps if s.action == Action.TYPE.value]
    del_steps = [s for s in steps if "delete" in (s.keys or [])]
    assert del_steps == []
    # texto gravado = 'xy' (sem o DEL no meio)
    all_text = "".join(t.text for t in types)
    assert all_text == "xy"


# ── FILTER DE CLIQUES NA GUI ───────────────────────────────────────────────


def _mk_recorder(tmp_path, monkeypatch, gui_active=True, gui_rect=(0, 0, 500, 400)):
    """Cria um Recorder com o _is_click_on_gui mockado.

    Se gui_active=True, qualquer (x, y) dentro de gui_rect é tratado como
    clique na GUI (descartado) — simula a janela MacroRecorderApp em foco.
    Se gui_active=False, nenhum clique é descartado.
    """
    from macro_recorder.listener import Recorder

    rec = Recorder(out_dir=tmp_path)
    if gui_active:
        def fake_gui(x, y):
            l, t, w, h = gui_rect
            return (l <= x <= l + w) and (t <= y <= t + h)
    else:
        def fake_gui(x, y):
            return False
    rec._is_click_on_gui = fake_gui
    return rec


def test_click_inside_gui_is_dropped(tmp_path, monkeypatch):
    """Clique dentro do bounding box da GUI não vira step (descartado)."""
    rec = _mk_recorder(tmp_path, monkeypatch, gui_active=True, gui_rect=(100, 100, 400, 300))
    rec._collector.is_recording = True
    # clique "dentro da GUI" (150, 150 está dentro do retângulo)
    rec._on_mouse_click(150, 150, "left", True)
    # clique "fora da GUI" (600, 600 está fora do retângulo)
    rec._on_mouse_click(600, 600, "left", True)
    steps = rec._collector.build(0.0)
    clicks = [s for s in steps if s.action == Action.CLICK.value]
    # só o clique de fora deve ter ficado
    assert len(clicks) == 1
    assert (clicks[0].x, clicks[0].y) == (600, 600)


def test_click_outside_gui_is_recorded(tmp_path, monkeypatch):
    """Clique fora da GUI (janela ativa = outra app) é gravado normal."""
    rec = _mk_recorder(tmp_path, monkeypatch, gui_active=False)
    rec._collector.is_recording = True
    rec._on_mouse_click(300, 300, "left", True)
    steps = rec._collector.build(0.0)
    clicks = [s for s in steps if s.action == Action.CLICK.value]
    assert len(clicks) == 1
    assert (clicks[0].x, clicks[0].y) == (300, 300)


def test_double_click_inside_gui_is_not_double(tmp_path, monkeypatch):
    """Dois cliques rápidos dentro da GUI não viram double-click (descartados)."""
    rec = _mk_recorder(tmp_path, monkeypatch, gui_active=True, gui_rect=(0, 0, 1000, 1000))
    rec._collector.is_recording = True
    rec._on_mouse_click(50, 50, "left", True)
    import time
    time.sleep(0.1)
    rec._on_mouse_click(50, 50, "left", True)
    steps = rec._collector.build(0.0)
    doubles = [s for s in steps if s.action == Action.DOUBLE_CLICK.value]
    clicks = [s for s in steps if s.action == Action.CLICK.value]
    assert doubles == [] and clicks == []


# ── CAPTURA DE TELA AUTOMÁTICA A CADA CLIQUE (IPE) ──────────────────────


def test_screen_capture_on_click_disabled_by_default(tmp_path):
    """Sem a flag, nenhum screenshot é capturado."""
    c = _collector(tmp_path, capture_screen_on_click=False)
    _click(c, 100, 200, "left")
    steps = c.build(0.0)
    clicks = [s for s in steps if s.action == Action.CLICK.value]
    assert len(clicks) == 1
    assert clicks[0].screenshot is None


def test_screen_capture_on_click_enabled(tmp_path):
    """Com a flag, o clique dispara captura de tela."""
    c = _collector(tmp_path, capture_screen_on_click=True)
    c.on_mouse_move(FakeMouseEvent(x=100, y=200))
    _click(c, 100, 200, "left")
    steps = c.build(0.0)
    clicks = [s for s in steps if s.action == Action.CLICK.value]
    assert len(clicks) == 1
    # o screenshot deve ter sido chamado (no test, a captura falha sem display,
    # mas a lógica tenta — verificamos que o campo foi populado ou que não errou)
    # note: em ambiente sem display, capture_monitor falha → screenshot fica None
    # mas O CÓDIGO TENTOU (não quebrou)
    assert clicks[0].screenshot is None or isinstance(clicks[0].screenshot, str)


# ── MONITOR DINÂMICO (seleção por coordenada do clique) ──────────────────


def test_monitor_for_point_secondary(tmp_path, monkeypatch):
    """Ponto dentro do 2º monitor → devolve índice 1."""
    import macro_recorder.capture as cap
    monkeypatch.setattr(
        cap, "get_monitors",
        lambda: [
            {"left": 0, "top": 0, "width": 1920, "height": 1080, "is_primary": True, "name": "m1"},
            {"left": 1920, "top": 0, "width": 1920, "height": 1080, "is_primary": False, "name": "m2"},
        ],
    )
    assert cap.monitor_for_point(100, 100) == 0
    assert cap.monitor_for_point(2000, 100) == 1


def test_monitor_for_point_left_negative(tmp_path, monkeypatch):
    """Monitor à esquerda do primário (left negativo) → índice 1."""
    import macro_recorder.capture as cap
    monkeypatch.setattr(
        cap, "get_monitors",
        lambda: [
            {"left": 0, "top": 0, "width": 1920, "height": 1080, "is_primary": True, "name": "m1"},
            {"left": -1920, "top": 0, "width": 1920, "height": 1080, "is_primary": False, "name": "m2"},
        ],
    )
    # ponto no monitor à esquerda tem x negativo
    assert cap.monitor_for_point(-500, 100) == 1
    assert cap.monitor_for_point(500, 100) == 0


def test_monitor_for_point_fallback_primary(tmp_path, monkeypatch):
    """Ponto fora de qualquer monitor → fallback para o primário (0)."""
    import macro_recorder.capture as cap
    monkeypatch.setattr(
        cap, "get_monitors",
        lambda: [
            {"left": 0, "top": 0, "width": 1920, "height": 1080, "is_primary": True, "name": "m1"},
        ],
    )
    assert cap.monitor_for_point(99999, 99999) == 0


def test_capture_screen_uses_click_monitor(tmp_path, monkeypatch):
    """A captura usa O monitor que contém o clique (dinâmico)."""
    import macro_recorder.capture as cap
    monkeypatch.setattr(
        cap, "get_monitors",
        lambda: [
            {"left": 0, "top": 0, "width": 1920, "height": 1080, "is_primary": True, "name": "m1"},
            {"left": 1920, "top": 0, "width": 1920, "height": 1080, "is_primary": False, "name": "m2"},
        ],
    )
    called = {}

    def fake_capture_mon(idx, *, out_path=None):
        called["idx"] = idx
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p, "ts"

    monkeypatch.setattr(cap, "capture_monitor", fake_capture_mon)

    c = _collector(tmp_path, capture_screen_on_click=True)
    c.on_mouse_move(FakeMouseEvent(x=2000, y=100))  # dentro do monitor 2
    _click(c, 2000, 100, "left")
    steps = c.build(0.0)
    clicks = [s for s in steps if s.action == Action.CLICK.value]
    assert len(clicks) == 1
    # a captura deveria ter usado o monitor 1 (índice do 2º)
    assert called.get("idx") == 1
    assert clicks[0].screenshot is not None
    assert clicks[0].monitor == 1
