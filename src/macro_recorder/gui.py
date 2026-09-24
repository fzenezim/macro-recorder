"""Macro Recorder — GUI (customtkinter, dark theme).

Uso:
    python -m macro_recorder.gui

Estrutura:
    - 2 abas: 🎥 Record | ▶ Replay
    - Toggles de checkbox: capturar texto / cliques / scroll / foco-janela
    - Status em tempo real (REC ● GRAVANDO... pulsando em vermelho)
    - Console embutido (logs ao vivo)
    - Pasta de saída, hotkey, margem do crop, threshold de confiança

Decisão de design:
    - RECORD roda IN-PROCESS: o Recorder (listener pynput) tem um callback
      on_state_change(is_recording) thread-safe (queue), então a GUI só
      precisa de 1 thread de worker + as filas. Sem subprocess, sem bridge.
    - REPLAY roda via SUBPROCESS (python -m macro_recorder replay ...):
      o replay manipula o mouse/teclado reais de forma síncrona + pyautogui
      fail-safe; isolar em processo filho evita que um hang derrube a GUI e
      não conflita com o mainloop do tkinter.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import queue as _queue
from pathlib import Path

# Windows: DPI awareness (evita blur no display 125%/150%)
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import customtkinter as ctk

# ── cores dark (mesma paleta do audit-sample-generator) ────────────────
BG          = "#0f172a"
CARD        = "#1e293b"
CARD_HOVER  = "#334155"
ACCENT      = "#3b82f6"   # azul
ACCENT_HOVER= "#2563eb"
DANGER      = "#ef4444"   # vermelho
DANGER_HOVER= "#dc2626"
SUCCESS     = "#10b981"
SUCCESS_HOVER = "#059669"
WARN        = "#f59e0b"
TEXT        = "#e2e8f0"
TEXT_DIM    = "#94a3b8"
CONSOLE_BG  = "#0b1120"
CONSOLE_FG  = "#94a3b8"
FONT_TITLE  = ("Segoe UI", 22, "bold")
FONT_H      = ("Segoe UI", 15, "bold")
FONT_BODY   = ("Segoe UI", 13)
FONT_SMALL  = ("Segoe UI", 11)
FONT_MONO   = ("Consolas", 12)

# texto padrão do status por estado
_STATUS_TEXT = {
    "idle": "⏸  Pronto para gravar",
    "waiting": "⏱  Pressione o hotkey para LIGAR",
    "recording": "●  GRAVANDO...",
    "stopping": "⏸  Parando...",
    "done": "✅ Gravação salva!",
}


def _list_recordings(recordings_dir: Path) -> list[str]:
    """Lista pastas de gravação (nome por pasta, mais novas primeiro)."""
    if not recordings_dir.is_dir():
        return []
    out = []
    for p in recordings_dir.iterdir():
        if p.is_dir() and (p / "recording.json").is_file():
            out.append(p.name)
    return sorted(out, reverse=True)


def _find_project_root() -> Path:
    """Localiza o root do projeto (src/...) para o subprocess do replay."""
    py = Path(sys.executable)
    for parent in (py.parent.parent, py.parent):
        if (parent / "src" / "macro_recorder").is_dir():
            return parent
    return Path.cwd()


# ═════════════════════════════════════════════════════════════════════════
# App principal
# ═════════════════════════════════════════════════════════════════════════
class MacroRecorderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Macro Recorder — gravação & replay por âncora visual")
        self.geometry("900x720")
        self.minsize(780, 620)
        self.configure(fg_color=BG)

        self.project_root = _find_project_root()
        self.recordings_dir = Path("recordings")
        self._rec_worker = None
        self._rec = None  # Recorder exposto p/ botão PARAR + WM_DELETE_WINDOW
        # filas thread-safe (worker -> mainloop)
        self._q_log: _queue.Queue = _queue.Queue(maxsize=1000)
        self._q_status: _queue.Queue = _queue.Queue(maxsize=16)
        self._q_finish: _queue.Queue = _queue.Queue(maxsize=16)

        self._build_ui()
        self.after(100, self._poll_queue)

        # ao fechar a GUI: salva a gravação em curso
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        """Handler do WM_DELETE_WINDOW: salva a gravação em curso antes de fechar."""
        rec = self._rec
        if rec is not None and rec._running:
            self._log("[record] Fechando GUI — salvando gravação antes de sair...")
            # toggle para PARA + SALVA
            rec.toggle()
            # trava o mainloop e dá 5s para o worker salvar
            import time
            deadline = time.time() + 5.0
            while self._rec_worker is not None and self._rec_worker.is_alive() and time.time() < deadline:
                self.update()
                time.sleep(0.2)
            if self._rec_worker is not None and self._rec_worker.is_alive():
                self._log("[record] ⚠  Worker não terminou em 5s — forçando saída.")
        self.destroy()

    # ───────────────────── pump das filas (thread-safe) ─────────────────
    def _poll_queue(self):
        # logs
        try:
            while True:
                item = self._q_log.get_nowait()
                dest, _, msg = item.partition(":")
                (self._rlog if dest == "replay" else self._log)(msg)
        except _queue.Empty:
            pass
        # status
        try:
            while True:
                s = self._q_status.get_nowait()
                self._set_status(s, _STATUS_TEXT.get(s, ""))
        except _queue.Empty:
            pass
        # finalização de record/replay
        try:
            while True:
                which, code = self._q_finish.get_nowait()
                if which == "record":
                    self._record_finished(code)
                else:
                    self._replay_finished(code)
        except _queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # thread-safe emits
    def _log(self, msg: str) -> None:
        self.console.configure(state="normal")
        self.console.insert("end", msg + "\n")
        self.console.see("end")
        self.console.configure(state="disabled")

    def _rlog(self, msg: str) -> None:
        self.replay_console.configure(state="normal")
        self.replay_console.insert("end", msg + "\n")
        self.replay_console.see("end")
        self.replay_console.configure(state="disabled")

    def _emit_log(self, msg: str) -> None:
        try:
            self._q_log.put_nowait("main:" + msg)
        except _queue.Full:
            pass

    def _emit_rlog(self, msg: str) -> None:
        try:
            self._q_log.put_nowait("replay:" + msg)
        except _queue.Full:
            pass

    def _emit_status(self, state: str) -> None:
        try:
            self._q_status.put_nowait(state)
        except _queue.Full:
            pass

    def _emit_finish(self, which: str, code: int) -> None:
        try:
            self._q_finish.put_nowait((which, code))
        except _queue.Full:
            pass

    # ───────────────────── construção do UI ─────────────────────────────
    def _build_ui(self):
        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(padx=20, pady=20, fill="both", expand=True)
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(1, weight=1)

        # header
        hdr = ctk.CTkFrame(root, fg_color=CARD, corner_radius=14)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(
            hdr, text="🎬  Macro Recorder", font=FONT_TITLE, text_color=TEXT
        ).pack(side="left", padx=20, pady=12)
        ctk.CTkLabel(
            hdr,
            text="Grave cliques/teclado e repita por âncora visual",
            font=FONT_SMALL, text_color=TEXT_DIM,
        ).pack(side="left", padx=4, pady=(16, 12))
        ctk.CTkLabel(
            hdr, text="v0.3.0", font=FONT_SMALL, text_color=TEXT_DIM
        ).pack(side="right", padx=20)

        # tabs
        self.tabs = ctk.CTkTabview(
            root,
            fg_color=CARD,
            segmented_button_fg_color=CARD,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_HOVER,
            segmented_button_unselected_color=CARD,
            segmented_button_unselected_hover_color=CARD_HOVER,
            text_color=TEXT_DIM,
            corner_radius=10,
        )
        self.tabs.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=(0, 12))

        self._build_record_tab(self.tabs.add("🎥  Record"))
        self._build_replay_tab(self.tabs.add("▶  Replay"))

    # ───────────────────────── ABABA: RECORD ────────────────────────────
    def _build_record_tab(self, parent):
        main = ctk.CTkFrame(parent, fg_color="transparent")
        main.grid(sticky="nsew", padx=8, pady=8)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(4, weight=1)

        # status
        status_box = ctk.CTkFrame(main, fg_color=CONSOLE_BG, corner_radius=12)
        status_box.grid(row=0, column=0, sticky="ew", pady=(4, 10))
        self.status_lbl = ctk.CTkLabel(
            status_box, text="⏸  Pronto para gravar",
            font=("Segoe UI", 16, "bold"), text_color=TEXT_DIM,
        )
        self.status_lbl.pack(padx=16, pady=14)

        # settings
        settings = ctk.CTkFrame(main, fg_color=CONSOLE_BG, corner_radius=12)
        settings.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        settings.grid_columnconfigure((1, 3), weight=1)

        # file row
        ctk.CTkLabel(
            settings, text="📂 Pasta de saída:", font=FONT_BODY, text_color=TEXT
        ).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")
        file_row = ctk.CTkFrame(settings, fg_color="transparent")
        file_row.grid(row=0, column=1, columnspan=3, padx=8, pady=(12, 6), sticky="ew")
        file_row.grid_columnconfigure(0, weight=1)
        self.entry_out = ctk.CTkEntry(
            file_row, font=FONT_BODY, text_color=TEXT,
            fg_color=CARD, border_color=CARD_HOVER,
        )
        self.entry_out.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.entry_out.insert(0, "recordings")
        ctk.CTkButton(
            file_row, text="📁...", width=60, font=FONT_BODY,
            fg_color=CARD, hover_color=CARD_HOVER, command=self._pick_out_dir,
        ).grid(row=0, column=1)

        # hotkey row
        ctk.CTkLabel(
            settings, text="⌨  Tecla de iniciar/parar:", font=FONT_BODY, text_color=TEXT
        ).grid(row=1, column=0, padx=12, pady=6, sticky="w")
        self.entry_hotkey = ctk.CTkEntry(
            settings, width=120, font=FONT_BODY, text_color=TEXT,
            fg_color=CARD, border_color=CARD_HOVER,
        )
        self.entry_hotkey.grid(row=1, column=1, sticky="w", padx=8)
        self.entry_hotkey.insert(0, "f9")
        ctk.CTkLabel(
            settings, text="(padrão: f9  — ou defina MREC_HOTKEY)",
            font=FONT_SMALL, text_color=TEXT_DIM,
        ).grid(row=1, column=2, sticky="w", padx=8)

        # capture toggles
        ctk.CTkLabel(
            settings, text="🎯 Capturar:", font=FONT_H, text_color=ACCENT
        ).grid(row=2, column=0, padx=12, pady=(14, 4), sticky="w")

        toggles = ctk.CTkFrame(settings, fg_color="transparent")
        toggles.grid(row=2, column=1, columnspan=3, sticky="ew", padx=8)
        toggles.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.chk_text = ctk.CTkCheckBox(
            toggles, text="🔤 Texto digitado", font=FONT_BODY, text_color=TEXT,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
        )
        self.chk_text.grid(row=0, column=0, padx=(0, 12), sticky="w", pady=4)
        self.chk_text.select()

        self.chk_clicks = ctk.CTkCheckBox(
            toggles, text="🖱  Cliques (com crop)", font=FONT_BODY, text_color=TEXT,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
        )
        self.chk_clicks.grid(row=0, column=1, padx=(0, 12), sticky="w", pady=4)
        self.chk_clicks.select()

        self.chk_scroll = ctk.CTkCheckBox(
            toggles, text="🖲  Scroll da roda", font=FONT_BODY, text_color=TEXT,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
        )
        self.chk_scroll.grid(row=0, column=2, padx=(0, 12), sticky="w", pady=4)
        self.chk_scroll.select()

        self.chk_focus = ctk.CTkCheckBox(
            toggles, text="🪟 Janela em foco", font=FONT_BODY, text_color=TEXT,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
        )
        self.chk_focus.grid(row=0, column=3, padx=(0, 12), sticky="w", pady=4)
        self.chk_focus.select()

        # advanced
        adv = ctk.CTkFrame(settings, fg_color="transparent")
        adv.grid(row=3, column=0, columnspan=3, sticky="ew", padx=8, pady=(4, 12))
        adv.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(
            adv, text="Margem do crop:", font=FONT_SMALL, text_color=TEXT_DIM
        ).grid(row=0, column=0, padx=8, sticky="w")
        self.opt_margin = ctk.CTkOptionMenu(
            adv, values=["40", "60", "80", "120", "160"], width=90,
            font=FONT_SMALL, text_color=TEXT,
            fg_color=CARD, button_color=CARD_HOVER, dropdown_fg_color=CARD,
        )
        self.opt_margin.set("60")
        self.opt_margin.grid(row=0, column=1, padx=8)

        ctk.CTkLabel(
            adv, text="Confiança (matching):", font=FONT_SMALL, text_color=TEXT_DIM
        ).grid(row=0, column=2, padx=8, sticky="w")
        self.opt_conf = ctk.CTkOptionMenu(
            adv, values=["0.70", "0.80", "0.85", "0.90"], width=90,
            font=FONT_SMALL, text_color=TEXT,
            fg_color=CARD, button_color=CARD_HOVER, dropdown_fg_color=CARD,
        )
        self.opt_conf.set("0.90")
        self.opt_conf.grid(row=0, column=3, padx=8)

        # buttons: START / STOP / CANCEL
        rec_btns = ctk.CTkFrame(main, fg_color="transparent")
        rec_btns.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.btn_record = ctk.CTkButton(
            rec_btns, text="⏺  Começar a gravar",
            font=("Segoe UI", 15, "bold"), height=50,
            fg_color=DANGER, hover_color=DANGER_HOVER,
            command=self._toggle_record,
        )
        self.btn_record.pack(side="left", padx=(0, 8), fill="x", expand=True)
        self.btn_stop = ctk.CTkButton(
            rec_btns, text="⏹  Parar e salvar",
            font=("Segoe UI", 15, "bold"), height=50,
            fg_color=WARN, hover_color="#d97706",
            command=self._stop_record,
            state="disabled",
        )
        self.btn_stop.pack(side="left", padx=(0, 8), fill="x", expand=True)
        self.btn_cancel = ctk.CTkButton(
            rec_btns, text="✕ Cancelar", font=FONT_BODY, height=50,
            fg_color=CARD, hover_color=CARD_HOVER,
            command=self._cancel_record, width=140,
        )
        self.btn_cancel.pack(side="left", padx=(8, 0))

        # hint
        ctk.CTkLabel(
            main,
            text="Ao gravar: aperte o hotkey (F9) para LIGAR, faça a tarefa, "
                 "aperte de novo para PARAR. Jogue o mouse no canto "
                 "superior-esquerdo (FailSafe) para abortar à força.",
            font=FONT_SMALL, text_color=TEXT_DIM, justify="left", wraplength=820,
        ).grid(row=3, column=0, sticky="ew", padx=4, pady=(0, 6))

        # console
        cons = ctk.CTkFrame(main, fg_color=CONSOLE_BG, corner_radius=10)
        cons.grid(row=4, column=0, sticky="nsew", pady=(0, 4))
        cons.grid_columnconfigure(0, weight=1)
        cons.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            cons, text="📟 Console", font=FONT_H, text_color=TEXT_DIM
        ).grid(row=0, column=0, padx=12, pady=(8, 0), sticky="w")
        self.console = ctk.CTkTextbox(
            cons, font=FONT_MONO, fg_color=CONSOLE_BG,
            text_color=CONSOLE_FG, wrap="word",
        )
        self.console.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 10))
        self.console.configure(state="disabled")

        self._log("[init] Macro Recorder GUI carregado.")
        self._log(f"[init] venv: {sys.executable}")

    # ───────────────────────── ABABA: REPLAY ────────────────────────────
    def _build_replay_tab(self, parent):
        main = ctk.CTkFrame(parent, fg_color="transparent")
        main.grid(sticky="nsew", padx=8, pady=8)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)

        # dropdown
        row = ctk.CTkFrame(main, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", pady=(4, 8))
        row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            row, text="📦 Gravação:", font=FONT_BODY, text_color=TEXT
        ).grid(row=0, column=0, padx=12, pady=12, sticky="w")
        self.combo_rec = ctk.CTkOptionMenu(
            row, values=["(nenhuma gravação)"], font=FONT_BODY, text_color=TEXT,
            fg_color=CARD, button_color=CARD_HOVER, dropdown_fg_color=CARD,
            width=420,
        )
        self.combo_rec.grid(row=0, column=1, padx=8, pady=12, sticky="ew")
        ctk.CTkButton(
            row, text="🔄", width=44, font=FONT_BODY, fg_color=CARD,
            hover_color=CARD_HOVER, command=self._refresh_recordings,
        ).grid(row=0, column=2, padx=8, pady=12)

        # options
        opts = ctk.CTkFrame(main, fg_color="transparent")
        opts.grid(row=1, column=0, sticky="ew", pady=8)
        ctk.CTkLabel(
            opts, text="⚙️  Comportamento:", font=FONT_H, text_color=ACCENT
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(8, 4), sticky="w")
        self.chk_dry = ctk.CTkCheckBox(
            opts, text="🐍 Dry-run (não executa, só mostra o que faria)",
            font=FONT_BODY, text_color=TEXT,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
        )
        self.chk_dry.grid(row=1, column=0, columnspan=2, padx=12, pady=2, sticky="w")
        self.chk_pause = ctk.CTkCheckBox(
            opts, text="⏸ Pausar 1s entre passos (facilita acompanhar)",
            font=FONT_BODY, text_color=TEXT,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
        )
        self.chk_pause.select()
        self.chk_pause.grid(row=2, column=0, columnspan=2, padx=12, pady=2, sticky="w")

        # buttons
        btns = ctk.CTkFrame(main, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="ew", pady=10)
        self.btn_replay = ctk.CTkButton(
            btns, text="▶  Reproduzir", font=("Segoe UI", 15, "bold"),
            height=50, fg_color=SUCCESS, hover_color=SUCCESS_HOVER,
            command=self._run_replay,
        )
        self.btn_replay.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            btns, text="📂 Abrir pasta", font=FONT_BODY, height=50, width=160,
            fg_color=CARD, hover_color=CARD_HOVER,
            command=self._open_recording_folder,
        ).pack(side="left", padx=(8, 0))

        # replay console
        cons = ctk.CTkFrame(main, fg_color=CONSOLE_BG, corner_radius=10)
        cons.grid(row=3, column=0, sticky="nsew", pady=(4, 4))
        cons.grid_columnconfigure(0, weight=1)
        cons.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            cons, text="📟 Console replay", font=FONT_H, text_color=TEXT_DIM
        ).grid(row=0, column=0, padx=12, pady=(8, 0), sticky="w")
        self.replay_console = ctk.CTkTextbox(
            cons, font=FONT_MONO, fg_color=CONSOLE_BG,
            text_color=CONSOLE_FG, wrap="word",
        )
        self.replay_console.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 10))
        self.replay_console.configure(state="disabled")

        self._refresh_recordings()

    # ───────────────────────── HANDLERS: RECORD (in-process) ────────────
    def _toggle_record(self):
        if self._rec_worker is not None and self._rec_worker.is_alive():
            self._log("⚠  Já existe uma gravação em curso. Aguarde o F9/Cancelar.")
            return

        from macro_recorder.listener import Recorder

        out_dir_txt = (self.entry_out.get().strip() or "recordings")
        hotkey = (self.entry_hotkey.get().strip().lower() or "f9")
        cap_text = bool(self.chk_text.get())
        cap_clicks = bool(self.chk_clicks.get())
        cap_scroll = bool(self.chk_scroll.get())
        cap_focus = bool(self.chk_focus.get())

        if not (cap_text or cap_clicks or cap_scroll):
            from tkinter import messagebox
            messagebox.showwarning(
                "Macro Recorder", "Nenhum recurso selecionado — nada vai ser gravado."
            )
            return

        out_root = Path(out_dir_txt)
        if not out_root.is_absolute():
            out_root = Path.cwd() / out_root
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_dir = out_root / ts
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "assets").mkdir(exist_ok=True)

        self._log("─" * 60)
        self._log(
            f"[record] hotkey={hotkey}  out={out_dir}  "
            f"texto={cap_text} cliques={cap_clicks} scroll={cap_scroll} foco={cap_focus}"
        )
        self._emit_status("waiting")

        def on_state(is_rec):
            # callback thread-safe do collector -> fila -> mainloop
            self._emit_status("recording" if is_rec else "stopping")
            self._emit_log("[record] >>> GRAVANDO..." if is_rec
                           else "[record] <<< PARADO.  Salvando artefatos...")

        def worker():
            code = 1
            try:
                rec = Recorder(
                    out_dir=out_dir,
                    hotkey=hotkey,
                    capture_text=cap_text,
                    capture_clicks=cap_clicks,
                    capture_scroll=cap_scroll,
                    capture_focus=cap_focus,
                    on_state_change=on_state,
                )
                self._rec = rec  # exposto p/ botão PARAR + E2E (toggle programático)
                recording = rec.run()
                import json
                (out_dir / "recording.json").write_text(
                    json.dumps(recording.to_dict(), indent=2), encoding="utf-8"
                )
                from macro_recorder import exporter_md as md
                from macro_recorder import exporter_py as pyexp
                steps = recording.steps
                md.export_md(recording, steps, out_dir / "passo-a-passo.md")
                pyexp.export_py(steps, out_dir / "replay.py")
                crops = sum(1 for s in steps if s.crop)
                self._emit_log(f"[record] ✅ {len(steps)} passos salvos em {out_dir}/")
                self._emit_log(
                    f"[record]   recording.json + passo-a-passo.md + replay.py "
                    f"+ assets/ ({crops} crops)"
                )
                self._emit_log(f"[record] ▶  Testar: aba ▶ Replay → {ts} → ▶ Reproduzir")
                code = 0
            except KeyboardInterrupt:
                import shutil
                shutil.rmtree(out_dir, ignore_errors=True)
                self._emit_status("idle")
                self._emit_log("[record] Cancelado (Ctrl+C). Pasta removida.")
            except Exception as e:
                import traceback
                self._emit_log("[record] ERRO: " + repr(e))
                self._emit_log(traceback.format_exc().replace("\n", " | "))
            self._emit_finish("record", code)

        self._rec_worker = threading.Thread(target=worker, daemon=True)
        self._rec_worker.start()
        self.btn_record.configure(state="disabled")
        self.btn_stop.configure(state="normal")

    def _record_finished(self, code: int):
        self.btn_record.configure(
            text="⏺  Começar a gravar", fg_color=DANGER, hover_color=DANGER_HOVER,
            state="normal",
        )
        self.btn_stop.configure(state="disabled")
        self._log(
            "[record] finalizado com sucesso (code=0)." if code == 0
            else f"[record] finalizado com código {code}."
        )
        self._emit_status("done" if code == 0 else "idle")
        self._refresh_recordings()

    def _stop_record(self):
        """Para a gravação e salva os artefatos (toggle programático)."""
        rec = getattr(self, "_rec", None)
        if rec is not None:
            self._log("[record] Parando gravação (botão ⏹)...")
            rec.toggle()
        else:
            self._log("⚠  Nenhuma gravação em curso.")

    def _cancel_record(self):
        self._log(
            "[record] Para parar: aperte o hotkey de novo "
            "(ou jogue o mouse no canto superior esquerdo p/ abortar)."
        )

    def _pick_out_dir(self):
        import tkinter.filedialog as fd
        p = fd.askdirectory(title="Pasta de saída das gravações")
        if p:
            self.entry_out.delete(0, "end")
            self.entry_out.insert(0, p)

    # ───────────────────────── HANDLERS: REPLAY (subprocess) ────────────
    def _refresh_recordings(self):
        recs = _list_recordings(self.recordings_dir)
        values = recs or ["(nenhuma gravação)"]
        self.combo_rec.configure(values=values)
        self.combo_rec.set(values[0])

    def _run_replay(self):
        sel = self.combo_rec.get()
        if sel == "(nenhuma gravação)":
            from tkinter import messagebox
            messagebox.showinfo(
                "Macro Recorder",
                "Nenhuma gravação encontrada.\nGrave algo primeiro na aba 🎥 Record.",
            )
            return

        rec_dir = self.recordings_dir / sel
        dry = bool(self.chk_dry.get())
        self._log("─" * 60)
        self._log(f"[replay] {sel}  dry-run={dry}")
        self.btn_replay.configure(text="⏳  Reproduzindo...", state="disabled")

        env = os.environ.copy()
        args = [sys.executable, "-m", "macro_recorder", "replay", str(rec_dir)]
        if dry:
            args.append("--dry-run")

        def pump():
            code = 1
            try:
                p = subprocess.Popen(
                    args, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, cwd=str(self.project_root), text=True,
                )
                for line in p.stdout:
                    line = line.rstrip("\n")
                    if line:
                        self._emit_rlog(line)
                p.wait()
                code = p.returncode
            except Exception as e:
                self._emit_rlog("erro: " + repr(e))
            self._emit_finish("replay", code)

        threading.Thread(target=pump, daemon=True).start()

    def _replay_finished(self, code: int):
        self.btn_replay.configure(text="▶  Reproduzir", state="normal")
        self._rlog(f"[replay] finalizado (code={code}).")

    def _open_recording_folder(self):
        sel = self.combo_rec.get()
        if sel == "(nenhuma gravação)":
            return
        p = str(self.recordings_dir / sel)
        if sys.platform == "win32":
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", p])
        else:
            subprocess.run(["xdg-open", p])

    # ───────────────────────── STATUS ───────────────────────────────────
    def _set_status(self, state: str, text: str):
        self.status_lbl.configure(text=text)
        if state == "recording":
            self._blink_phase = 0
            self._blink_tick()
        else:
            colors = {
                "idle": TEXT_DIM,
                "waiting": WARN,
                "stopping": WARN,
                "done": SUCCESS,
            }
            self.status_lbl.configure(text_color=colors.get(state, TEXT))

    def _blink_tick(self):
        self._blink_phase = (self._blink_phase + 1) % 2
        if self._blink_phase == 0:
            self.status_lbl.configure(text="●  GRAVANDO...", text_color=DANGER)
        else:
            self.status_lbl.configure(text="   GRAVANDO...", text_color=DANGER)
        self.after(500, self._blink_tick)


def main():
    import macro_recorder  # noqa: F401
    app = MacroRecorderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
