"""Macro Recorder — gravador de macro estilo Excel em Python.

Pacotes internos:
    - events:      dataclasses Step / Recording (serializa/deserializa JSON)
    - listener:    captura eventos com pynput -> Steps
    - capture:     crop de tela + locateOnScreen
    - exporter_md: gera passo_a_passo.md
    - exporter_py: gera replay.py standalone
    - replay:      runner do replay (carrega recording.json, --dry-run)
    - cli:         entry point `mrec` (record / replay)
"""

__version__ = "0.1.0"
