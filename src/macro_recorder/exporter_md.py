# -*- coding: utf-8 -*-
"""Exporta Recording como passo-a-passo.md (PT-BR)."""
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from macro_recorder.events import Recording, Step, Action


def build_step_line(n: int, s: Step) -> str:
    """Linha de resumo humano para 1 passo."""
    a = s.action
    if a == Action.CLICK.value:
        crop = s.crop if s.crop else None
        return f"({n}) Clique ({s.x}, {s.y})" + (f" [crop: {crop}]" if crop else "")
    return (
        f"({n}) {s.action}"
        + (f" em ({s.x}, {s.y})" if (s.x is not None and s.y is not None) else "")
    )


def _resumo(steps: List[Step]) -> str:
    linhas = []
    c = {k: 0 for k in [
        Action.CLICK.value, Action.DOUBLE_CLICK.value,
        Action.RIGHT_CLICK.value, Action.KEY.value,
        Action.TYPE.value, Action.SCROLL.value,
        Action.MOVE.value,
    ]}
    red = sum(1 for s in steps if s.redacted)
    cliques = c[Action.CLICK.value] + c[Action.DOUBLE_CLICK.value] + c[Action.RIGHT_CLICK.value]
    for s in steps:
        c[s.action] = c.get(s.action, 0) + 1
    linhas.append(f"""
## Resumo

- Total de passos: **{len(steps)}**
- Cliques (simples/duplo/direito): **{cliques}**
- Teclas/atalhos: **{c[Action.KEY.value]}**
- Texto digitado: **{c[Action.TYPE.value]}** (redigidos: {red})
- Scrolls: **{c[Action.SCROLL.value]}**
- Move: **{c[Action.MOVE.value]}**
""")
    return "\n".join(linhas)


def to_markdown(recording: Recording, steps: List[Step]) -> str:
    """Gera o texto markdown completo."""
    if not steps:
        return "# Passo a passo — sem passos gravados\n"
    name = recording.meta.get("name", "rec")
    created_at = recording.created_at
    if isinstance(created_at, str):
        ca_str = created_at  # já é string ISO (do JSON to_dict)
    else:
        ca_str = created_at.isoformat()  # datetime -> ISO string
    out = []
    out.append(f"# Passo a passo — {ca_str} ({name}, {recording.duration_s:.2f}s)")
    out.append(f"> _Gerado por `mrec` em {datetime.now().isoformat()}_")
    out.append(_resumo(steps))
    out.append("## Passos")
    out.append("")
    for n, s in enumerate(steps, 1):
        a = s.action
        if a == Action.CLICK.value:
            line = f"({n}) Clique ({s.x}, {s.y})"
            if s.crop:
                line += f"\n    ![a{n:02d}](assets/{s.crop})"
            out.append(line)
        elif a == Action.DOUBLE_CLICK.value:
            line = f"({n}) Duplo clique ({s.x}, {s.y})"
            if s.crop:
                line += f"\n    ![a{n:02d}](assets/{s.crop})"
            out.append(line)
        elif a == Action.RIGHT_CLICK.value:
            line = f"({n}) Clique direito ({s.x}, {s.y})"
            if s.crop:
                line += f"\n    ![a{n:02d}](assets/{s.crop})"
            out.append(line)
        elif a == Action.KEY.value:
            # combina modificadores com + e a tecla
            mods, key = s.keys[:-1], s.keys[-1]
            combo = "+".join(mods + [key]) if mods else key
            t_wait = s.t if s.t else 0.0
            out.append(f"({n}) Atalho: `{combo}` (t+{t_wait:.2f}s)")
        elif a == Action.TYPE.value:
            if s.redacted:
                out.append(f"({n}) Digitar `***` [_redigido — senha_] (t+{s.t:.2f}s)")
            else:
                out.append(f"({n}) Digitar `{s.text}` (t+{s.t:.2f}s)")
        elif a == Action.SCROLL.value:
            out.append(f"({n}) Scroll ({s.dx}, {s.dy}) em t+{s.t:.2f}s")
        elif a == Action.MOVE.value:
            out.append(f"({n}) Mover para ({s.x}, {s.y}) (t+{s.t:.2f}s)")
    out.append("")
    return "\n".join(out)


def export_md(recording: Recording, steps: List[Step], out_path: Path | str) -> Path:
    """Escreve o MD em `out_path` e devolve o caminho."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = to_markdown(recording, steps)
    out.write_text(text, encoding="utf-8")
    return out
