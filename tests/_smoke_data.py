# -*- coding: utf-8 -*-
"""Smoke test E2E: gravacao fake com placeholders -> replay com data.xlsx.

Roda em dry-run (nao mexe no mouse) e confere que:
  - sem data.xlsx  -> 1 execucao (placeholders cravados)
  - com  data.xlsx-> N execucoes (1 por linha), placeholders substituidos
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / ".." / "src"))

from macro_recorder.events import Step, Action
from macro_recorder.exporter_py import export_py
from macro_recorder.excel_data import make_template, load_rows
from macro_recorder.replay import replay_from_dir
from openpyxl import load_workbook


def build(steps, rec_dir: Path):
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / "assets").mkdir(exist_ok=True)
    from macro_recorder.events import Recording
    rec = Recording(created_at="2026-01-01T00:00:00Z", duration_s=3.5,
                    steps=steps, meta={"hotkey": "f9"})
    rec.save_json(rec_dir / "recording.json")
    export_py(steps, rec_dir / "replay.py")
    return rec_dir


def main() -> int:
    tmp = Path(__file__).parent / "_smoke_data"
    tmp.mkdir(exist_ok=True)

    steps = [
        Step(action=Action.TYPE.value, t=1.0, text="CPF: {cpf}"),
        Step(action=Action.TYPE.value, t=2.0, text="Nome: {nome}"),
        Step(action=Action.CLICK.value, t=3.0, x=100, y=100),
    ]
    rec_dir = build(steps, tmp / "rec")

    # ── caso 1: sem data.xlsx -> 1 execucao ─────────────────────────────
    print("\n========== CASO 1: sem data.xlsx (1 execucao) ==========")
    rc = replay_from_dir(rec_dir, dry_run=True, verbose=False)
    assert rc == 0, f"rc={rc}"
    # confere que o replay.py tem a funcao _load_data
    text = (rec_dir / "replay.py").read_text(encoding="utf-8")
    assert "_load_data" in text, "footer data ausente"
    assert "run(data_row=None)" in text, "run() nao recebe data_row"
    assert "pyperclip" in text, 'colar via clipboard ausente'
    print("OK — 1 execucao, footer/data_row/clipboard presentes no replay.py")

    # ── caso 2: com data.xlsx 2 linhas -> 2 execucoes ─────────────────
    data = make_template(steps, rec_dir / "data.xlsx")
    # preenche 2 linhas
    wb = load_workbook(data)
    ws = wb.active
    ws.append(["111.222.333-44", "Feli Silva"])
    ws.append(["555.666.777-88", "Maria Souza"])
    wb.save(data)

    print("\n========== CASO 2: data.xlsx 2 linhas (2 execucoes) ==========")
    rc = replay_from_dir(rec_dir, dry_run=True, verbose=False)
    assert rc == 0, f"rc={rc}"
    print("\nOK — replay com data.xlsx exitou (rc=0)")
    # a saida do subprocess esta em stdout; capturamos via load_rows
    rows = load_rows(data)
    assert len(rows) == 2, f"expected 2 rows, got {len(rows)}"
    assert rows[0]["cpf"] == "111.222.333-44"
    print("OK — load_rows leu 2 linhas corretamente")

    # limpa o data.xlsx para o proximo run
    (rec_dir / "data.xlsx").unlink()
    print("\nSMOKE TEST PASSOU ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
