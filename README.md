# Macro Recorder (mrec)

Gravador de macro estilo Excel em Python para **Windows**: grava cliques,
digitação, atalhos e scroll, e reproduz por **âncora visual**
(`pyautogui.locateOnScreen(crop, confidence=...)`) em vez de coordenadas
absolutas — para o replay continuar funcionando mesmo com a janela movida.

Duo com **Excel de apoio** (1 linha = 1 execução; cada coluna vira
placeholder `{campo}`) e **GUI Tkinter** com hotkey F9.

## Instalação

```bash
py -V:3.14 -m venv .venv
.venv\Scripts\pip install -e ".[ocr,dev]"
```

- `[ocr]` (opcional, recomendado): `opencv-python[full] + numpy` — permite
  `confidence<1` em `locateOnScreen`. Sem o pacote, o replay cai para match
  exato (confidence=1) e NUNCA para matching sem confidence (TM_CCOEFF
  achava qualquer pixel e o clique caía em outro app).

## Uso

### CLI

```bash
mrec record                 # F9 liga / F9 desliga
mrec replay <pasta>         # reproduz (move o mouse!)
mrec replay <pasta> --dry-run  # só imprime os passos
```

### GUI

```bash
.venv\Scripts\python -m macro_recorder.gui     # (ou macrorecorder.exe)
```

- **F9** liga/desliga a gravação — o próprio F9 nunca é gravado.
- Botões **Reproduzir** / **Reproduzir (dry-run)** rodam o replay com os
  controles internos (sem abrir CMD na frente).
- Suporta pasta de destino, hotkey alternativo e "Excel de apoio".

## Excel de apoio (1 linha = 1 execução)

Se `replay.py` encontrar um arquivo `.xlsx` na pasta, o replay lê cada
linha como uma execução separada. Cada coluna vira um placeholder `{campo}`:

| cpf | nome | end |
|-----|------|-----|
| 111.111.111-11 | João | Rua X, 123 |
| 222.222.222-22 | Maria | Rua Y, 456 |

- Coluna com placeholder `{...}` no nome → o valor é copiado para o
  **clipboard** antes de cada `type` que usa esse campo — assim senhas e
  números de cartão nunca passam pelo teclado (nem o `pyautogui.typewrite`
  recebe o texto).
- Coluna sem placeholder → ignorada.
- Sem `.xlsx` → 1 execução (100% retrocompatível).

## Failsafe

- **Reprodução real**: `pyautogui.FAILSAFE = True` já vem habilitado. Levar
  o mouse ao canto **superior-esquerdo** da tela (0, 0) aborta
  instantaneamente `FailsafeException`.
- **Gravação**: `Ctrl+C` no console cancela e descarta.
- **Âncora não achada**: se nenhuma das âncoras casar com confiança 0.9 /
  0.8 / 0.7, o replay imprime `[!] nao-localizei` e **não clica** — nunca
  cai no matching sem confidence.

## Âncoras visuais (cascata 120 / 240 / 360)

Cada clique grava a região ao redor do cursor (60px de margem por lado =
120×120). Antes de salvar, o listener **mede o número de cores únicas**
(quantização 256 níveis). Se forem < 40 (fundo uniforme, branco, etc.):

| tentativa | margem  | total   |
|-----------|---------|---------|
| 1         | 60 px   | 120×120 |
| 2         | 120 px  | 240×240 |
| 3         | 180 px  | 360×360 |

A primeira com ≥ 40 cores vira a **âncora principal**; as maiores ficam
como **fallback** nos nomes `a01.png`, `a01b.png`, `a01c.png`. O replay tenta
cada âncora em ordem (principal → fallbacks) até localizar. Se nenhuma
casar, imprime `[!] nao-localizei` e **não clica** (evita clicar em outro
app).

