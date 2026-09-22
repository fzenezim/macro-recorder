"""Capture de tela: crop ao redor do cursor + âncora visual (locateOnScreen).

Responsabilidades:
    - make_crop(x, y): recorta a região ao redor do ponto (x, y) com margem
      `CROP_MARGIN` e salva em <out_path>. Retorna (region_box, path).
      Trata coordenadas virtuais multimonitor (podem ser negativas).
    - find_anchor(crop_path, step_no): usa pyautogui.locateOnScreen com
      fallback de confiança (0.9 → 0.8 → 0.7). Se opencv não está
      disponível, cai para match exato (confidence=None). Se nada acerta,
      lança AnchorNotFound com o nº do passo + instrução — NUNCA clica
      em ponto cego.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

CROP_MARGIN = 60  # px ao redor do ponto
_CONFIDENCE_LADDERS = (0.9, 0.8, 0.7)


class AnchorNotFound(Exception):
    """Âncora (crop) não encontrada na tela pelo locateOnScreen.

    Mensagem contém o número do passo e uma dica (mover a janela, recorte
    manual). O replay não clica em ponto cego — aborta limpo.
    """

    def __init__(self, step_no: int, crop: Path):
        self.step_no = step_no
        self.crop = Path(crop)
        super().__init__(
            f"âncora não encontrada no passo {step_no:02d} "
            f"([{self.crop.name}]). Tente mover a janela de volta para a "
            f"posição original ou atualize o crop manualmente "
            f"(assets/{self.crop.name})."
        )


# ───────────────────────────────────────────────────────────────────────────
# clamp
# ───────────────────────────────────────────────────────────────────────────
def _clamp_box(
    left: int,
    top: int,
    right: int,
    bottom: int,
    *,
    virtual_origin: Tuple[int, int] = (0, 0),
    virtual_size: Tuple[int, int] = (0, 0),
) -> Tuple[int, int, int, int]:
    """Clampa um retângulo (left, top, right, bottom) dentro de uma área.

    Se virtual_size for (0, 0), não clampa (retorna sem alteração).
    """
    if virtual_size[0] == 0 or virtual_size[1] == 0:
        return left, top, right, bottom
    vo_x, vo_y = virtual_origin
    vw, vh = virtual_size
    lo_x, lo_y = vo_x, vo_y
    lo_x_max = lo_x + vw
    lo_y_max = lo_y + vh

    def c(v: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, v))

    L = c(left, lo_x, lo_x_max)
    T = c(top, lo_y, lo_y_max)
    R = c(right, lo_x, lo_x_max)
    B = c(bottom, lo_y, lo_y_max)
    # garante R > L, B > T (se o retângulo for menor que a tela)
    if R < L:
        R = L
    if B < T:
        B = T
    return L, T, R, B


# ───────────────────────────────────────────────────────────────────────────
# crop
# ───────────────────────────────────────────────────────────────────────────
def make_crop(
    x: int,
    y: int,
    *,
    screen_size: Optional[Tuple[int, int]] = None,
    virtual_size: Optional[Tuple[int, int]] = None,
    virtual_origin: Optional[Tuple[int, int]] = None,
    margin: int = CROP_MARGIN,
    out_path: Path | str,
) -> Tuple[Tuple[int, int, int, int], Path]:
    """Recorta a tela ao redor de (x, y) e salva em <out_path>.

    Argumentos:
        x, y: coordenadas virtuais (podem ser negativas — multimonitor)
        screen_size: (w, h) da tela principal (para clamp quando é a única
            tela). Se virtual_size for dado, usa-se este.
        virtual_size: (w, h) da área virtual total (multimonitor).
        virtual_origin: (x, y) da origem da área virtual — default (0, 0)
        margin: largura da margem ao redor do ponto (default 60)
        out_path: onde salvar o PNG

    Retorna (region_box, path):
        region_box = (left, top, width, height) — o que screenshot(region=)
            recebeu.
    """
    import pyautogui
    from PIL import Image  # import aqui para não quebrar se PIL não estiver

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # resolve a área de referência para o clamp
    if virtual_size and virtual_size[0] > 0 and virtual_size[1] > 0:
        v_origin = virtual_origin or (0, 0)
        v_size = virtual_size
    elif screen_size:
        v_origin = (0, 0)
        v_size = screen_size
    else:
        # fallback: descobre via pyautogui
        full = pyautogui.screenshot()
        v_origin = (0, 0)
        v_size = (full.size[0], full.size[1]) if hasattr(full, "size") else (1920, 1080)
        full.close() if hasattr(full, "close") else None  # type: ignore

    L = x - margin
    T = y - margin
    R = x + margin
    B = y + margin
    L, T, R, B = _clamp_box(L, T, R, B, virtual_origin=v_origin, virtual_size=v_size)

    region = (L, T, R - L, B - T)
    img = pyautogui.screenshot(region=region)
    # salva (mesmo no mock, que implementa .save)
    img.save(str(out_path))
    if hasattr(img, "close"):
        img.close()

    return region, out_path


# ───────────────────────────────────────────────────────────────────────────
# find_anchor
# ───────────────────────────────────────────────────────────────────────────
def find_anchor(
    crop: Path | str,
    *,
    step_no: int = 0,
    ladder: Tuple[float, ...] = _CONFIDENCE_LADDERS,
) -> Tuple[int, int]:
    """Encontra o centro da âncora na tela via locateOnScreen.

    Tenta confidences em cascata; se opencv não está instalado
    (confidence<1 lança), cai para match exato (confidence=None).
    Se nada acerta, lança AnchorNotFound(step_no, crop).
    """
    import pyautogui

    crop = Path(crop)
    if not crop.exists():
        raise FileNotFoundError(f"crop não existe: {crop}")

    # tenta com confidences da ladder
    opencv_unavailable = False
    for conf in ladder:
        try:
            loc = pyautogui.locateOnScreen(str(crop), confidence=conf)
        except AssertionError:
            # opencv ausente: para a ladder e cai para match exato
            opencv_unavailable = True
            break
        except Exception:  # noqa: BLE001
            continue
        if loc is not None:
            return _center(loc)

    # fallback para match exato (confidence=None explicitamente)
    try:
        loc = pyautogui.locateOnScreen(str(crop), confidence=None)
    except Exception:
        loc = None
    if loc is not None:
        return _center(loc)

    # última tentativa: sem o kwarg (comportamento default do pyautogui)
    try:
        loc = pyautogui.locateOnScreen(str(crop))
    except Exception:
        loc = None
    if loc is not None:
        return _center(loc)

    raise AnchorNotFound(step_no, crop)


def _center(loc) -> Tuple[int, int]:
    """Extrai (cx, cy) de um Box/Location-like."""
    # pyautogui.center devolve (x, y)
    try:
        import pyautogui
        return tuple(pyautogui.center(loc))  # type: ignore
    except Exception:
        # fallback manual
        left = getattr(loc, "left", None)
        top = getattr(loc, "top", None)
        width = getattr(loc, "width", None)
        height = getattr(loc, "height", None)
        if None in (left, top, width, height):
            # tuple (left, top, width, height)
            left, top, width, height = loc  # type: ignore
        return int(left + width / 2), int(top + height / 2)
