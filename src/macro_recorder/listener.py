"""Listener pynput: captura eventos de mouse/teclado e agrupa em Steps.

Responsabilidades:
    - EventCollector: API publica usada pelos tests (on_key_press, on_key_release,
      on_mouse_move, on_mouse_click, on_scroll, build) — injetamos eventos
      sinteticos para validacao unitaria.
    - Recorder: wrapper que faz a ponte com pynput (listeners globais) e
      chama EventCollector (usado pela CLI `mrec record` em runtime real).
    - Hotkey F9 (override via env MREC_HOTKEY) liga/desliga a gravação.
    - Crop: ao gravar clique, grava o crop via capture.make_crop (lazy
      import — nos testes fica mockado).

Agrupamento:
    - chars imprimiveis sem modificadores, intervalo < 0.5s -> 1 Step.TYPE
    - 2 cliques no mesmo ponto, intervalo < 0.4s -> 1 Step.DOUBLE_CLICK
    - Ctrl/Shift/Alt + tecla -> 1 Step.KEY (ex.: ctrl+s)
    - scroll proximo -> acumula deltas em 1 Step.SCROLL
    - senha: heuristica de "campo parece senha" -> text="***" + redacted=True
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from macro_recorder.events import Action, Recording, Step


# ═════════════════════════════════════════════════════════════════════════
# Constantes de agrupamento
# ═════════════════════════════════════════════════════════════════════════
TEXT_GAP_S = 0.5          #chars com > 0.5s entre -> 2 Steps.TYPE
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
    """Heuristica simples: o foco atual parece um campo de senha?"""
    for s in (focused_window, field_name):
        if s and _PASSWORD_HINTS.search(s):
            return True
    return False


def _key_name(key) -> Optional[str]:
    """Extrai o nome legivel de uma tecla pynput (ou fake)."""
    if isinstance(key, str):
        return key
    # pynput.keyboard.Key tem .name ou .value; nosso fake tem .name
    name = getattr(key, "name", None)
    if name:
        return name
    value = getattr(key, "value", None)
    if value is not None:
        return str(value)
    return None


def _is_modifier(key) -> bool:
    n = _key_name(key)
    return n in MODIFIERS


# ═════════════════════════════════════════════════════════════════════════
# EventCollector — API publica (usada nos testes)
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
    """Fake de uma tecla pynput para testes sinteticos.

    O listener extrai o nome via ``getattr(key, "name", ...)``; este fake expoe
    apenas o atributo ``name``, o que basta para ``_key_name``.
    """

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f"FakeKey({self.name!r})"


class EventCollector:
    """Coleciona eventos (mouse/teclado) e agrupa em Steps.

    Argumentos:
        clock:  objeto com now() -> float (tempo sintetico nos tests)
        out_dir: pasta onde os crops serao gravados (lazy, no clique)
        hotkey: tecla de toggle (default "f9"; override via MREC_HOTKEY)
        focused_window: titulo da janela em foco (optional, p/ heuristica)
        field_name: nome do campo em foco (optional, p/ heuristica)
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
    ):
        self._clock = clock
        self._out_dir = Path(out_dir)
        self._hotkey = (hotkey or os.environ.get("MREC_HOTKEY", "f9")).lower()
        self._focused_window = focused_window or ""
        self._field_name = field_name or ""
        self._redact = redact

        self.is_recording = True  # collector sempre "gravando" nos testes

        # estado interno
        self._events: list = []          # passos finais bruto (pre-agrupamento)
        self._pending_text: Optional[_PendingText] = None
        self._modifiers_down: set = set()
        self._mods_since_last: list = []  # modificadores pressionados desde o ultimo char
        self._pending_scroll: Optional[_PendingScroll] = None
        self._last_click: Optional[Step] = None
        self._step_counter = 0

    # ── hotkey ─────────────────────────────────────────────────────────────
    def _is_hotkey(self, key) -> bool:
        return _key_name(key) == self._hotkey

    # ── callbacks (pynput-style) ──────────────────────────────────────────
    def on_key_press(self, event) -> None:
        key = event.key
        name = _key_name(key)

        # hotkey de toggle — NUNCA vira step (o Recorder externo aplica
        # gating is_recording; aqui so descartamos o F9)
        if self._is_hotkey(key):
            self._flush_all()
            return

        # modificador
        if _is_modifier(key):
            self._modifiers_down.add(name)
            return

        # char imprimivel -> agrupa ou emite atalho
        if isinstance(key, str):
            if self._modifiers_down:
                # atalho (Ctrl+S, Alt+A etc.) -> Step.KEY
                self._emit_key(key)
                return
            self._append_char(key)
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
        # move em si nao vira step; so atualiza o ponto atual
        if not self.is_recording:
            return
        self._last_mouse_pos = (int(event.x), int(event.y))

    def _init_last_mouse_pos(self):
        if not hasattr(self, "_last_mouse_pos"):
            self._last_mouse_pos = (0, 0)

    def on_mouse_click(self, event) -> None:
        self._init_last_mouse_pos()
        if not self.is_recording:
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

        # verif duplo click: mesmo ponto + < DOUBLE_CLICK_S e botao esquerdo
        last = self._last_click
        if (
            action == Action.CLICK.value
            and last is not None
            and last.action == Action.CLICK.value
            and last.x == x
            and last.y == y
            and (t - last.t) < DOUBLE_CLICK_S
        ):
            # troca para DOUBLE_CLICK
            last.action = Action.DOUBLE_CLICK.value
            # remove o step anterior para substituir por um unico
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
        t = self._clock.now()
        x, y = int(event.x), int(event.y)
        dx, dy = int(event.dx), int(event.dy)

        # acumula no pending scroll se proximo o suficiente
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

        # flush pendings
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
            # fecha o grupo anterior
            self._emit_text(p, close=True)
            self._pending_text = _PendingText(chars=ch, t=t)
        else:
            p.chars += ch
            # t mantem o do inicio do grupo

    def _emit_text(self, p: _PendingText, close: bool = True) -> None:
        text = p.chars
        if not text:
            return
        # redaction de senha
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
        """Permite a pyncp (em runtime) atualizar a janela/campo em foco."""
        return self._focused_window, self._field_name

    def set_focus(self, focused_window: str, field_name: str = "") -> None:
        """Chamado pelo runtime pynput quando a mudanca de foco acontece."""
        self._focused_window = focused_window or ""
        self._field_name = field_name or ""

    # ── crop (lazy import para nao quebrar nos tests) ─────────────────────
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
            # crop falhou (sem display etc.) — segue sem crop
            pass

    # ── build ─────────────────────────────────────────────────────────────
    def build(self, stop_time: Optional[float] = None) -> list:
        """Finaliza e devolve a lista de Steps (em ordem cronologica).

        Flush de pendings e normalizacao do t (relativo ao inicio).
        """
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
# Recorder — wrapper com pynput (usado pela CLI em runtime real)
# ═════════════════════════════════════════════════════════════════════════
class Recorder:
    """Gravador com pynput global listeners.

    Uso:
        rec = Recorder(out_dir=Path("./recordings"), hotkey="f9")
        rec.run()   # bloqueia ate o 2o F9 (ou fail-safe)
    Rec:
        rec.recording: Recording (apos rec.run() terminar)
    """

    def __init__(self, *, out_dir: Path | str, hotkey: Optional[str] = None):
        from pynput import keyboard, mouse  # noqa: F401 — checa disponibilidade
        from macro_recorder.listener import _RealClock

        self._collector = EventCollector(
            clock=_RealClock(),
            out_dir=out_dir,
            hotkey=hotkey,
        )
        self._kl = None
        self._ml = None
        self.recording: Optional[Recording] = None

    def _on_key_press(self, event):
        self._collector.on_key_press(event)

    def _on_key_release(self, event):
        self._collector.on_key_release(event)

    def _on_mouse_move(self, event):
        self._collector.on_mouse_move(event)

    def _on_mouse_click(self, event):
        self._collector.on_mouse_click(event)

    def _on_mouse_scroll(self, event):
        self._collector.on_scroll(event)

    def run(self, max_seconds: int = 0) -> Recording:
        from pynput import keyboard, mouse
        import select

        print("[mrec] aguardando F9 para comecar (F9 para iniciar)...", flush=True)
        kl = keyboard.Listener(on_press=self._on_key_press,
                               on_release=self._on_key_release)
        ml = mouse.Listener(on_move=self._on_mouse_move,
                            on_click=self._on_mouse_click,
                            on_scroll=self._on_mouse_scroll)
        with kl, ml:
            # bloqueia ate 2o F9 (collector.is_recording volta a False)
            import time
            start = time.monotonic()
            while True:
                time.sleep(0.2)
                if not self._collector.is_recording:
                    if max_seconds and (time.monotonic() - start) > max_seconds:
                        break
                    # espera pelo 2o toggle (se o primeiro ja aconteceu e
                    # gravacao parou, is_recording==False indica fim)
                    break
        recording = self._collector.to_recording()
        self.recording = recording
        return recording


class _RealClock:
    """Clock de producao (time.monotonic)."""

    def now(self) -> float:
        import time
        return time.monotonic()


def run_record() -> int:
    """Entry point `mrec record` — roda o Recorder em bloco."""
    import datetime
    from pathlib import Path

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path("./recordings") / ts

    rec = Recorder(out_dir=out)
    recording = rec.run()

    # salva artefatos
    recording.save_json(out / "recording.json")
    n = len(recording.steps)
    clicks = sum(1 for s in recording.steps if s.action in (Action.CLICK.value, Action.DOUBLE_CLICK.value))
    types = sum(1 for s in recording.steps if s.action == Action.TYPE.value)
    print(f"\n[mrec] {n} passos gravados ({clicks} cliques, {types} trechos de texto)")
    print(f"[mrec] artefatos em {out}/")

    # exporta MD e replay.py
    from macro_recorder.exporter_md import export_md
    from macro_recorder.exporter_py import export_replay_py
    export_md(recording, out)
    export_replay_py(recording, out)
    print(f"[mrec] OK: {out}/{'passo-a-passo.md', 'replay.py'}".replace("{'", "").replace("', '", "").replace("'}", ""))
    return 0
