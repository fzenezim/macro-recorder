"""Listener pynput: captura eventos de mouse/teclado e agrupa em Steps.

Responsabilidades:
    - EventCollector: API pública usada pelos tests (on_key_press, on_key_release,
      on_mouse_move, on_mouse_click, on_scroll, build) — injetamos eventos
      sintéticos para validação unitária.
    - Recorder: wrapper que faz a ponte com pynput (listeners globais) e
      chama EventCollector (usado pela CLI `mrec record` em runtime real).
    - Hotkey F9 (override via env MREC_HOTKEY) liga/desliga a gravação.
    - Crop: ao gravar clique, grava o crop via capture.make_crop (lazy
      import — nos testes fica mockado).

Agrupamento:
    - chars imprimíveis sem modificadores, intervalo < 0.5s -> 1 Step.TYPE
    - 2 cliques no mesmo ponto, intervalo < 0.4s -> 1 Step.DOUBLE_CLICK
    - Ctrl/Shift/Alt + tecla -> 1 Step.KEY (ex.: ctrl+s)
    - scroll próximo -> acumula deltas em 1 Step.SCROLL
    - senha: heurística de "campo parece senha" -> text="***" + redacted=True
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from macro_recorder.events import Action, Recording, Step


# ═════════════════════════════════════════════════════════════════════════
# Constantes de agrupamento
# ═════════════════════════════════════════════════════════════════════════
TEXT_GAP_S = 0.5          # chars com > 0.5s entre -> 2 Steps.TYPE
DOUBLE_CLICK_S = 0.4      # 2 cliques em < 0.4s -> DOUBLE_CLICK
SCROLL_GAP_S = 0.3        # scrolls com < 0.3s entre -> 1 Step.SCROLL

# modificadores que quebra agrupamento de texto
MODIFIERS = {"ctrl", "shift", "alt", "win", "cmd"}

# heuristica de "campo parecendo senha"
_PASSWORD_HINTS = re.compile(
    r"password|passwd|senha|pwd|secret|login|credencial|"
    r"token|api[-_ ]?key|cv[vc]|cart[ãa]o|cred",
    re.IGNORECASE,
)


def _is_passwordish(focused_window: Optional[str], field_name: Optional[str]) -> bool:
    """Heurística simples: o foco atual parece um campo de senha?"""
    for s in (focused_window, field_name):
        if s and _PASSWORD_HINTS.search(s):
            return True
    return False


def _key_name(key) -> Optional[str]:
    """Extrai o nome legível de uma tecla pynput (ou fake)."""
    if isinstance(key, str):
        return key
    # KeyCode de char tem .char (o próprio char)
    char = getattr(key, "char", None)
    if char is not None and isinstance(char, str):
        return char
    value = getattr(key, "value", None)
    if value is not None and isinstance(value, str):
        return value
    name = getattr(key, "name", None)
    if name:
        return name
    if value is not None:
        return str(value)
    return None


def _is_modifier(key) -> bool:
    n = _key_name(key)
    return n in MODIFIERS


def _char_of(key) -> Optional[str]:
    """Retorna o char imprimível da tecla (KeyCode de char / str) ou None."""
    if isinstance(key, str):
        ch = key
        return ch if len(ch) == 1 else None
    # KeyCode de char tem .char (o próprio char)
    char = getattr(key, "char", None)
    if char is not None and isinstance(char, str) and len(char) == 1:
        return char
    return None


# ═════════════════════════════════════════════════════════════════════════
# EventCollector — API pública (usada nos testes)
# ═════════════════════════════════════════════════════════════════════════
@dataclass
class _PendingText:
    chars: str = ""
    t: float = 0.0


@dataclass
class _PendingScroll:
    dx: int = 0
    dy: int = 0
    x: int = 0
    y: int = 0
    t: float = 0.0


class FakeKey:
    """Fake de uma tecla pynput para testes sintéticos."""

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f"FakeKey({self.name!r})"


class EventCollector:
    """Coleciona eventos (mouse/teclado) e agrupa em Steps.

    Argumentos:
        clock:  objeto com now() -> float (tempo sintético nos tests)
        out_dir: pasta onde os crops serão gravados (lazy, no clique)
        hotkey: tecla de toggle (default "f9"; override via MREC_HOTKEY)
        focused_window: título da janela em foco (optional, p/ heurística)
        field_name: nome do campo em foco (optional, p/ heurística)
    """

    def __init__(
        self,
        *,
        clock,
        out_dir: Path | str = Path("recordings"),
        hotkey: Optional[str] = None,
        focused_window: Optional[str] = None,
        field_name: Optional[str] = None,
        redact: bool = True,
        capture_text: bool = True,
        capture_clicks: bool = True,
        capture_scroll: bool = True,
        capture_focus: bool = True,
        is_recording: bool = False,
        on_state_change=None,
    ):
        self._clock = clock
        self._out_dir = Path(out_dir)
        self._hotkey = (hotkey or os.environ.get("MREC_HOTKEY", "f9")).lower()
        self._focused_window = focused_window or ""
        self._field_name = field_name or ""
        self._redact = redact
        self.capture_text = capture_text
        self.capture_clicks = capture_clicks
        self.capture_scroll = capture_scroll
        self.capture_focus = capture_focus
        self._on_state_change = on_state_change  # callback(recording: bool)

        # Inicia PARADO por padrão (runtime real: o hotkey F9 o liga na 1a
        # tecla). Tests sintéticos passam is_recording=True explicitamente.
        self.is_recording = bool(is_recording)

        # estado interno
        self._events: list = []
        self._pending_text: Optional[_PendingText] = None
        self._modifiers_down: set = set()
        self._modifier_char: Optional[str] = None
        self._mods_since_last: list = []
        self._pending_scroll: Optional[_PendingScroll] = None
        self._last_click: Optional[Step] = None
        self._last_mouse_pos: tuple = (0, 0)
        self._step_counter = 0

    # ── hotkey ─────────────────────────────────────────────────────────────
    def _is_hotkey(self, key) -> bool:
        return _key_name(key) == self._hotkey

    def _notify_state(self) -> None:
        """Callback opcional quando o is_recording muda (F9)."""
        if self._on_state_change is None:
            return
        try:
            self._on_state_change(self.is_recording)
        except Exception:
            pass

    def on_key_press(self, event) -> None:
        key = event.key
        name = _key_name(key)

        # hotkey de toggle — NUNCA vira step
        if self._is_hotkey(key):
            if self.is_recording:
                # está gravando -> para
                self.is_recording = False
                self._flush_all()
            else:
                # está parado -> liga
                self.is_recording = True
            self._notify_state()
            return

        if not self.is_recording:
            return

        # modificador
        if _is_modifier(key):
            self._modifiers_down.add(name)
            return

        # char imprimível -> agrupa ou emite atalho
        ch = _char_of(key)
        if ch is not None:
            if self._modifiers_down:
                self._emit_key(ch)
                return
            if not self.capture_text:
                return
            self._append_char(ch)
            return

        # tecla especial (enter, tab, f5, ...)
        if name and name not in MODIFIERS:
            self._emit_key(name)
            return

    def on_key_release(self, event) -> None:
        key = event.key
        name = _key_name(key)

        if self._is_hotkey(key):
            return

        if _is_modifier(key):
            self._modifiers_down.discard(name)
            if not self._modifiers_down:
                self._modifier_char = None
                self._mods_since_last = []
            return

    def on_mouse_move(self, event) -> None:
        # move em si não vira step; só atualiza o ponto atual
        if not self.is_recording:
            return
        self._last_mouse_pos = (int(event.x), int(event.y))

    def on_mouse_click(self, event) -> None:
        if not self.is_recording:
            return
        if not self.capture_clicks:
            return

        x, y = int(event.x), int(event.y)
        t = self._clock.now()
        action = (
            Action.CLICK.value
            if event.button == "left"
            else Action.RIGHT_CLICK.value
            if event.button == "right"
            else Action.CLICK.value
        )

        # verif duplo click: mesmo ponto + < DOUBLE_CLICK_S e botão esquerdo
        last = self._last_click
        if (
            action == Action.CLICK.value
            and last is not None
            and last.action == Action.CLICK.value
            and last.x == x
            and last.y == y
            and (t - last.t) < DOUBLE_CLICK_S
        ):
            last.action = Action.DOUBLE_CLICK.value
            self._events.pop()
            self._events.append(last)
            self._last_click = last
            self._step_counter += 1
            self._maybe_capture(last)
            return

        # flush pendings antes de um clique
        self._flush_all()

        step = Step(
            action=action,
            t=t,
            x=x,
            y=y,
        )
        self._events.append(step)
        self._last_click = step
        self._step_counter += 1
        self._maybe_capture(step)

    def on_scroll(self, event) -> None:
        if not self.is_recording:
            return
        if not self.capture_scroll:
            return
        t = self._clock.now()
        x, y = int(event.x), int(event.y)
        dx, dy = int(event.dx), int(event.dy)

        p = self._pending_scroll
        if (
            p is not None
            and p.x == x
            and p.y == y
            and (t - p.t) < SCROLL_GAP_S
        ):
            p.dx += dx
            p.dy += dy
            p.t = t
            return

        self._flush_all()
        self._pending_scroll = _PendingScroll(dx=dx, dy=dy, x=x, y=y, t=t)

    # ── internos ───────────────────────────────────────────────────────────
    def _append_char(self, ch: str) -> None:
        t = self._clock.now()
        p = self._pending_text
        if p is None:
            self._pending_text = _PendingText(chars=ch, t=t)
            return
        gap = t - p.t
        if gap > TEXT_GAP_S:
            self._emit_text(p, close=True)
            self._pending_text = _PendingText(chars=ch, t=t)
        else:
            p.chars += ch

    def _emit_text(self, p: _PendingText, close: bool = True) -> None:
        text = p.chars
        if not text:
            return
        if self._redact and _is_passwordish(self._focused_window, self._field_name):
            text = "***"
            redacted = True
        else:
            redacted = False
        self._events.append(
            Step(action=Action.TYPE.value, t=p.t, text=text, redacted=redacted)
        )
        if close:
            self._pending_text = None

    def _emit_key(self, name: str) -> None:
        t = self._clock.now()
        order = {"ctrl": 0, "shift": 1, "alt": 2}
        mods = sorted(self._modifiers_down, key=lambda k: order.get(k, 99))
        keys = mods + [name]
        self._events.append(Step(action=Action.KEY.value, t=t, keys=keys))

    def _flush_pending_text(self) -> None:
        if self._pending_text is not None:
            self._emit_text(self._pending_text, close=True)

    def _flush_pending_scroll(self) -> None:
        p = self._pending_scroll
        if p is None:
            return
        self._events.append(
            Step(
                action=Action.SCROLL.value,
                t=p.t,
                x=p.x,
                y=p.y,
                dx=p.dx,
                dy=p.dy,
            )
        )
        self._pending_scroll = None

    def _flush_all(self) -> None:
        self._flush_pending_text()
        self._flush_pending_scroll()

    @property
    def current_focus(self) -> tuple[str, str]:
        return self._focused_window, self._field_name

    def set_focus(self, focused_window: str, field_name: str = "") -> None:
        self._focused_window = focused_window or ""
        self._field_name = field_name or ""

    # ── crop (lazy import para não quebrar nos tests) ──────────────────────
    def _maybe_capture(self, step: Step) -> None:
        """Se o step tem x/y, grava o crop em assets/aNN.png."""
        if step.x is None or step.y is None:
            return
        try:
            from macro_recorder.capture import make_crop
        except Exception:
            return
        try:
            nn = f"{self._step_counter:02d}"
            assets = self._out_dir / "assets"
            out = assets / f"a{nn}.png"
            make_crop(step.x, step.y, out_path=out)
            step.crop = f"assets/a{nn}.png"
        except Exception:
            pass

    # ── build ─────────────────────────────────────────────────────────────
    def build(self, stop_time: Optional[float] = None) -> list:
        self._flush_all()
        if self._events:
            t0 = self._events[0].t
            for s in self._events:
                s.t = max(0.0, s.t - t0)
        return list(self._events)

    def to_recording(self, stop_time: Optional[float] = None) -> Recording:
        import datetime
        steps = self.build(stop_time)
        duration = max((s.t for s in steps), default=0.0)
        return Recording(
            created_at=datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            duration_s=duration,
            steps=steps,
            meta={"hotkey": self._hotkey},
        )


# ═════════════════════════════════════════════════════════════════════════
# _RealClock — clock de produção (time.monotonic)
# ═════════════════════════════════════════════════════════════════════════
class _RealClock:
    def now(self) -> float:
        import time
        return time.monotonic()


# ═════════════════════════════════════════════════════════════════════════
# _KeyEvent — adaptador: pynput passa a tecla "solta"; o EventCollector espera
# um objeto com .key (contrato dos tests sintéticos).
# ═════════════════════════════════════════════════════════════════════════
class _KeyEvent:
    """Wrapper mínimo: expõe .key como o contrato do EventCollector."""
    __slots__ = ("key",)
    def __init__(self, key):
        self.key = key


class _MouseEvent:
    """Adapter da assinatura pynput (x, y, button, pressed[, dx, dy]) para o
    shape .x / .y / .button / .dx / .dy que o EventCollector consome."""
    __slots__ = ("x", "y", "button", "dx", "dy")
    def __init__(self, x, y, button=None, dx=0, dy=0):
        self.x = x
        self.y = y
        self.button = button
        self.dx = dx
        self.dy = dy


# ═════════════════════════════════════════════════════════════════════════
# Recorder — wrapper com pynput (usado pela CLI em runtime real)
# ═════════════════════════════════════════════════════════════════════════
class Recorder:
    """Gravador com pynput global listeners.

    Uso:
        rec = Recorder(out_dir=Path("./recordings"), hotkey="f9")
        rec.run()   # bloqueia até o 2º F9 (ou Ctrl+C para cancelar)
    Rec:
        rec.recording: Recording (após rec.run() terminar)

    Fluxo:
        1. run() -> "aguardando F9 ..."
        2. usuário aperta F9 -> "GRAVANDO..." (evento não é gravado)
        3. usuário clica/digita -> eventos são gravados
        4. usuário aperta F9 de novo -> "PARADO" -> gravação termina
    """

    def __init__(
        self,
        *,
        out_dir: Path | str,
        hotkey: Optional[str] = None,
        capture_text: bool = True,
        capture_clicks: bool = True,
        capture_scroll: bool = True,
        capture_focus: bool = True,
        on_state_change=None,
    ):
        from pynput import keyboard, mouse  # noqa: F401 — checa disponibilidade

        self._capture_focus = capture_focus
        self._on_state_change = on_state_change  # callback(is_recording: bool)

        self._collector = EventCollector(
            clock=_RealClock(),
            out_dir=out_dir,
            hotkey=hotkey,
            capture_text=capture_text,
            capture_clicks=capture_clicks,
            capture_scroll=capture_scroll,
            capture_focus=capture_focus,
            on_state_change=self._on_state_change,
        )
        # começa parado (aguardando 1º F9 para ligar)
        self._collector.is_recording = False
        self.recording: Optional[Recording] = None
        self._was_started = False  # True após o 1º F9 ser pressionado
        # toggle programático: GUI/teste chama rec.toggle() para virar o estado
        # do hotkey sem depender de eventos de teclado reais (pynput injetados
        # não são vistos pelo hook global do mesmo processo no Windows).
        self._toggle_event: threading.Event = threading.Event()
        self._running = False

    def toggle(self) -> bool:
        """Aciona o toggle do hotkey (mesmo efeito de apertar F9).

        Thread-safe: qualquer thread pode chamar. O loop do run() consome o
        evento e dispara o mesmo tratamento do EventCollector.on_key_press
        para a tecla do hotkey.
        """
        self._toggle_event.set()
        return self._collector.is_recording

    # ── callbacks pynput (chamados em threads separadas) ─────────────────
    def _notify(self):
        if self._on_state_change:
            try:
                self._on_state_change(self._collector.is_recording)
            except Exception:
                pass

    def _on_key_press(self, key, *a):
        """pynput: on_press(key[, injected]) — o EventCollector espera .key."""
        self._update_focus_if_needed()
        ev = _KeyEvent(key)
        if self._collector._is_hotkey(key):
            hk = self._collector._hotkey.upper()
            self._collector.on_key_press(ev)
            if self._collector.is_recording:
                self._was_started = True
                print("\n[mrec] >>> GRAVANDO...  (2ª {} para PARAR | Ctrl+C cancela)".format(hk), flush=True)
            else:
                print("\n[mrec] <<< PARADO.  Salvando artefatos...", flush=True)
            return
        # Não é hotkey -> delega ao collector
        self._collector.on_key_press(ev)
        return

    def _on_key_release(self, key, *a):
        self._collector.on_key_release(_KeyEvent(key))
        return

    def _on_mouse_move(self, x, y):
        self._collector.on_mouse_move(_MouseEvent(x, y))
        return

    def _on_mouse_click(self, x, y, button, pressed):
        if not pressed:
            return
        # normalize o botão pynput (Button.left/right/middle -> "left"...)
        try:
            from pynput.mouse import Button
            for name in ("left", "middle", "right"):
                if button == getattr(Button, name, None):
                    button = name
                    break
        except Exception:
            pass
        self._collector.on_mouse_click(_MouseEvent(x, y, button))
        return

    def _on_mouse_scroll(self, x, y, dx, dy):
        self._collector.on_scroll(_MouseEvent(x, y, dx=dx, dy=dy))
        return

    # ── janela em foco (heurística p/ detectar campo de senha) ─────────
    def _focused_window_title(self) -> str:
        """Título da janela em foco (pygetwindow; '' se não suportado)."""
        try:
            import pygetwindow as gw
            ws = gw.getActiveWindow()
            return ws.title or "" if ws else ""
        except Exception:
            return ""

    def _update_focus_if_needed(self, event=None) -> None:
        """No início da gravação (e a cada clique), atualiza o foco.

        O collector só usa o foco para a heurística de senha — o título real
        da janela é gravado nos artefatos via meta (não em cada step)."""
        if not self._capture_focus:
            return
        if not self._collector.is_recording:
            return
        title = self._focused_window_title()
        if title:
            if title != self._collector._focused_window:
                self._collector.set_focus(title)

    def _hotkey_pressed(self) -> bool:
        """True se a tecla do hotkey está fisicamente pressionada (Windows / GetAsyncKeyState).

        O listener global do pynput NÃO recebe eventos que vieram via SendInput
        marcados com KBDLLHOOK_INJECTED (o 1º F9 chega, mas o 2º — disparado
        pelo GUI/Controller — não). GetAsyncKeyState lê o estado físico e é
        robusto a isso. Usamos o scan code do hotkey para não depender de layout.
        """
        if not sys.platform.startswith("win"):
            return False
        try:
            from pynput.keyboard import KeyCode, Key as _PnKey, _keys
        except Exception:
            return False

        # mapeia o hotkey (ex.: "f9") para scan code VK
        hk = (self._collector._hotkey or "f9").lower()
        VK = getattr(_PnKey, hk.upper(), None)
        if VK is None:
            sc = _keys.keys_to_codes.get(hk[0], None)
            if not sc:
                return False
            vkc = sc[0]
        else:
            vkc = VK.value
        # value do KeyCode de Key.f9 é o enum do VK — convertemos pro VK
        if hasattr(vkc, "value"):
            vkc = vkc.value
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(vkc) & 0x8000)
        except Exception:
            return False

    def _programmatic_toggle(self) -> None:
        """Aplica o toggle do hotkey sem depender de um evento de teclado real.

        Dispara o MESMO tratamento que o _on_key_press faria para a tecla do
        hotkey: alterna is_recording via EventCollector.on_key_press e atualiza
        o _was_started (que controla a saida do loop do run).
        """
        hk = (self._collector._hotkey or "f9")
        before = self._collector.is_recording
        self._collector.on_key_press(
            _KeyEvent(type("_ProgKey", (), {
                "name": hk, "char": None, "value": None,
            })())
        )
        if not before and self._collector.is_recording:
            self._was_started = True
            print(f"\n[mrec] >>> GRAVANDO...  (2ª F9 para PARAR | Ctrl+C cancela)", flush=True)
        elif before and not self._collector.is_recording:
            print(f"\n[mrec] <<< PARADO.  Salvando artefatos...", flush=True)

    def handle_screenshot(self, monitor_index: int = 0):
        """Captura o monitor inteiro em tela cheia (com hora/data do Windows no relógio).

        Salva em assets/ e adiciona evento SCREENSHOT na gravação.
        Retorna o caminho do arquivo.
        """
        import datetime
        asset_dir = self.out / "assets"
        asset_dir.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = asset_dir / f"screen_{ts}_m{monitor_index}.png"

        from .capture import capture_monitor
        capture_monitor(monitor_index, out_path=out_path)

        self.record(
            EventType.SCREENSHOT,
            screenshot=f"assets/screen_{ts}_m{monitor_index}.png",
            monitor=monitor_index,
            timestamp=datetime.datetime.now().isoformat(),
        )
        return out_path

    def run(self, max_seconds: int = 0) -> Recording:
        from pynput import keyboard, mouse
        import time as _t

        # pyautogui fail-safe (canto superior esquerdo cancela)
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.0
        except Exception:
            pass

        hk = (self._collector._hotkey or "f9").upper()
        print(f"[mrec] pressionando {hk} LIGA a gravação; 2ª {hk} PARA.  Ctrl+C cancela.", flush=True)
        self._running = True

        with keyboard.Listener(on_press=self._on_key_press,
                               on_release=self._on_key_release) as kl, \
             mouse.Listener(on_move=self._on_mouse_move,
                            on_click=self._on_mouse_click,
                            on_scroll=self._on_mouse_scroll) as ml:
            # loop de controle: sai quando o usuário ligou E parou
            while True:
                _t.sleep(0.1)
                # toggle programático (GUI/chama rec.toggle())
                if self._toggle_event.is_set():
                    self._toggle_event.clear()
                    self._programmatic_toggle()
                if self._was_started and not self._collector.is_recording:
                    break
                # timeout opcional
                if max_seconds > 0:
                    # (implementação simplificada: não cobrimos por hora)
                    pass
        self._running = False

        recording = self._collector.to_recording()
        self.recording = recording
        return recording


# ═════════════════════════════════════════════════════════════════════════
# run_record() — entry point `mrec record`
# ═════════════════════════════════════════════════════════════════════════
def run_record() -> int:
    """Grava uma macro e salva os artefatos. Retorna 0 sucesso, 1 abortado."""
    import os, json
    from datetime import datetime

    hotkey = os.environ.get("MREC_HOTKEY", "f9").lower()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("recordings") / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assets").mkdir(exist_ok=True)

    print(f"\n[mrec] ═══════════════════════════════════════════════", flush=True)
    print(f"[mrec]   HOTKEY: {hotkey.upper()}   |   PASTA: {out_dir}", flush=True)
    print(f"[mrec]   Pressione {hotkey.upper()} quando estiver PRONTO para gravar.", flush=True)
    print(f"[mrec]   Pressione {hotkey.upper()} de novo quando terminar.", flush=True)
    print(f"[mrec]   (Mova o mouse para o canto superior-esquerdo p/ cancelar.)", flush=True)
    print(f"[mrec] ═══════════════════════════════════════════════\n", flush=True)

    try:
        rec = Recorder(out_dir=out_dir, hotkey=hotkey)
        recording = rec.run()
    except KeyboardInterrupt:
        print("\n\n[mrec] Cancelado pelo usuário (Ctrl+C). Pasta removida.", flush=True)
        # limpa a pasta vazia
        import shutil
        shutil.rmtree(out_dir, ignore_errors=True)
        return 1
    except Exception as e:
        print(f"\n[mrec] ERRO: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return 1

    steps = recording.steps
    rec_path = out_dir / "recording.json"
    rec_path.write_text(json.dumps(recording.to_dict(), indent=2), encoding="utf-8")

    # exporta MD e PY
    import macro_recorder.exporter_md as md
    import macro_recorder.exporter_py as pyexp
    md.export_md(recording, steps, out_dir / "passo-a-passo.md")
    pyexp.export_py(steps, out_dir / "replay.py")

    crops = sum(1 for s in steps if s.crop)
    print(f"\n[mrec] ✅ {len(steps)} passos salvos em {out_dir}/", flush=True)
    print(f"[mrec]   recording.json", flush=True)
    print(f"[mrec]   passo-a-passo.md", flush=True)
    print(f"[mrec]   replay.py", flush=True)
    print(f"[mrec]   assets/ ({crops} crops)", flush=True)
    print(f"[mrec] ▶  Para testar: mrec replay {out_dir} --dry-run", flush=True)
    return 0
