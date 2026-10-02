"""Okno Nastavenia ovladacieho okna (ui/control.py): vsetko z config.yaml + persona.md, bez rucneho editovania suborov.

Policka sa skladaju z mirana/schema.py (popis, rozsah, typ); vlastne casti okna (zariadenia a testy
zvuku, ukazka hlasu, mod hry, test HUD, pamat, persona) su metody _block_<nazov>. Ukladaju sa len
zmenene hodnoty — komentare a format config.yaml ostavaju.

Zmeny sa prejavia po restarte Mirany (vacsina nastaveni sa cita pri starte) — tlacidlo
"Ulozit a restartovat" to spravi. Zmena hlasu, rychlosti, vysky alebo fillerov zmaze stare
fillers/*.wav, aby sa pri starte vygenerovali novym hlasom.
"""

import copy
import json
import re
import threading
import tkinter.messagebox as messagebox

import customtkinter as ctk
import numpy as np
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from mirana import schema, settings
from mirana.config import BASE_DIR, load_config
from mirana.store import read_json, write_json

YELLOW, CYAN, RED, DIM = "#FCEE0A", "#00F0FF", "#FF003C", "#7d7d85"
BG, PANEL, TEXT = "#0a0a0c", "#141418", "#e6e6e6"

SAMPLE = "Ahoj Emzo, takto znie môj hlas. Johnny Silverhand ťa čaká v Night City. Tak poďme na to."
MIC_DEFAULT = "(predvolený mikrofón Windows)"
STREAM_OFF = "(vypnutý)"
STREAM_DEFAULT = "(predvolený výstup Windows)"
VOICE_KEYS = ("tts.voice", "tts.rate", "tts.pitch", "tts.phonetics_file")
HUD_TESTS = [("Odpoveď", "answer"), ("Databáza", "db"), ("Sken obrazovky", "scan"), ("Level", "level"),
             ("Quest", "quest"), ("Smrť", "death"), ("Polícia", "police"), ("Kritické HP", "critical")]


def _put(section, key: str, value) -> None:
    """Zapise len zmenenu hodnotu — nezmenene ostanu v configu doslova (5.00, uvodzovky, komentare)."""
    old = section.get(key)
    if isinstance(value, list):
        if old is not None and list(old) == value:
            return
        quoted = [DoubleQuotedScalarString(x) for x in value]
        if old is not None and hasattr(old, "__setitem__"):
            old[:] = quoted
        else:
            section[key] = quoted
        return
    if old != value:
        section[key] = value


def _put_path(tree, key: str, value) -> None:
    *path, last = key.split(".")
    node = tree
    for part in path:
        if not isinstance(node.get(part), dict):
            node[part] = CommentedMap()
        node = node[part]
    _put(node, last, value)


def _pct(value) -> int:
    try:
        return int(str(value).replace("%", "").replace("+", ""))
    except ValueError:
        return 0


def _audio_devices(kind: str, show_all: bool) -> list[str]:
    """Zariadenia v tvare 'nazov, hostapi' (ako v config.yaml). Standardne len WASAPI."""
    import sounddevice as sd

    apis = sd.query_hostapis()
    out = []
    for dev in sd.query_devices():
        channels = dev["max_input_channels"] if kind == "input" else dev["max_output_channels"]
        api = apis[dev["hostapi"]]["name"]
        if channels > 0 and (show_all or api == "Windows WASAPI"):
            out.append(f"{dev['name']}, {api}")
    return out


