"""MIRANA — ovladacie okno. Spusti sa z ikony na ploche (pythonw, bez konzoly).

Okno Miranu spusti (run.py -> main.py) a pripoji sa na jej WebSocket ako dalsi klient HUD-u:
dostava stav, odpovede, Erikove otazky a utratu. Prikazy (stlmit, vypnut) posiela tym istym
spojenim; main.py ich prijima len z tohto PC. Zatvorenie okna Miranu vypne.
"""

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser

import customtkinter as ctk
from websockets.sync.client import connect

from core.config import BASE_DIR, load_config
from inputs.ptt import key_label
from core.session import LOGS_DIR

YELLOW, CYAN, RED, DIM = "#FCEE0A", "#00F0FF", "#FF003C", "#7d7d85"
BG, PANEL, TEXT = "#0a0a0c", "#141418", "#e6e6e6"
STATES = {
    "offline": ("OFFLINE", DIM),
    "starting": ("ŠTARTUJE…", DIM),
    "stopping": ("VYPÍNA SA…", DIM),
    "idle": ("STANDBY", YELLOW),
    "listening": ("POČÚVAM", CYAN),
    "processing": ("SPRACOVÁVAM", YELLOW),
    "speaking": ("HOVORÍ", YELLOW),
    "muted": ("STLMENÁ", RED),
}
STARTUP_TIMEOUT_SEC = 180  # nacitanie Whispera; pri vytazenom disku (napr. Steam stahuje) aj minutu


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.port = load_config()["overlay"]["port"]
        self.proc: subprocess.Popen | None = None  # supervisor, ak sme ho spustili z okna
        self.ws = None
        self.connected = False
        self.starting_since: float | None = None
        self.events: queue.Queue = queue.Queue()
        self.mirana_line_open = False
        self.restart_pending = False
        self.settings_window = None

        self.title("MIRANA")
        self.geometry("560x620")
        self.minsize(480, 480)
        self.configure(fg_color=BG)
        try:
            self.iconbitmap(str(BASE_DIR / "assets" / "mirana.ico"))
        except Exception:
            pass
        self._build()
        self._set_status("offline")

        threading.Thread(target=self._ws_loop, name="ws", daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._pump)
        self.after(1500, self._autostart)  # ak uz bezi (napr. zo start.bat), len sa pripoji

    # --- UI -----------------------------------------------------------------------------------

    def _build(self) -> None:
        head = ctk.CTkFrame(self, fg_color=BG)
        head.pack(fill="x", padx=18, pady=(16, 6))
        ctk.CTkLabel(head, text="MIRANA", font=ctk.CTkFont("Segoe UI", 26, "bold"), text_color=YELLOW).pack(side="left")
        self.status = ctk.CTkLabel(head, text="", font=ctk.CTkFont("Segoe UI", 13, "bold"))
        self.status.pack(side="right")

        self.info = ctk.CTkLabel(self, text="", font=ctk.CTkFont("Segoe UI", 12), text_color=DIM, anchor="w")
        self.info.pack(fill="x", padx=20)
        self.game_label = ctk.CTkLabel(self, text="Hra: čakám na údaje", font=ctk.CTkFont("Segoe UI", 12),
                                       text_color=DIM, anchor="w", wraplength=520, justify="left")
        self.game_label.pack(fill="x", padx=20)
        self.chat_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont("Segoe UI", 12), text_color=DIM, anchor="w")
        self.chat_label.pack(fill="x", padx=20)

        buttons = ctk.CTkFrame(self, fg_color=BG)
        buttons.pack(fill="x", padx=16, pady=10)
        style = dict(height=36, corner_radius=4, font=ctk.CTkFont("Segoe UI", 13, "bold"))
        self.btn_power = ctk.CTkButton(buttons, text="Spustiť", command=self._toggle_power, width=120,
                                       fg_color=YELLOW, hover_color="#d9cc08", text_color="#000", **style)
        self.btn_power.pack(side="left", padx=4)
        self.btn_mute = ctk.CTkButton(buttons, text="Stlmiť", command=lambda: self._send("mute"), width=120,
                                      fg_color=PANEL, hover_color="#26262c", border_width=1, border_color=RED, **style)
        self.btn_mute.pack(side="left", padx=4)
        for label, cmd in (("HUD", self._open_hud), ("Logy", lambda: os.startfile(LOGS_DIR)),
                           ("Nastavenia", self._open_settings)):
            ctk.CTkButton(buttons, text=label, command=cmd, width=80, fg_color=PANEL, hover_color="#26262c",
                          border_width=1, border_color="#33333a", **style).pack(side="left", padx=4)

        vol = ctk.CTkFrame(self, fg_color=BG)
        vol.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(vol, text="Hlasitosť Mirany", font=ctk.CTkFont("Segoe UI", 12), text_color=TEXT).pack(side="left")
        self.volume = int(load_config()["audio"].get("volume", 100))
        self.volume_label = ctk.CTkLabel(vol, text=f"{self.volume} %", width=50, font=ctk.CTkFont("Segoe UI", 12),
                                         text_color=TEXT)
        self.volume_label.pack(side="right")
        self.volume_slider = ctk.CTkSlider(vol, from_=0, to=150, number_of_steps=30, command=self._on_volume,
                                           button_color=YELLOW, button_hover_color="#d9cc08", progress_color=YELLOW)
        self.volume_slider.set(self.volume)
        self.volume_slider.pack(side="left", fill="x", expand=True, padx=10)
        self.volume_slider.bind("<ButtonRelease-1>", lambda _e: self._save_volume())

        budget = ctk.CTkFrame(self, fg_color=BG)
        budget.pack(fill="x", padx=20, pady=(4, 8))
        self.budget_label = ctk.CTkLabel(budget, text="Dnes: —", font=ctk.CTkFont("Segoe UI", 12), text_color=TEXT)
        self.budget_label.pack(anchor="w")
        self.budget_bar = ctk.CTkProgressBar(budget, height=6, progress_color=YELLOW, fg_color=PANEL)
        self.budget_bar.pack(fill="x", pady=(4, 0))
        self.budget_bar.set(0)

        self.log = ctk.CTkTextbox(self, fg_color=PANEL, text_color=TEXT, font=ctk.CTkFont("Segoe UI", 13),
                                  wrap="word", corner_radius=4, border_width=0)
        self.log.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        for tag, color in (("erik", CYAN), ("mirana", YELLOW), ("sys", DIM), ("chat", "#a970ff")):
            self.log.tag_config(tag, foreground=color)
        self.log.configure(state="disabled")

        ask = ctk.CTkFrame(self, fg_color=BG)
        ask.pack(fill="x", padx=16, pady=(0, 6))
        self.text_entry = ctk.CTkEntry(ask, placeholder_text="Napíš Mirane… (Enter = poslať)", height=34,
                                       font=ctk.CTkFont("Segoe UI", 13), fg_color=PANEL, border_color="#2a2a30")
        self.text_entry.pack(side="left", fill="x", expand=True)
        self.text_entry.bind("<Return>", self._send_text)
        ctk.CTkButton(ask, text="Poslať", width=90, height=34, command=self._send_text, fg_color=YELLOW,
                      text_color="#000", hover_color="#c9bd00").pack(side="left", padx=(6, 0))

        self.keys_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont("Segoe UI", 11), text_color=DIM, wraplength=520)
        self.keys_label.pack(pady=(0, 10))
        self._show_keys()

    def _show_keys(self) -> None:
        audio = load_config()["audio"]
        ptt, self.panic_label = key_label(audio["ptt_key"]), key_label(audio.get("panic_mute_key"))
        marker = f"  ·  Značka na strih: {key_label(audio['marker_key'])}" if audio.get("marker_key") else ""
        self.keys_label.configure(text=f"Otázka: drž {ptt} (počas odpovede ju preruší)  ·  Stlmiť: {self.panic_label}{marker}")

    def _write(self, text: str, tag: str, newline: bool = True) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", ("\n" if newline and self.log.get("1.0", "end").strip() else "") + text, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, state: str) -> None:
        label, color = STATES.get(state, (state.upper(), DIM))
        self.status.configure(text="● " + label, text_color=color)
        running = state not in ("offline",)
        self.btn_power.configure(text="Vypnúť" if running else "Spustiť",
                                 state="disabled" if state in ("starting", "stopping") else "normal")
        self.btn_mute.configure(text="Zapnúť hlas" if state == "muted" else "Stlmiť",
                                state="normal" if self.connected else "disabled")

    # --- akcie --------------------------------------------------------------------------------

    def _autostart(self) -> None:
        if not self.connected and self.proc is None:
            self._start()

    def _toggle_power(self) -> None:
        if self.connected or self.proc is not None:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen([sys.executable, str(BASE_DIR / "run.py")], cwd=BASE_DIR, creationflags=flags,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.starting_since = time.time()
        self._set_status("starting")
        self._write("Spúšťam Miranu…", "sys")

    def _stop(self, wait: bool = False) -> None:
        self._set_status("stopping")
        self._send("quit")
        proc = self.proc
        if wait:
            deadline = time.time() + 35  # pri vypnuti sa uklada pamat (zhrnutie modelom, max ~25 s)
            while proc is not None and proc.poll() is None and time.time() < deadline:
                time.sleep(0.2)
            self._kill_tree(proc)
        else:
            # ak by nereagovala, zabi supervisor aj Miranu — prave tento proces, nie novy po restarte
            self.after(35000, lambda: self._kill_tree(proc))

    def _kill_tree(self, proc: subprocess.Popen | None = None) -> None:
        proc = proc if proc is not None else self.proc
        if proc is not None and proc.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
        if proc is self.proc:
            self.proc = None
        if not self.connected and self.proc is None:
            self._set_status("offline")

    def _open_settings(self) -> None:
        from gui_settings import SettingsWindow

        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.focus_force()
            return
        self.settings_window = SettingsWindow(self)

    def on_settings_saved(self, restart: bool) -> None:
        self.port = load_config()["overlay"]["port"]
        self._show_keys()
        running = self.connected or (self.proc is not None and self.proc.poll() is None)
        if restart and running:
            self._write("Nastavenia uložené, reštartujem Miranu…", "sys")
            self.restart_pending = True
            self._stop()
        elif restart:
            self._write("Nastavenia uložené.", "sys")
            self._start()
        else:
            self._write("Nastavenia uložené. Prejavia sa po reštarte Mirany.", "sys")

    def _send(self, cmd: str, **extra) -> bool:
        ws = self.ws
        if ws is None:
            return False
        try:
            ws.send(json.dumps({"type": "command", "cmd": cmd, **extra}))
            return True
        except Exception:
            return False

    def _on_volume(self, value: float) -> None:
        """Posuvnik: Mirana zmeni hlasitost hned (aj uprostred vety), do configu sa zapise po pusteni."""
        self.volume = int(round(value))
        self.volume_label.configure(text=f"{self.volume} %")
        self._send("volume", text=str(self.volume))

    def _save_volume(self) -> None:
        try:
            from core import settings
            cfg = settings.load_editable()
            if cfg["audio"].get("volume") != self.volume:
                cfg["audio"]["volume"] = self.volume
                settings.save(cfg)
        except Exception as e:
            self._write(f"Hlasitosť sa neuložila: {e}", "sys")

    def _send_text(self, _event=None) -> str:
        text = self.text_entry.get().strip()
        if not text:
            return "break"
        if not self.connected or not self._send("ask", text=text):
            self._write("Mirana nebeží — otázka sa neposlala.", "sys")
            return "break"
        self.text_entry.delete(0, "end")
        return "break"

    def _open_hud(self) -> None:
        webbrowser.open(f"http://localhost:{self.port}")

    def _on_close(self) -> None:
        if self.connected or self.proc is not None:
            self._stop(wait=True)
        self.destroy()

    # --- spojenie s Miranou -------------------------------------------------------------------

    def _ws_loop(self) -> None:
        while True:
            try:
                with connect(f"ws://127.0.0.1:{self.port}/ws", open_timeout=2) as ws:
                    self.ws = ws
                    self.events.put(("connected", None))
                    for message in ws:
                        self.events.put(("msg", json.loads(message)))
            except Exception:
                pass
            if self.ws is not None:
                self.ws = None
                self.events.put(("disconnected", None))
            time.sleep(1)

    def _pump(self) -> None:
        """Udalosti z WebSocket vlakna do UI (Tk sa smie volat len z hlavneho vlakna)."""
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "connected":
                    self.connected, self.starting_since = True, None
                    self._write("Mirana beží.", "sys")
                    self._set_status("idle")  # skutocny stav hned prepise udalost "state" zo servera
                elif kind == "disconnected":
                    self.connected = False
                    self._write("Mirana vypnutá.", "sys")
                    self._set_status("starting" if self.proc is not None and self.proc.poll() is None else "offline")
                else:
                    self._on_event(data)
        except queue.Empty:
            pass
        if self.starting_since and time.time() - self.starting_since > STARTUP_TIMEOUT_SEC:
            self.starting_since = None
            self._write("Mirana sa nespustila — pozri Logy.", "sys")
            self._kill_tree()
        if self.proc is not None and self.proc.poll() is not None and not self.connected:
            self.proc = None
            self._set_status("offline")
        if self.restart_pending and not self.connected and (self.proc is None or self.proc.poll() is not None):
            self.restart_pending = False
            self.proc = None
            self._start()
        self.after(100, self._pump)

    def _on_event(self, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "state":
            self._set_status(ev["state"])
            if ev["state"] != "speaking":
                self.mirana_line_open = False
        elif kind == "erik":
            self._write("Ty: " + ev["text"], "erik")
            self.mirana_line_open = False
        elif kind == "answer_start":
            self._write("Mirana: ", "mirana")
            self.mirana_line_open = True
        elif kind == "answer_append":
            if not self.mirana_line_open:
                self._write("Mirana: ", "mirana")
                self.mirana_line_open = True
            self._write(ev["text"] + " ", "mirana", newline=False)
        elif kind == "question":  # systemova hlaska, napr. vypadok hlasu
            self._write(ev["text"], "sys")
        elif kind == "budget":
            spent, cap = ev["spent"], ev["cap"]
            self.budget_label.configure(text=f"Dnes minuté: ${spent:.2f} z ${cap:.2f}")
            self.budget_bar.set(min(1.0, spent / cap) if cap else 0)
            self.budget_bar.configure(progress_color=RED if spent >= cap * 0.8 else YELLOW)
        elif kind == "game":
            if ev.get("live"):
                line = (ev.get("line") or "").removeprefix("[HRA] ")
                self.game_label.configure(text="Hra: " + line, text_color=CYAN)
            else:
                self.game_label.configure(text="Hra: nebeží (alebo menu) — Mirana ide bez telemetrie", text_color=DIM)
        elif kind == "chat":
            pass  # spravy z chatu sa v okne nevypisuju (Mirana ich vidi aj tak), len stav pripojenia
        elif kind == "notice":
            self._write(ev["text"], "sys")
            self.mirana_line_open = False
        elif kind == "chat_status":
            self.chat_label.configure(text=ev["text"].capitalize(),
                                      text_color="#a970ff" if "pripojený" in ev["text"] and "odpojený" not in ev["text"] else DIM)
        elif kind == "info":
            self.info.configure(text=f"Model: {ev.get('model')}  ·  effort {ev.get('effort')}  ·  HUD http://localhost:{self.port}")


if __name__ == "__main__":
    if sys.platform == "win32":
        # vlastna ikona na paneli uloh (inak by Windows ukazal ikonu Pythonu)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mirana.control")
    ctk.set_appearance_mode("dark")
    App().mainloop()
