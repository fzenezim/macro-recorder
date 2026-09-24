"""Ponte subprocesso — chamado pelo GUI para iniciar a gravação.

Lê as env vars MREC_* e executa o loop do Recorder.
Uso:  python -m macro_recorder._record_bridge
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    # importa aqui (depois que o usuário configurou o venv)
    from macro_recorder.listener import Recorder
    import json
    from datetime import datetime

    hotkey = os.environ.get("MREC_HOTKEY", "f9").lower()
    out_root = Path(os.environ.get("MREC_OUT", "recordings"))
    cap_text = os.environ.get("MREC_CAP_TEXT", "1") == "1"
    cap_clicks = os.environ.get("MREC_CAP_CLICKS", "1") == "1"
    cap_scroll = os.environ.get("MREC_CAP_SCROLL", "1") == "1"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = out_root / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assets").mkdir(exist_ok=True)

    print(f"\n[bridge] ═══════════════════════════════════════════", flush=True)
    print(f"[bridge]   HOTKEY:   {hotkey.upper()}", flush=True)
    print(f"[bridge]   PASTA:    {out_dir}", flush=True)
    print(f"[bridge]   CAPTURA:  texto={cap_text} cliques={cap_clicks} scroll={cap_scroll}", flush=True)
    print(f"[bridge]   Pressione {hotkey.upper()} quando PRONTO para gravar", flush=True)
    print(f"[bridge]   Pressione {hotkey.upper()} de novo para PARAR", flush=True)
    print(f"[bridge]   (FailSafe: arraste o mouse para o canto superior-esquerdo)", flush=True)
    print(f"[bridge] ═══════════════════════════════════════════\n", flush=True)

    print(f"[bridge] esperando {hotkey.upper()} (1ª) para LIGAR a gravação...", flush=True)

    try:
        rec = Recorder(
            out_dir=out_dir,
            hotkey=hotkey,
            capture_text=cap_text,
            capture_clicks=cap_clicks,
            capture_scroll=cap_scroll,
        )
        recording = rec.run()
    except KeyboardInterrupt:
        print("\n[bridge] cancelado pelo usuário (Ctrl+C).", flush=True)
        import shutil
        shutil.rmtree(out_dir, ignore_errors=True)
        return 1
    except Exception as e:
        print(f"[bridge] ERRO: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return 2

    print('[bridge] DEBUG: rec.run() retornou, gravando artefatos...', flush=True)
    print('[bridge] DEBUG: nº de passos =', len(recording.steps), flush=True)
    steps = recording.steps
    print('[bridge] DEBUG: escrito out_dir/ =', out_dir, flush=True)
    rec_path = out_dir / "recording.json"
    rec_path.write_text(json.dumps(recording.to_dict(), indent=2), encoding="utf-8")

    import macro_recorder.exporter_md as md
    import macro_recorder.exporter_py as pyexp
    md.export_md(recording, steps, out_dir / "passo-a-passo.md")
    pyexp.export_py(steps, out_dir / "replay.py")

    crops = sum(1 for s in steps if s.crop)
    print(f"\n[bridge] ok!  {len(steps)} passos salvos em {out_dir}/", flush=True)
    print(f"[bridge]   recording.json", flush=True)
    print(f"[bridge]   passo-a-passo.md", flush=True)
    print(f"[bridge]   replay.py", flush=True)
    print(f"[bridge]   assets/ ({crops} crops)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
