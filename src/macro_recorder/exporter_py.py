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

def _type(text, interval=0.03, data_row=None):
    # cola via clipboard (acentos OK + dados nao ficam no .py/arg do subprocess)
    if data_row is not None and text:
        import re as _re
        def _repl(m):
            v = data_row.get(m.group(1), "")
            return str(v) if v is not None else ""
        text = _re.sub(r"\{([A-Za-z0-9_-]+)\}", _repl, text)
    if DRY_RUN:
        print(f"  [dry] colar {text!r}")
        return
    print(f"  colar {text!r}")
    try:
        import pyperclip
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except Exception:
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
        return f"    _type({txt!r}, interval=0.03, data_row=data_row)"
    if a == Action.SCROLL.value:
        return f"    _scroll(dx={s.dx}, dy={s.dy}, x={s.x}, y={s.y})"
    if a == Action.MOVE.value:
        return f"    _move(x={s.x}, y={s.y})"
    if a == Action.SCREENSHOT.value:
        return "    pass  # screenshot (marcador no replay)"
    return "    pass"


def to_python(steps: List[Step], dry_run: bool = False) -> str:
    """Gera o replay.py completo.

    Quando `data.xlsx` existir na pasta da gravação, o replay itera uma vez
    por linha e substitui {placeholder} nos passos TYPE pelos valores da
    coluna correspondente. Sem data.xlsx → 1 execução (comportamento atual).
    """
    header = _tpl_header(len(steps), sum(s.t for s in steps) if steps else 0.0,
                          _dt.now().isoformat())
    helpers = _tpl_helpers()
    lines = [
        "def run(data_row=None):",
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
    # footer: ler data.xlsx (se existir) e iterar por linha
    lines += _footer_data()
    return header + helpers + "\n".join(lines) + "\n"


def _footer_data() -> List[str]:
    """Gerador do footer __main__: carrega data.xlsx e roda run() 1x/linha."""
    return [
        "def _print_sep(i, n):",
        '    print(f"\\n--- execucao {i}/{n} ---")',
        "",
        "def _load_data():",
        '    """Lê data.xlsx (se existir na pasta) -> list de dicts. None se ausente."""',
        '    p = Path(__file__).resolve().parent / "data.xlsx"',
        "    if not p.exists():",
        "        return None",
        "    try:",
        "        from openpyxl import load_workbook",
        "        wb = load_workbook(p, read_only=True, data_only=True)",
        "        ws = wb.active",
        "        rows = list(ws.iter_rows(values_only=True))",
        "        wb.close()",
        "        if not rows:",
        "            return None",
        "        header = [str(h).strip() if h is not None else f'col{i}' for i, h in enumerate(rows[0])]",
        "        data = []",
        "        for row in rows[1:]:",
        "            d = {header[i]: (str(row[i]) if i < len(row) and row[i] is not None else '') ",
        "                 for i in range(len(header))}",
        "            if all(str(v).strip() == '' for v in d.values()):",
        "                continue",
        "            data.append(d)",
        "        return data or None",
        "    except Exception as e:",
        '        print(f"  [!] data.xlsx: {e}")',
        "        return None",
        "",
        "if __name__ == '__main__':",
        "    _data = _load_data()",
        "    if _data is None:",
        "        run()",
        "    else:",
        "        print(f'  data.xlsx: {len(_data)} linha(s) — 1 execucao por linha')",
        "        for _i, _row in enumerate(_data, 1):",
        "            _print_sep(_i, len(_data))",
        "            run(data_row=_row)",
        "        print(f'  All done — {len(_data)} execucao(oes).')",
    ]


def export_py(steps: List[Step], out_path: Path | str, dry_run: bool = False) -> Path:
    """Escreve replay.py em `out_path`."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_python(steps, dry_run=dry_run), encoding="utf-8")
    return out
