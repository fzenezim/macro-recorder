"""Modelo de dados do Macro Recorder.

    Step:      um passo individual (clique, digitação, atalho, scroll, ...)
    Recording: uma gravação completa (lista de Steps + metadados)

Serialização JSON bidirecional (to_dict / from_dict) para o replay.py
gerado rodar em ambiente sem o pacote do projeto.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class Action(str, Enum):
    """Tipos de passo gravados."""

    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    MOVE = "move"
    TYPE = "type"
    KEY = "key"
    SCROLL = "scroll"


@dataclass
class Step:
    """Um passo individual.

    Campos opcionais dependem da ação:
        - click / double_click / right_click / move: x, y, crop
        - type:    text, redacted
        - key:     keys (ex.: ["ctrl", "s"])
        - scroll:  dx, dy
    """

    action: str = Action.CLICK.value
    t: float = 0.0  # segundos desde o início da gravação

    # mouse
    x: Optional[int] = None
    y: Optional[int] = None
    crop: Optional[str] = None  # caminho relativo do crop de tela

    # keyboard
    text: Optional[str] = None
    redacted: bool = False
    keys: Optional[list] = None

    # scroll
    dx: Optional[int] = None
    dy: Optional[int] = None

    # ── serialização ───────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        """Seriáliza para dict JSON-able (só campos com valor)."""
        d: dict[str, Any] = {"action": self.action, "t": self.t}
        if self.x is not None:
            d["x"] = self.x
        if self.y is not None:
            d["y"] = self.y
        if self.crop is not None:
            d["crop"] = self.crop
        if self.text is not None:
            d["text"] = self.text
        if self.redacted:
            d["redacted"] = True
        if self.keys is not None:
            d["keys"] = list(self.keys)
        if self.dx is not None or self.dy is not None:
            d["dx"] = self.dx or 0
            d["dy"] = self.dy or 0
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Step":
        """Deseriza um dict JSON-able para Step."""
        return cls(
            action=d["action"],
            t=d.get("t", 0.0),
            x=d.get("x"),
            y=d.get("y"),
            crop=d.get("crop"),
            text=d.get("text"),
            redacted=d.get("redacted", False),
            keys=d.get("keys"),
            dx=d.get("dx"),
            dy=d.get("dy"),
        )


@dataclass
class Recording:
    """Uma gravação completa."""

    created_at: str = ""  # ISO-8601 UTC
    duration_s: float = 0.0
    steps: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)  # hotkey, resumo, etc.

    # ── serialização ───────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "created_at": self.created_at,
            "duration_s": self.duration_s,
            "steps": [s.to_dict() for s in self.steps],
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Recording":
        return cls(
            created_at=d.get("created_at", ""),
            duration_s=d.get("duration_s", 0.0),
            steps=[Step.from_dict(s) for s in d.get("steps", [])],
            meta=d.get("meta", {}),
        )

    def save_json(self, path: Path) -> Path:
        """Escreve o recording em <path> (JSON indentado, UTF-8)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load_json(cls, path: Path) -> "Recording":
        """Carrega um recording de <path>."""
        with Path(path).open("r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    # conveniência de contagens para o resumo ao parar
    def counts(self) -> dict:
        out = {"total": len(self.steps)}
        for a in Action:
            out[a.value] = sum(1 for s in self.steps if s.action == a.value)
        return out
