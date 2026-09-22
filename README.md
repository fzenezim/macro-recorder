# Macro Recorder

Gravador de macro estilo Excel em Python para **Windows**: grava cliques,
digitação, atalhos e scroll, e reproduz por **âncora visual**
(`pyautogui.locateOnScreen(crop, confidence=...)`) em vez de coordenadas
absolutas — para o replay continuar funcionando mesmo com a janela movida.

> 🚧 Projeto em construção — ver `BRIEF-para-outro-agente.md` (fora do repo).

## Instalação

```bash
py -V:3.14 -m venv .venv
.venv\Scripts\pip install -e ".[ocr,dev]"
```

## Uso

```bash
mrec record                 # F9 liga / F9 desliga
mrec replay <pasta>         # reproduz
mrec replay <pasta> --dry-run  # só imprime os passos
```

## Deposições do Windows (crítico)

- **DPI awareness**: ambos `record` e `replay` chamam
  `SetProcessDpiAwareness(2)` no topo.
- **pynput** sem admin funciona, mas jogos / VMs / Remote Desktop podem
  engolir eventos.
- **Hotkey** padrão `F9`; override via env `MREC_HOTKEY` (ex.: `f12`).
- **Multimonitor**: coordenadas virtuais (podem ser negativas) — os crops
  usam `pyautogui.screenshot(region=...)` com clamp.
- **Opção `ocr`**: opencv + numpy permitem `confidence<1` em
  `locateOnScreen`; sem o pacote, cai para match exato (confidence=1)
  com aviso no console.

## Testes

```bash
.venv\Scripts\pytest        # unit tests (não exigem display)
```
