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
    """Gera o texto markdown completo (formato IPE — com screenshots a cada clique)."""
    if not steps:
        return "# Passo a passo — sem passos gravados\n"
    name = recording.meta.get("name", "rec")
    created_at = recording.created_at
    if isinstance(created_at, str):
        ca_str = created_at
    else:
        ca_str = created_at.isoformat()
    out = []
    out.append(f"# IPE — passo a passo ({name}, {recording.duration_s:.2f}s)")
    out.append(f"> _Gerado por `mrec` em {datetime.now().isoformat()}_")
    out.append(_resumo(steps))
    out.append("## Passos")
    out.append("")
    for n, s in enumerate(steps, 1):
        a = s.action
        # sufixo "mN" quando o passo grava o monitor (IPE dinâmica)
        mtag = f" [monitor {s.monitor}]" if s.monitor else ""
        if a in (Action.CLICK.value, Action.DOUBLE_CLICK.value, Action.RIGHT_CLICK.value):
            label = {"click": "Clique", "double_click": "Duplo clique", "right_click": "Clique direito"}.get(a, a)
            out.append(f"### {n}. {label} ({s.x}, {s.y}){mtag}")
            if s.crop:
                out.append(f"![ancora]({s.crop})")
            # screenshot completo (IPE) — o mais importante para o template
            if s.screenshot:
                out.append(f"\n![tela completa]({s.screenshot})")
            out.append("")
        elif a == Action.KEY.value:
            mods, key = s.keys[:-1], s.keys[-1]
            combo = "+".join(mods + [key]) if mods else key
            t_wait = s.t if s.t else 0.0
            out.append(f"### {n}. Atalho `{combo}` (t+{t_wait:.2f}s){mtag}")
            out.append("")
        elif a == Action.TYPE.value:
            if s.redacted:
                out.append(f"### {n}. Digitar `***` [_redigido_] (t+{s.t:.2f}s){mtag}")
            else:
                out.append(f"### {n}. Digitar `{s.text}` (t+{s.t:.2f}s){mtag}")
            if s.screenshot:
                out.append(f"![tela completa]({s.screenshot})")
            out.append("")
        elif a == Action.SCROLL.value:
            out.append(f"### {n}. Scroll ({s.dx}, {s.dy}) (t+{s.t:.2f}s)")
            out.append("")
        elif a == Action.MOVE.value:
            out.append(f"### {n}. Mover para ({s.x}, {s.y}) (t+{s.t:.2f}s)")
            out.append("")
    out.append("")
    return "\n".join(out)


def export_md(recording: Recording, steps: List[Step], out_path: Path | str) -> Path:
    """Escreve o MD em `out_path` e devolve o caminho."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = to_markdown(recording, steps)
    out.write_text(text, encoding="utf-8")
    return out
