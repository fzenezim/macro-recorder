# -*- coding: utf-8 -*-
"""Gera replay.py standalone a partir de list de Steps."""
from datetime import datetime as _dt
from pathlib import Path
from typing import List
from macro_recorder.events import Step, Action

def _tpl_header(n_steps, duration_s, generated_at):
    lines = [
        '# -*- coding: utf-8 -*-',
        f'# Gerado por mrec em {generated_at}',
        f'# Replay de {n_steps} passos (duracao {duration_s:.2f}s)',
        '',
        'import sys',
        'import time',
        'from pathlib import Path',
        '',
        'import pyautogui',
        '',
        'BASE = Path(__file__).resolve().parent',
        'pyautogui.FAILSAFE = True',
        'DRY_RUN = "--dry-run" in sys.argv',
        '',
    ]
    return "\n".join(lines) + "\n"

def _tpl_helpers():
    return '''
def _locate(crop, confs=(0.9, 0.8, 0.7)):
    """Localiza a crop na tela com confidence em cascata."""
    if DRY_RUN:
        return (None, None)
    p = BASE / "assets" / crop
    if not p.exists():
        return None
    for c in confs:
        try:
            box = pyautogui.locateOnScreen(str(p), confidence=c)
        except AssertionError:
            box = pyautogui.locateOnScreen(str(p))
            break
        if box is not None:
            return pyautogui.center(box)
    return None

def _click(crop=None, x=None, y=None):
    if x is None and crop is not None:
        pt = _locate(crop)
        if pt:
            x, y = pt
    if x is None and not DRY_RUN:
        print("  [!] nao-localizei")
        return
    if x is None:
        x, y = 0, 0
    if DRY_RUN:
        print(f"  [dry] click ({x}, {y})")
        return
    print(f"  click ({x}, {y})")
    pyautogui.click(x, y)

def _double_click(crop=None, x=None, y=None):
    if x is None and crop is not None:
        pt = _locate(crop)
        if pt:
            x, y = pt
    if x is None and not DRY_RUN:
        print("  [!] nao-localizei")
        return
    if x is None:
        x, y = 0, 0
    if DRY_RUN:
        print(f"  [dry] double-click ({x}, {y})")
        return
    print(f"  double-click ({x}, {y})")
    pyautogui.doubleClick(x, y)

def _right_click(crop=None, x=None, y=None):
    if x is None and crop is not None:
        pt = _locate(crop)
        if pt:
            x, y = pt
    if x is None and not DRY_RUN:
        print("  [!] nao-localizei")
        return
    if x is None:
        x, y = 0, 0
    if DRY_RUN:
        print(f"  [dry] right-click ({x}, {y})")
        return
    print(f"  right-click ({x}, {y})")
    pyautogui.rightClick(x, y)

def _key(keys):
    combo = "+".join(keys)
    if DRY_RUN:
        print(f"  [dry] key {combo}")
        return
    print(f"  key {combo}")
    pyautogui.hotkey(*keys)

def _type(text, interval=0.03):
    if DRY_RUN:
        print(f"  [dry] type {text!r}")
        return
    print(f"  type {text!r}")
    pyautogui.typewrite(text, interval=interval)

def _scroll(dx, dy, x=None, y=None):
    clicks = int(dy / 120)
    if DRY_RUN:
        print(f"  [dry] scroll dy={dy} (clicks={clicks}) at ({x or '?'}, {y or '?'})")
        return
    if x is not None:
        pyautogui.moveTo(x, y)
    print(f"  scroll dy={dy} (clicks={clicks})")
    pyautogui.scroll(clicks)

def _move(x, y):
    if DRY_RUN:
        print(f"  [dry] move ({x}, {y})")
        return
    print(f"  move ({x}, {y})")
    pyautogui.moveTo(x, y, duration=0.05)

def _wait(s):
    if DRY_RUN:
        print(f"  [dry] wait {s:.2f}")
        return
    if s > 0.01:
        print(f"  wait {s:.2f}")
        time.sleep(s)
'''
def _step_line(s: Step, dry_run: bool = False) -> str:
    """Um passo -> 1 linha (ou blocos) no replay."""
    a = s.action
    t = s.t
    prefix = ""
    if dry_run:
        prefix = "print('[dry] "
    if a == Action.CLICK.value:
        if s.crop:
            return f"    _click(crop={s.crop!r}, x={s.x}, y={s.y})"
        return f"    _click(x={s.x}, y={s.y})"
    if a == Action.DOUBLE_CLICK.value:
        if s.crop:
            return f"    _double_click(crop={s.crop!r}, x={s.x}, y={s.y})"
        return f"    _double_click(x={s.x}, y={s.y})"
    if a == Action.RIGHT_CLICK.value:
        if s.crop:
            return f"    _right_click(crop={s.crop!r}, x={s.x}, y={s.y})"
        return f"    _right_click(x={s.x}, y={s.y})"
    if a == Action.KEY.value:
        return f"    _key({s.keys!r})"
    if a == Action.TYPE.value:
        txt = "***" if s.redacted else (s.text or "")
        return f"    _type({txt!r}, interval=0.03)"
    if a == Action.SCROLL.value:
        return f"    _scroll(dx={s.dx}, dy={s.dy}, x={s.x}, y={s.y})"
    if a == Action.MOVE.value:
        return f"    _move(x={s.x}, y={s.y})"
    return "    pass"


def to_python(steps: List[Step], dry_run: bool = False) -> str:
    """Gera o replay.py completo."""
    header = _tpl_header(len(steps), sum(s.t for s in steps) if steps else 0.0,
                          _dt.now().isoformat())
    helpers = _tpl_helpers()
    lines = [
        "def run():",
        "    print('replay...')",
        "    pyautogui.FAILSAFE = True",
        "    # mouse top-left aborta (Failsafe)",
    ]
    last_t = 0.0
    for s in steps:
        delta = s.t - last_t
        if delta > 0.005:
            lines.append(f"    _wait({delta:.3f})")
        lines.append(_step_line(s, dry_run))
        last_t = s.t
    lines.append("    print('done.')")
    lines.append("")
    lines.append("")
    lines.append("if __name__ == '__main__':")
    lines.append("    run()")
    return header + helpers + "\n".join(lines) + "\n"


def export_py(steps: List[Step], out_path: Path | str, dry_run: bool = False) -> Path:
    """Escreve replay.py em `out_path`."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_python(steps, dry_run=dry_run), encoding="utf-8")
    return out