> **Dica para cliques em fundo vazio**: clique perto de texto, ícones ou
> bordas — qualquer coisa que dê ≥ 40 cores únicas dentro do retângulo.
> Clicar no meio de uma tela branca pura usa a 360×360 e ainda pode não
> casar se o fundo for monocromático.

## Filtros de gravação

- **Teclas de deleção** (`DEL`, `Backspace`, `Ctrl+DEL`, etc.) **nunca**
  viram passo — mesmo em combinação com modificadores.
- **Cliques na própria GUI**: se a janela ativa é a do Macro Recorder e o
  ponto (x, y) cai dentro do bounding box dela, o clique é **descartado**
  (com log `[gui] clique ignorado`). Impede gravar cliques em "Parar",
  "Reproduzir", "Exportar", etc.
- **F9** (hotkey de start/stop) nunca é gravado.
- **Campo de senha** (heurística por título da janela em foco) — texto é
  sempre gravado como `text="***"` com `redacted: true`.

## Artefatos

Cada gravação gera um diretório `recordings/<timestamp>/`:

```
recordings/2026-09-22_14-30-00/
├── recording.json          # modelo serializável (Steps + metadata)
├── passo-a-passo.md        # resumo humano em PT-BR
├── replay.py               # replay standalone runnable
├── dados.xlsx (opcional)   # Excel com 1 linha por execução
└── assets/
    ├── a01.png             # âncora 1 (principal)
    ├── a01b.png            # fallback 240×240 (se houve cascata)
    ├── a01c.png            # fallback 360×360 (se houve cascata)
    ├── a02.png             # âncora 2 (próximo clique)
    └── ...
```

## Testes

```bash
.venv\Scripts\pytest        # 95 unit tests (não exigem display)
```

## Build (`.exe` standalone)

```bash
.venv\Scripts\python build_exe.py
# -> dist/macrorecorder.exe  (~84 MB, self-contained)
```

O `.exe` já carrega um mini-venv com todos os deps (pyautogui, pynput,
mss, opencv + numpy, openpyxl, ...). **Feche** o `macrorecorder.exe`
antes de rodar o build novamente (o exe fica em uso).

## Detalhes do Windows (crítico)

- **DPI awareness**: `record` e `replay` chamam `SetProcessDpiAwareness(2)`
  no topo — coordonadas virtuais consistentes com o monitor.
- **pynput** sem admin funciona para apps comuns; jogos / VMs / RDP podem
  engolir eventos.
- **Hotkey** padrão `F9`; override via env `MREC_HOTKEY` (ex.: `f12`).
- **Multimonitor**: coordonadas virtuais (podem ser negativas) — os
  `crops` usam `pyautogui.screenshot(region=...)` com clamp.
- **Redigidos**: campos de senha nunca vazam para o JSON/MD/replay.py.
- **Subprocess do replay (GUI)**: `CREATE_NO_WINDOW` — a GUI roda o
  `python replay.py` num processo sem janela, então **não abre CMD na
  frente** durante o replay. O console interno da GUI continua mostrando
  o log.

## Estrutura

```
src/macro_recorder/
├── __init__.py              # version
├── events.py                # dataclasses Step/Recording + enum Action
├── listener.py              # EventCollector + Recorder (pynput) + filtro GUI
├── capture.py               # make_crop + make_cascading_crops + find_anchor
├── exporter_md.py           # gera passo-a-passo.md
├── exporter_py.py           # gera replay.py standalone
├── excel_data.py            # helpers para o Excel de apoio
├── replay.py                # executa replay.py (subprocess)
├── gui.py                   # app Tkinter (F9 + botões)
└── cli.py                   # entrypoint `mrec`
```

## Roadmap

- [ ] Gravar janela ativa + título do app (ajuda a identificar onde
      clicar em caso de falha de match).
- [ ] Detectar âncoras **dinâmicas** (regiões que mudam entre execuções,
      ex.: relógio na taskbar) e sugerir crop maior ou âncora alternada.
- [ ] Histórico de execuções (log das linhas do Excel já processadas).
