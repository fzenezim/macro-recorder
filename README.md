# Macro Recorder

Gravador de macro estilo Excel em Python para **Windows**: grava cliques,
digitação, atalhos e scroll, e reproduz por **âncora visual**
(`pyautogui.locateOnScreen(crop, confidence=...)`) em vez de coordenadas
absolutas — para o replay continuar funcionando mesmo com a janela movida.

## Instalação

```bash
py -V:3.14 -m venv .venv
.venv\Scripts\pip install -e ".[ocr,dev]"
```

## Uso

```bash
mrec record                 # F9 liga / F9 desliga
mrec replay <pasta>         # reproduz (move o mouse!)
mrec replay <pasta> --dry-run  # só imprime os passos
```

### Failsafe

- **Reprodução real**: o `pyautogui.FAILSAFE = True` já vem habilitado.
  Basta levar o mouse ao canto **superior-esquerdo** da tela (0, 0)
  para abortar instantaneamente.
- **Gravação**: `Ctrl+C` no console cancela e descarta.

## Artefatos

Cada gravação gera um diretório `recordings/<timestamp>/`:

```
recordings/2026-09-22_14-30-00/
├── recording.json          # modelo serializável (Steps + metadata)
├── passo-a-passo.md        # resumo humano em PT-BR
├── replay.py               # replay standalone runnable
└── assets/
    ├── a01.png             # crops das âncoras visuais
    ├── a02.png
    └── ...
```

## Testes

```bash
.venv\Scripts\pytest        # 70 unit tests (não exigem display)
```

## Deposições do Windows (crítico)

- **DPI awareness**: `record` e `replay` chamam `SetProcessDpiAwareness(2)`
  no topo — coordenes virtuais consistentes com o monitor.
- **pynput** sem admin funciona para apps comuns; jogos / VMs / RDP podem
  engolir eventos.
- **Hotkey** padrão `F9`; override via env `MREC_HOTKEY` (ex.: `f12`).
- **Multimonitor**: coordenadas virtuais (podem ser negativas) — os
  `crops` usam `pyautogui.screenshot(region=...)` com clamp.
- **Opção `ocr`**: `opencv-python[full] + numpy` permitem
  `confidence<1` em `locateOnScreen`; sem o pacote, cai para match exato
  (confidence=1) e tenta sem parâmetro.
- **Redigidos**: campos de senha são sempre gravados como `text="***"`
  com `redacted: true` — **nunca** vaza no JSON/MD/replay.py.

## Estrutura

```
src/macro_recorder/
├── __init__.py              # version
├── events.py                # dataclasses Step/Recording + enum Action
├── listener.py              # EventCollector + Recorder (pynput)
├── capture.py               # crop de tela + find_anchor (cascata confidence)
├── exporter_md.py           # gera passo-a-passo.md
├── exporter_py.py           # gera replay.py standalone
├── replay.py                # executa replay.py (subprocess)
└── cli.py                   # entrypoint `mrec`
```

## Roadmap pós-MVP

- [ ] Gravar multi-captura: se o app tem vários pontos possíveis (ex.
      menu > File > Save vs. toolbar), tentar cada âncora em sequência.
- [ ] Gravar janela ativa + título do app (ajuda a identificar onde
      clicar em caso de falha de match).
- [ ] PyInstaller para gerar `mrec.exe` único.