# zobrazenie zariadeni v combo <-> hodnota v configu
DEVICE_SHOW = {
    "device_in": lambda v: v or MIC_DEFAULT,
    "device_out": lambda v: STREAM_DEFAULT if not v or str(v).lower() == "default" else str(v),
    "device_stream": lambda v: STREAM_OFF if not v else STREAM_DEFAULT if str(v).lower() == "default" else str(v),
}
DEVICE_VALUE = {
    "device_in": lambda t: None if not t.strip() or t == MIC_DEFAULT else t,
    "device_out": lambda t: "default" if not t.strip() or t == STREAM_DEFAULT else t,
    "device_stream": lambda t: None if not t.strip() or t == STREAM_OFF else "default" if t == STREAM_DEFAULT else t,
}


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("MIRANA — Nastavenia")
        self.geometry("720x640")
        self.minsize(640, 560)
        self.configure(fg_color=BG)
        self.transient(app)
        self.after(150, self.focus_force)
        try:
            self.after(200, lambda: self.iconbitmap(str(BASE_DIR / "assets" / "mirana.ico")))
        except Exception:
            pass

        self.cfg = settings.load_editable()              # strom s komentarmi — sem sa zapisuje
        self.current = load_config()                     # uplny config (aj predvolene hodnoty) — odtial sa cita
        self.persona_original = settings.load_persona()
        self.fields: dict[str, tuple] = {}               # kluc -> (nastavenie, funkcia vracajuca hodnotu z okna)
        self.vars: dict[str, ctk.Variable] = {}

        self.hint = None
        self.tabs = tabs = ctk.CTkTabview(self, fg_color=PANEL, segmented_button_selected_color="#8a8200",
                                          segmented_button_selected_hover_color="#a39a00")
        tabs.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        bar = ctk.CTkFrame(self, fg_color=BG)
        self.hint = ctk.CTkLabel(bar, text="Zmeny sa prejavia po reštarte Mirany.", text_color=DIM)
        for name in schema.TABS:
            tab = tabs.add(name)
            for item in schema.SETTINGS:
                if item.tab != name:
                    continue
                if isinstance(item, schema.Block):
                    getattr(self, f"_block_{item.name}")(tab)
                elif item.label:
                    self._field(tab, item)

        bar.pack(fill="x", padx=12, pady=(4, 12))
        self.hint.pack(side="left", padx=6)
        btn = dict(height=34, corner_radius=4, font=ctk.CTkFont("Segoe UI", 13, "bold"))
        ctk.CTkButton(bar, text="Zrušiť", width=90, fg_color=PANEL, hover_color="#26262c", command=self.destroy,
                      **btn).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="Uložiť", width=90, fg_color=PANEL, hover_color="#26262c", border_width=1,
                      border_color=YELLOW, command=lambda: self._save(restart=False), **btn).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="Uložiť a reštartovať", width=170, fg_color=YELLOW, hover_color="#d9cc08",
                      text_color="#000", command=lambda: self._save(restart=True), **btn).pack(side="right", padx=4)

    # --- stavebne bloky -----------------------------------------------------------------------

    def _row(self, parent, label: str, hint: str = ""):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(row, text=label, width=170, anchor="w", text_color=TEXT).pack(side="left")
        if hint:
            ctk.CTkLabel(parent, text=hint, text_color=DIM, anchor="w", font=ctk.CTkFont("Segoe UI", 11),
                         wraplength=470, justify="left").pack(fill="x", padx=(190, 12), pady=(0, 2))
        return row

    def _textbox(self, parent, text: str, height: int):
        box = ctk.CTkTextbox(parent, height=height, fg_color=BG, font=ctk.CTkFont("Consolas", 12), wrap="word")
        box.pack(fill="both", expand=True, padx=10, pady=5)
        box.insert("1.0", text)
        return box

    def _field(self, parent, s: schema.S) -> None:
        """Policko podla schemy; do self.fields ulozi funkciu, ktora vrati hodnotu pre config."""
        value = schema.get(self.current, s.key, s.default)
        kind = s.type
        widget = s.widget or {"bool": "switch", "flag": "switch", "choice": "combo", "list": "lines",
                              "percent": "slider", "key": "key"}.get(kind, "entry")
        hint = s.hint

        if widget == "switch":
            var = ctk.BooleanVar(value=value == s.on if kind == "flag" else bool(value))
            ctk.CTkSwitch(self._row(parent, s.label, hint), text="", variable=var, progress_color=YELLOW).pack(side="left")
            get = (lambda: s.on if var.get() else None) if kind == "flag" else var.get
        elif widget == "slider":
            start = _pct(value) if kind == "percent" else int(value)
            var = ctk.IntVar(value=start)
            row = self._row(parent, s.label, hint)
            shown = ctk.CTkLabel(row, text=s.fmt.format(start), width=70)
            lo, hi = int(s.lo), int(s.hi)
            ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=hi - lo, variable=var, width=300, button_color=YELLOW,
                          progress_color=YELLOW, command=lambda v: shown.configure(text=s.fmt.format(int(v)))).pack(side="left")
            shown.pack(side="left", padx=8)
            get = (lambda: f"{var.get():+d}%".replace("+0%", "0%")) if kind == "percent" else var.get
        elif widget == "segmented":
            var = ctk.StringVar(value=str(value))
            ctk.CTkSegmentedButton(self._row(parent, s.label, hint), values=list(s.choices), variable=var,
                                   selected_color="#8a8200").pack(side="left")
            get = var.get
        elif widget == "lines":
            ctk.CTkLabel(parent, text=s.label + ":", text_color=TEXT, anchor="w").pack(fill="x", padx=10, pady=(8, 0))
            if hint:
                ctk.CTkLabel(parent, text=hint, text_color=DIM, anchor="w").pack(fill="x", padx=10)
            box = self._textbox(parent, "\n".join(value or []), 90)
            get = lambda: [(ln.strip().lower() if s.lower else ln.strip())
                           for ln in box.get("1.0", "end").splitlines() if ln.strip()]
        elif widget == "checks":
            ctk.CTkLabel(parent, text=s.label + ":", text_color=TEXT, anchor="w").pack(fill="x", padx=10, pady=(8, 2))
            grid = ctk.CTkFrame(parent, fg_color="transparent")
            grid.pack(fill="x", padx=30)
            checks = {}
            for i, choice in enumerate(s.choices):
                checks[choice] = var = ctk.BooleanVar(value=choice in (value or []))
                ctk.CTkCheckBox(grid, text=(s.labels or {}).get(choice, choice), variable=var, fg_color=YELLOW,
                                text_color=TEXT).grid(row=i // 4, column=i % 4, sticky="w", padx=6, pady=3)
            get = lambda: [c for c, v in checks.items() if v.get()]
        elif widget in ("combo", "key") or widget in DEVICE_SHOW:
            labels = s.labels or {}
            if widget in DEVICE_SHOW:
                shown, values = DEVICE_SHOW[widget](value), []
            elif widget == "key":
                shown, values = value or "", list(schema.KEYS)
            else:
                shown = labels.get(value, "" if value is None else str(value))
                values = [labels.get(c, c) for c in (s.choices or s.suggest)]
            var = ctk.StringVar(value=shown)
            row = self._row(parent, s.label, "" if s.choice_hints else hint)
            command = None
            if s.choice_hints:
                hint_label = ctk.CTkLabel(parent, text=s.choice_hints.get(value, ""), text_color=DIM, anchor="w")
                hint_label.pack(fill="x", padx=(190, 12))
                command = lambda choice: hint_label.configure(text=s.choice_hints.get(choice, ""))
            box = ctk.CTkComboBox(row, values=values, variable=var, command=command,
                                  width=s.width or (160 if widget == "key" else 420))
            box.pack(side="left")
            if widget == "key":
                self._capture_button(row, var)
            if widget in DEVICE_SHOW:
                self.device_boxes[widget] = box
            reverse = {v: k for k, v in labels.items()}
            if widget in DEVICE_VALUE:
                get = lambda: DEVICE_VALUE[widget](var.get())
            else:
                get = lambda: (None if s.nullable and not var.get().strip()
                               else reverse.get(var.get().strip(), var.get().strip()))
        else:  # entry
            var = ctk.StringVar(value="" if value is None else str(value))
            ctk.CTkEntry(self._row(parent, s.label, hint), textvariable=var, width=s.width or 120).pack(side="left")

            def get(var=var):
                raw = var.get().strip()
                if not raw and s.nullable:
                    return None
                if kind in ("int", "float"):
                    try:
                        return (int if kind == "int" else float)(raw.replace(",", "."))
                    except ValueError:
                        raise ValueError(f"{s.label}: „{raw}“ nie je číslo") from None
                return raw
        self.fields[s.key] = (s, get)

    def value(self, key: str):
        """Aktualna hodnota policka v okne (este neulozena)."""
        return self.fields[key][1]()

    # --- zvuk -----------------------------------------------------------------------------------

    @property
    def device_boxes(self) -> dict:
        if not hasattr(self, "_device_boxes"):
            self._device_boxes = {}
        return self._device_boxes

    def _block_devices(self, tab):
        self.show_all = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(tab, text="Zobraziť všetky zariadenia (nielen WASAPI)", variable=self.show_all,
                        command=self._fill_devices, fg_color=YELLOW, text_color=DIM).pack(anchor="w", padx=190, pady=2)
        self._fill_devices()
        tests = ctk.CTkFrame(tab, fg_color="transparent")
        tests.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkButton(tests, text="Test mikrofónu (3 s)", width=160, command=self._test_mic, fg_color=PANEL,
                      border_width=1, border_color=CYAN).pack(side="left", padx=(180, 6))
        ctk.CTkButton(tests, text="Test výstupu", width=120, command=self._test_out, fg_color=PANEL,
                      border_width=1, border_color=YELLOW).pack(side="left", padx=6)
        self.mic_bar = ctk.CTkProgressBar(tab, height=8, progress_color=CYAN, fg_color=BG, width=420)
        self.mic_bar.pack(anchor="w", padx=190, pady=4)
        self.mic_bar.set(0)
        self.mic_label = ctk.CTkLabel(tab, text="", text_color=DIM)
        self.mic_label.pack(anchor="w", padx=190)

    def _fill_devices(self):
        try:
            inputs = _audio_devices("input", self.show_all.get())
            outputs = _audio_devices("output", self.show_all.get())
        except Exception as e:
            inputs, outputs = [], []
            self.hint.configure(text=f"Zariadenia sa nedajú načítať: {e}", text_color=RED)
        boxes = self.device_boxes
        boxes["device_in"].configure(values=[MIC_DEFAULT] + inputs)
        boxes["device_out"].configure(values=[STREAM_DEFAULT] + outputs)
        boxes["device_stream"].configure(values=[STREAM_OFF, STREAM_DEFAULT] + outputs)

    def _capture_button(self, row, var):
        button = ctk.CTkButton(row, text="Stlačiť…", width=80, fg_color=PANEL, border_width=1, border_color=YELLOW,
                               text_color=TEXT)
        button.configure(command=lambda: self._capture_key(var, button))
        button.pack(side="left", padx=6)

    def _capture_key(self, var, button):
        """Nasledujuci klaves alebo bocne/stredne tlacidlo mysi sa zapise do pola. Lave a prave sa ignoruju."""
        from pynput import keyboard, mouse

        button.configure(text="stlač…", state="disabled")
        listeners = []

        def done(spec):
            for listener in listeners:
                listener.stop()

            def apply():
                if spec:
                    var.set(spec)
                button.configure(text="Stlačiť…", state="normal")
            self.after(0, apply)
            return False

        def on_key(k):
            if isinstance(k, keyboard.Key):
                return done(k.name)
            if getattr(k, "char", None):
                return done(k.char.lower())
            return None

        def on_click(x, y, b, pressed):
            if pressed and b.name in ("x1", "x2", "middle"):
                return done(f"mouse_{b.name}")
            return None

        listeners += [keyboard.Listener(on_press=on_key), mouse.Listener(on_click=on_click)]
        for listener in listeners:
            listener.start()
        self.after(8000, lambda: done(None) if str(button.cget("state")) == "disabled" else None)

    def _test_mic(self):
        device = self.value("audio.input_device")
        self.mic_label.configure(text="Hovor…", text_color=CYAN)

        def run():
            import sounddevice as sd

            from mirana.outputs.voice import _ensure_com
            _ensure_com()
            try:
                rate = int(sd.query_devices(device, "input")["default_samplerate"])
                peak_all = 0
                with sd.InputStream(samplerate=rate, device=device, channels=1, dtype="int16") as stream:
                    for _ in range(30):
                        block, _ = stream.read(rate // 10)
                        peak = int(np.abs(block).max())
                        peak_all = max(peak_all, peak)
                        self.after(0, self.mic_bar.set, min(1.0, (peak / 32767) ** 0.5))
                verdict = "v poriadku" if peak_all > 3000 else ("potichu" if peak_all > 300 else "ticho — mute alebo zlé zariadenie?")
                self.after(0, lambda: self.mic_label.configure(text=f"Najvyššia úroveň {peak_all}/32767 — {verdict}",
                                                               text_color=TEXT if peak_all > 300 else RED))
            except Exception as e:
                self.after(0, lambda err=str(e): self.mic_label.configure(text=f"Chyba: {err}", text_color=RED))
            self.after(600, self.mic_bar.set, 0)

        threading.Thread(target=run, daemon=True).start()

    def _test_out(self):
        device = self.value("audio.output_device")

        def run():
            import sounddevice as sd

            from mirana.outputs.voice import _ensure_com, resolve_output
            _ensure_com()
            try:
                device_index = resolve_output(device)
                rate = int(sd.query_devices(device_index)["default_samplerate"])
                tone = (np.sin(2 * np.pi * 660 * np.arange(0, 0.4, 1 / rate)) * 0.2 * 32767).astype(np.int16)
                with sd.OutputStream(samplerate=rate, device=device_index, channels=1, dtype="int16") as stream:
                    stream.write(tone.reshape(-1, 1))
            except Exception as e:
                self.after(0, lambda err=str(e): self.hint.configure(text=f"Výstup: {err}", text_color=RED))

        threading.Thread(target=run, daemon=True).start()

    # --- hlas -----------------------------------------------------------------------------------

    def _block_voice_preview(self, tab):
        self.sample = ctk.StringVar(value=SAMPLE)
        row = self._row(tab, "Ukážka")
        ctk.CTkEntry(row, textvariable=self.sample, width=330).pack(side="left")
        ctk.CTkButton(row, text="Vypočuť", width=80, command=self._preview_voice, fg_color=YELLOW,
                      text_color="#000").pack(side="left", padx=6)

    def _preview_voice(self):
        try:
            cfg = copy.deepcopy(self.current)
            for key in ("audio.output_device", "audio.stream_output_device", "tts.voice", "tts.rate", "tts.pitch",
                        "tts.sentence_pause_ms", "tts.phonetics_file", "tts.effects.preset"):
                schema.put(cfg, key, self.value(key))
            schema.put(cfg, "tts.effects.enabled", True)
        except ValueError as e:
            self.hint.configure(text=str(e), text_color=RED)
            return
        text = self.sample.get()
        self.hint.configure(text="Syntetizujem ukážku…", text_color=DIM)

        def run():
            try:
                from mirana.outputs.voice import Voice
                voice = Voice(cfg)
                # po vetach ako pri skutocnej odpovedi, aby bolo pocut aj pauzu medzi vetami
                sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
                clips = [voice.to_device_audio(voice.synthesize(s, timeout=15)) for s in sentences]
                voice.arm()
                for clip in clips:
                    voice.play_audio(clip)
                self.after(0, lambda: self.hint.configure(text="Zmeny sa prejavia po reštarte Mirany.", text_color=DIM))
            except Exception as e:
                self.after(0, lambda err=str(e): self.hint.configure(text=f"Ukážka zlyhala: {err}", text_color=RED))

        threading.Thread(target=run, daemon=True).start()

    # --- hra --------------------------------------------------------------------------------------

    def _block_game_mod(self, tab):
        from mirana.inputs.game_state import MOD_SOURCE, MOD_SUBDIR, cet_installed, find_game_dir, mod_version

        self.game_dir = find_game_dir()
        if self.game_dir is None:
            status, color = "Cyberpunk 2077 sa nenašiel (Steam / GOG / Epic). Po inštalácii otvor nastavenia znova.", RED
        elif not cet_installed(self.game_dir):
            status, color = f"Hra: {self.game_dir}\nCyber Engine Tweaks nie je nainštalovaný — rozbaľ ho do bin\\x64.", RED
        else:
            installed, repo = mod_version(self.game_dir / MOD_SUBDIR / "init.lua"), mod_version(MOD_SOURCE / "init.lua")
            mod = f"mod mirana_state v{installed}" if installed else "mod nie je nainštalovaný"
            if installed and repo and installed < repo:
                mod += f" (nová verzia v{repo} sa nainštaluje po vypnutí hry)"
            status, color = f"Hra: {self.game_dir}\nCyber Engine Tweaks: nainštalovaný · {mod}", CYAN
        ctk.CTkLabel(tab, text=status, text_color=color, anchor="w", justify="left").pack(fill="x", padx=10, pady=(6, 2))
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=4)
        ctk.CTkButton(row, text="Nainštalovať / aktualizovať mod", width=230, fg_color=YELLOW, text_color="#000",
                      command=self._install_mod,
                      state="normal" if self.game_dir and cet_installed(self.game_dir) else "disabled").pack(side="left")
        self.mod_label = ctk.CTkLabel(row, text="", text_color=DIM)
        self.mod_label.pack(side="left", padx=10)

    def _install_mod(self):
        from mirana.inputs.game_state import install_mod

        try:
            path = install_mod(self.game_dir)
            self.mod_label.configure(text="Hotovo — po štarte hry zapisuje " + path.name, text_color=CYAN)
        except Exception as e:
            self.mod_label.configure(text=f"Chyba: {e}", text_color=RED)

    # --- HUD --------------------------------------------------------------------------------------

    def _block_hud_tests(self, tab):
        ctk.CTkLabel(tab, text="Test efektov na HUD (Mirana musí bežať; len vizuál, nič nepovie):",
                     text_color=TEXT, anchor="w").pack(fill="x", padx=10, pady=(14, 4))
        grid = ctk.CTkFrame(tab, fg_color="transparent")
        grid.pack(fill="x", padx=10)
        for i, (label, kind) in enumerate(HUD_TESTS):
            ctk.CTkButton(grid, text=label, width=150, fg_color=PANEL, border_width=1, border_color=CYAN,
                          text_color=TEXT, command=lambda k=kind: self._hud_test(k)).grid(row=i // 4, column=i % 4, padx=4, pady=4)

    def _hud_test(self, kind: str) -> None:
        if not self.app._send("hud_test", text=kind):
            self.hint.configure(text="Mirana nebeží — test HUD sa nedá spustiť.", text_color=RED)
        else:
            self.hint.configure(text="Pozri HUD (tlačidlo HUD v hlavnom okne alebo OBS).", text_color=DIM)

    # --- pamat ------------------------------------------------------------------------------------

    def _block_memory(self, tab):
        """Dlhodoba pamat (data/memory.json): fakty o Erikovi a poznamky o divakoch sa daju upravit."""
        from mirana.features.longterm import MEMORY_PATH
        mem = read_json(MEMORY_PATH, {}) or {}
        self.memory_original = mem
        game, streams = mem.get("game") or {}, [s for s in mem.get("streams") or [] if s.get("date")]
        info = []
        if game:
            info.append(f"Hra: úroveň {game.get('level', '?')}, dokončené hlavné questy {len(game.get('main_done') or [])}, "
                        f"naposledy {', '.join(x for x in (game.get('last_location'), game.get('last_quest')) if x) or '?'}")
        if streams:
            info.append(f"Streamov v pamäti: {len(streams)} (posledný {streams[-1]['date']})")
        ctk.CTkLabel(tab, text="\n".join(info) or "Pamäť je zatiaľ prázdna — naplní sa počas streamu.",
                     text_color=DIM, anchor="w", justify="left").pack(fill="x", padx=10, pady=(4, 6))
        ctk.CTkLabel(tab, text="Fakty o tebe (jeden na riadok; zmazaním riadku Mirana zabudne):", text_color=TEXT,
                     anchor="w").pack(fill="x", padx=10)
        self.facts_box = self._textbox(tab, "\n".join((mem.get("erik") or {}).get("facts") or []), 150)
        ctk.CTkLabel(tab, text="Diváci — poznámky (login: poznámka | poznámka). Štatistiky návštev ostávajú:",
                     text_color=TEXT, anchor="w").pack(fill="x", padx=10, pady=(6, 0))
        viewers = sorted((mem.get("viewers") or {}).items(), key=lambda kv: -kv[1].get("messages", 0))
        self.viewers_box = self._textbox(tab, "\n".join(f"{login}: {' | '.join(v.get('notes') or [])}" for login, v in viewers), 150)
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=4)
        ctk.CTkButton(row, text="Vymazať poznámky o divákoch", width=220, fg_color=PANEL, border_width=1,
                      border_color=RED, text_color=TEXT, command=self._clear_viewer_notes).pack(side="left")
        ctk.CTkButton(row, text="Zabudnúť všetko", width=160, fg_color=PANEL, border_width=1, border_color=RED,
                      text_color=TEXT, command=self._forget_all).pack(side="left", padx=8)
        self._forget_everything = False

    def _clear_viewer_notes(self):
        lines = [ln.split(":", 1)[0] + ": " for ln in self.viewers_box.get("1.0", "end").splitlines() if ln.strip()]
        self.viewers_box.delete("1.0", "end")
        self.viewers_box.insert("1.0", "\n".join(lines))

    def _forget_all(self):
        if messagebox.askyesno("Pamäť", "Naozaj zabudnúť všetko (fakty, divákov, streamy, postup v hre)?", parent=self):
            self._forget_everything = True
            self.facts_box.delete("1.0", "end")
            self.viewers_box.delete("1.0", "end")
            self.hint.configure(text="Pamäť sa vymaže po uložení.", text_color=RED)

    def _memory_edit(self) -> dict | None:
        """Uprava pamate z okna, alebo None, ked sa nic nezmenilo."""
        if self._forget_everything:
            return {"forget_all": True}
        facts = [ln.strip() for ln in self.facts_box.get("1.0", "end").splitlines() if ln.strip()]
        notes = {}
        for ln in self.viewers_box.get("1.0", "end").splitlines():
            if ":" in ln:
                login, _, rest = ln.partition(":")
                notes[login.strip().lower()] = [n.strip() for n in rest.split(" | ") if n.strip()]
        orig = self.memory_original
        orig_notes = {k: v.get("notes") or [] for k, v in (orig.get("viewers") or {}).items()}
        if facts == ((orig.get("erik") or {}).get("facts") or []) and all(
                notes.get(k, []) == n for k, n in orig_notes.items()):
            return None
        return {"facts": facts, "notes": notes}

    def _save_memory(self) -> None:
        """Bezaca Mirana upravu zapise sama (inak by ju prepisala svojou pamatou); inak rovno do suboru."""
        from mirana.features.longterm import MEMORY_PATH, apply_edit
        edit = self._memory_edit()
        if edit is None:
            return
        if self.app.connected and self.app._send("memory_edit", text=json.dumps(edit, ensure_ascii=False)):
            return
        write_json(MEMORY_PATH, apply_edit(read_json(MEMORY_PATH, {}) or {}, edit), indent=1)

    # --- persona ----------------------------------------------------------------------------------

    def _block_persona(self, tab):
        ctk.CTkLabel(tab, text="Osobnosť Mirany (persona.md). Záloha pred uložením: data/persona.md.bak  ·  Ctrl+F = hľadať",
                     text_color=DIM, anchor="w").pack(fill="x", padx=10)
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(4, 0))
        self.find_var = ctk.StringVar()
        self.find_entry = ctk.CTkEntry(bar, textvariable=self.find_var, placeholder_text="Hľadať v persone…", width=260)
        self.find_entry.pack(side="left")
        ctk.CTkButton(bar, text="▲", width=32, command=lambda: self._find(backwards=True), fg_color=PANEL).pack(side="left", padx=(6, 2))
        ctk.CTkButton(bar, text="▼", width=32, command=self._find, fg_color=PANEL).pack(side="left", padx=2)
        self.find_label = ctk.CTkLabel(bar, text="", text_color=DIM)
        self.find_label.pack(side="left", padx=8)
        self.persona_box = self._textbox(tab, self.persona_original, 390)
        text = self.persona_box._textbox  # tkinter Text pod CTkTextbox — tagy a hladanie
        text.tag_configure("find", background="#5a5200", foreground="#ffffff")
        text.tag_configure("find_current", background=YELLOW, foreground="#000000")
        self.find_var.trace_add("write", lambda *_: self._find(restart=True))
        self.find_entry.bind("<Return>", lambda _e: self._find())
        self.find_entry.bind("<Shift-Return>", lambda _e: self._find(backwards=True))
        self.find_entry.bind("<Escape>", lambda _e: (self.find_var.set(""), self.persona_box.focus_set()))
        for widget in (self, text, self.find_entry):
            widget.bind("<Control-f>", self._focus_find)
            widget.bind("<Control-F>", self._focus_find)

    def _focus_find(self, _event=None):
        try:
            self.tabs.set("Persona")
        except Exception:
            pass
        self.find_entry.focus_set()
        self.find_entry.select_range(0, "end")
        return "break"

    def _find(self, backwards: bool = False, restart: bool = False):
        """Zvyrazni vsetky vyskyty (bez ohladu na velkost pismen) a skoci na dalsi/predchadzajuci."""
        text = self.persona_box._textbox
        text.tag_remove("find", "1.0", "end")
        text.tag_remove("find_current", "1.0", "end")
        needle = self.find_var.get()
        if not needle:
            self.find_label.configure(text="")
            return "break"
        hits, start = [], "1.0"
        while True:
            pos = text.search(needle, start, stopindex="end", nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(needle)}c"
            text.tag_add("find", pos, end)
            hits.append(pos)
            start = end
        if not hits:
            self.find_label.configure(text="nenájdené", text_color=RED)
            return "break"
        cursor = "1.0" if restart else text.index("insert")
        if backwards:
            before = [h for h in hits if text.compare(f"{h}+{len(needle)}c", "<", cursor)]
            pos = before[-1] if before else hits[-1]
        else:
            after = [h for h in hits if text.compare(h, ">=" if restart else ">", cursor)]
            pos = after[0] if after else hits[0]
        text.tag_add("find_current", pos, f"{pos}+{len(needle)}c")
        text.mark_set("insert", pos)
        text.see(pos)
        self.find_label.configure(text=f"{hits.index(pos) + 1} z {len(hits)}", text_color=DIM)
        return "break"

    # --- ulozenie -----------------------------------------------------------------------------

    def collect(self) -> dict:
        """Hodnoty z okna (kluc -> hodnota), skontrolovane schemou. ValueError s ludskou spravou pri chybe."""
        values = {}
        for key, (s, get) in self.fields.items():
            value = get()
            err = s.error(value)
            if err:
                raise ValueError(f"{s.label}: {err}")
            values[key] = value
        if values.get("tts.effects.preset") != schema.get(self.current, "tts.effects.preset", None):
            values["tts.effects.enabled"] = True  # vybraty efekt ma aj znieť
        merged = copy.deepcopy(self.current)
        for key, value in values.items():
            schema.put(merged, key, value)
        problems = schema.cross_check(merged)
        if problems:
            raise ValueError(problems[0])
        return values

    def _save(self, restart: bool):
        try:
            values = self.collect()
        except ValueError as e:
            messagebox.showerror("Nastavenia", str(e), parent=self)
            return
        for key, value in values.items():
            _put_path(self.cfg, key, value)
        # hlasitost meni posuvnik v hlavnom okne aj pocas otvorenych Nastaveni — nech ju neprepiseme starou
        _put_path(self.cfg, "audio.volume", settings.load_editable()["audio"].get("volume", 100))

        # novy hlas / tempo / hlasky -> stare fillery by zneli inak, pri starte sa vygeneruju znova
        changed = lambda key: values.get(key, schema.get(self.current, key, None)) != schema.get(self.current, key, None)
        if any(changed(k) for k in VOICE_KEYS + ("fillers.lines", "fillers.search_lines")):
            for wav in (BASE_DIR / "fillers").glob("*.wav"):
                wav.unlink(missing_ok=True)

        settings.save(self.cfg)
        self._save_memory()
        persona = self.persona_box.get("1.0", "end").rstrip()
        if persona != self.persona_original.rstrip():
            settings.save_persona(persona)

        self.app.on_settings_saved(restart)
        self.destroy()
