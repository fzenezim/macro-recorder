"""E2E headless da GUI — constrói, dispara _toggle_record e verifica.

Uso:  python -m macro_recorder._e2e_gui_test

Fluxo:
  1. Constrói o MacroRecorderApp
  2. Ajusta a pasta de saída
  3. Chama _toggle_record (cria o Recorder em thread e guarda em app._rec)
  4. Usa rec.toggle() para LIGA e rec.toggle() para DESLIGA
     (o pynput.Controller injeta F9 de um jeito que o hook global do MESMO
      processo não propaga como "segunda press" — uso toggle programático)
  5. Aguarda os 3 artefatos (recording.json + passo-a-passo.md + replay.py)
"""

from __future__ import annotations

import time
from pathlib import Path


def main() -> int:
    print("\n[e2e] ═══════════════════════════════════════════════", flush=True)
    print("[e2e] Testando GUI end-to-end", flush=True)
    print("[e2e] ═══════════════════════════════════════════════\n", flush=True)

    # 1) importa o app
    from macro_recorder.gui import MacroRecorderApp

    app = MacroRecorderApp()
    app.update()
    print("[e2e] 1) app construído", flush=True)

    # 2) muda a pasta de saída
    app.entry_out.delete(0, "end")
    app.entry_out.insert(0, "recordings")
    print("[e2e] 2) out dir = recordings", flush=True)

    # 3) dispara _toggle_record
    app._toggle_record()
    app.update()
    print("[e2e] 3) _toggle_record invocado", flush=True)

    # 4) espera o Recorder (app._rec)
    deadline = time.time() + 5
    while time.time() < deadline:
        rec = getattr(app, "_rec", None)
        if rec is not None:
            break
        app.update()
        time.sleep(0.2)
    rec = getattr(app, "_rec", None)
    print(f"[e2e] 4) Recorder obtido: {rec is not None}", flush=True)
    if rec is None:
        print("[e2e] ❌ Recorder indisponível — falha no _toggle_record", flush=True)
        app.destroy()
        return 1

    # 5) _toggle_record já chamou rec.toggle() (LIGA)
    # Espera o estado de gravamento
    deadline = time.time() + 5
    while time.time() < deadline and not rec._collector.is_recording:
        app.update()
        time.sleep(0.2)
    print(f"[e2e] 5) is_recording={rec._collector.is_recording}", flush=True)
    if not rec._collector.is_recording:
        print("[e2e] ❌ gravação não LIGOU no _toggle_record", flush=True)
        app.destroy()
        return 1

    # 6) DESLIGA (2º F9 via toggle programático)
    print("[e2e] 6) DESLIGA (toggle 2)", flush=True)
    rec.toggle()
    time.sleep(0.5)
    print(f"[e2e]    is_recording={rec._collector.is_recording}", flush=True)

    # 7) espera os 3 artefatos
    deadline = time.time() + 30
    while time.time() < deadline:
        rec_root = Path("recordings")
        if rec_root.exists():
            dirs = sorted(
                [d for d in rec_root.iterdir() if d.is_dir() and d.name.startswith("202")],
                key=lambda p: p.name,
            )
            if dirs:
                last = dirs[-1]
                if (last / "recording.json").exists() and \
                   (last / "passo-a-passo.md").exists() and \
                   (last / "replay.py").exists():
                    print(f"\n[e2e] ✅ 7) gravação salva em {last}/", flush=True)
                    for f in sorted(last.iterdir()):
                        print(f"   - {f.name}", flush=True)
                    app.after(500, app.destroy)
                    app.update()
                    app.destroy()
                    return 0
        app.update()
        time.sleep(0.5)

    print("\n[e2e] ❌ 7) timeout — gravação não salva", flush=True)
    app.destroy()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
