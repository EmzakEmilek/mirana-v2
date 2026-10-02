"""Okno Nastavenia pre gui.py: vsetko z config.yaml + persona.md, bez rucneho editovania suborov.

Zmeny sa prejavia po restarte Mirany (vacsina nastaveni sa cita pri starte) — tlacidlo
"Ulozit a restartovat" to spravi. Zmena hlasu, rychlosti, vysky alebo fillerov zmaze stare
fillers/*.wav, aby sa pri starte vygenerovali novym hlasom.
"""

import copy
import re
import threading
import tkinter.messagebox as messagebox

import customtkinter as ctk
import numpy as np

from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from core import settings
from core.config import BASE_DIR
from inputs.ptt import parse_key
from outputs.voice_fx import PRESET_LABELS

YELLOW, CYAN, RED, DIM = "#FCEE0A", "#00F0FF", "#FF003C", "#7d7d85"
BG, PANEL, TEXT = "#0a0a0c", "#141418", "#e6e6e6"

VOICES = ["sk-SK-ViktoriaNeural", "sk-SK-LukasNeural", "en-US-EmmaMultilingualNeural", "en-US-AvaMultilingualNeural",
          "pl-PL-AgnieszkaNeural", "pl-PL-ZofiaNeural"]  # poľské = slovenský text s poľským prízvukom, pre srandu
MODELS = {
    "claude-opus-5-5": "najlepšie lore; low ~$1,50 / 4 h (občas kalky), medium ~$1,95 / 4 h, pomalší",
    "claude-sonnet-5-5": "najrýchlejší (low ~2 s), ~$0,95 / 4 h, čistá slovenčina, slabšie lore",
    "claude-opus-5": "staršia generácia, ~$1,00 / 4 h",
    "claude-sonnet-5": "staršia generácia, ~$0,30 / 4 h, častejšie si vymýšľa lore",
}
KEYS = [f"f{i}" for i in range(1, 13)] + ["insert", "home", "end", "page_up", "page_down", "pause", "scroll_lock",
                                          "mouse_x1", "mouse_x2", "mouse_middle"]
STT_MODELS = ["small", "medium", "large-v3", "large-v3-turbo"]
SAMPLE = "Ahoj Emzo, takto znie môj hlas. Johnny Silverhand ťa čaká v Night City. Tak poďme na to."


STREAM_OFF = "(vypnutý)"
STREAM_DEFAULT = "(predvolený výstup Windows)"


def _stream_label(value) -> str:
    return STREAM_OFF if not value else STREAM_DEFAULT if str(value).lower() == "default" else str(value)


def _stream_value(label: str):
    return None if label == STREAM_OFF else "default" if label == STREAM_DEFAULT else label


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


def _pct(value: str) -> int:
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

        self.cfg = settings.load_editable()
        self.original = copy.deepcopy(self.cfg)
        self.persona_original = settings.load_persona()
        self.v: dict[str, ctk.Variable] = {}

        self.tabs = tabs = ctk.CTkTabview(self, fg_color=PANEL, segmented_button_selected_color="#8a8200",
                              segmented_button_selected_hover_color="#a39a00")
        tabs.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        for name, build in (("Zvuk", self._tab_audio), ("Hlas", self._tab_voice), ("Model", self._tab_model),
                            ("Hra", self._tab_game),
                            ("Prepis", self._tab_stt), ("Fillery", self._tab_fillers), ("HUD", self._tab_hud),
                            ("Chat", self._tab_chat), ("Bezpečnosť", self._tab_safety), ("Persona", self._tab_persona)):
            build(tabs.add(name))

        bar = ctk.CTkFrame(self, fg_color=BG)
        bar.pack(fill="x", padx=12, pady=(4, 12))
        self.hint = ctk.CTkLabel(bar, text="Zmeny sa prejavia po reštarte Mirany.", text_color=DIM)
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

    def _combo(self, parent, key, label, values, current, hint="", width=420, command=None):
        var = ctk.StringVar(value=str(current))
        self.v[key] = var
        row = self._row(parent, label, hint)
        box = ctk.CTkComboBox(row, values=values, variable=var, width=width, command=command)
        box.pack(side="left")
        return box

    def _entry(self, parent, key, label, current, hint="", width=120):
        var = ctk.StringVar(value="" if current is None else str(current))
        self.v[key] = var
        ctk.CTkEntry(self._row(parent, label, hint), textvariable=var, width=width).pack(side="left")

    def _switch(self, parent, key, label, current, hint=""):
        var = ctk.BooleanVar(value=bool(current))
        self.v[key] = var
        ctk.CTkSwitch(self._row(parent, label, hint), text="", variable=var, progress_color=YELLOW).pack(side="left")

    def _slider(self, parent, key, label, current, lo, hi, fmt, hint=""):
        var = ctk.IntVar(value=int(current))
        self.v[key] = var
        row = self._row(parent, label, hint)
        value_label = ctk.CTkLabel(row, text=fmt(int(current)), width=70)
        ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=hi - lo, variable=var, width=300, button_color=YELLOW,
                      progress_color=YELLOW, command=lambda v: value_label.configure(text=fmt(int(v)))).pack(side="left")
        value_label.pack(side="left", padx=8)

    def _textbox(self, parent, text: str, height: int):
        box = ctk.CTkTextbox(parent, height=height, fg_color=BG, font=ctk.CTkFont("Consolas", 12), wrap="word")
        box.pack(fill="both", expand=True, padx=10, pady=5)
        box.insert("1.0", text)
        return box

    # --- zalozky ------------------------------------------------------------------------------

    def _tab_audio(self, tab):
        audio = self.cfg["audio"]
        self.show_all = ctk.BooleanVar(value=False)
        self.in_box = self._combo(tab, "audio.input_device", "Mikrofón", [],
                                  audio["input_device"] or "(predvolený mikrofón Windows)")
        self.out_box = self._combo(tab, "audio.output_device", "Výstup", [], _stream_label(audio["output_device"] or "default"),
                                   hint="Kam Mirana hovorí. Predvolený výstup Windows = tam, kam ide zvuk hry.")
        self.stream_box = self._combo(tab, "audio.stream_output_device", "Výstup pre stream",
                                      [], _stream_label(audio.get("stream_output_device")),
                                      hint="Druhý výstup naraz, napr. slúchadlá + HDMI do strihovej karty. Väčšinou vypnutý.")
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

        box = self._combo(tab, "audio.ptt_key", "Kláves na hovor (drž)", KEYS, audio["ptt_key"], width=160,
                          hint="Aj tlačidlo myši: mouse_x1 = zadné bočné, mouse_x2 = predné bočné. Hra ho dostane tiež, "
                               "tak nech v nej nemá priradenú akciu. „Stlačiť…“ = nastav stlačením.")
        self._capture_button(box.master, "audio.ptt_key")
        box = self._combo(tab, "audio.panic_mute_key", "Panic mute", KEYS, audio.get("panic_mute_key", "f11"), width=160)
        self._capture_button(box.master, "audio.panic_mute_key")

    def _capture_button(self, row, key):
        button = ctk.CTkButton(row, text="Stlačiť…", width=80, fg_color=PANEL, border_width=1, border_color=YELLOW,
                               text_color=TEXT)
        button.configure(command=lambda: self._capture_key(key, button))
        button.pack(side="left", padx=6)

    def _capture_key(self, key, button):
        """Nasledujuci klaves alebo bocne/stredne tlacidlo mysi sa zapise do pola. Lave a prave sa ignoruju."""
        from pynput import keyboard, mouse

        button.configure(text="stlač…", state="disabled")
        listeners = []

        def done(spec):
            for listener in listeners:
                listener.stop()

            def apply():
                if spec:
                    self.v[key].set(spec)
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

    def _fill_devices(self):
        try:
            inputs = _audio_devices("input", self.show_all.get())
            outputs = _audio_devices("output", self.show_all.get())
        except Exception as e:
            inputs, outputs = [], []
            self.hint.configure(text=f"Zariadenia sa nedajú načítať: {e}", text_color=RED)
        self.in_box.configure(values=["(predvolený mikrofón Windows)"] + inputs)
        self.out_box.configure(values=[STREAM_DEFAULT] + outputs)
        self.stream_box.configure(values=[STREAM_OFF, STREAM_DEFAULT] + outputs)

    def _tab_voice(self, tab):
        tts = self.cfg["tts"]
        self._combo(tab, "tts.voice", "Hlas (Azure)", VOICES, tts["voice"],
                    hint="Viktoria = slovenský hlas. Emma/Ava = viacjazyčné (fonetiku vypni). Agnieszka/Zofia = poľský prízvuk, pre srandu.")
        self._slider(tab, "tts.rate", "Rýchlosť reči", _pct(tts["rate"]), -30, 50, lambda v: f"{v:+d} %",
                     hint="0 % = prirodzené tempo Azure. +10 až +20 % znie svižnejšie a stále zrozumiteľne.")
        self._slider(tab, "tts.sentence_pause_ms", "Pauza medzi vetami", tts.get("sentence_pause_ms", 250), 100, 800,
                     lambda v: f"{v} ms", hint="Ticho medzi vetami odpovede. Bez orezania by bolo ~900 ms.")
        self._slider(tab, "tts.pitch", "Výška hlasu", _pct(tts["pitch"]), -20, 20, lambda v: f"{v:+d} %")
        self._switch(tab, "tts.phonetics", "Fonetika anglických názvov", bool(tts.get("phonetics_file")),
                     hint="Prepíše „Night City“ na „Najt Siti“ pre slovenský hlas (phonetics.yaml).")
        effects = tts.get("effects") or {}
        preset = effects.get("preset", "vypnute") if effects.get("enabled", True) else "vypnute"
        self._combo(tab, "tts.effects", "Efekty hlasu", list(PRESET_LABELS.values()), PRESET_LABELS.get(preset, preset),
                    width=160, hint="Night City = digitálna AI (filtre, zrnitosť, kovový nádych, echo). Platí aj pre fillery; "
                                    "vyskúšaj tlačidlom Vypočuť.")
        self.sample = ctk.StringVar(value=SAMPLE)
        row = self._row(tab, "Ukážka")
        ctk.CTkEntry(row, textvariable=self.sample, width=330).pack(side="left")
        ctk.CTkButton(row, text="Vypočuť", width=80, command=self._preview_voice, fg_color=YELLOW,
                      text_color="#000").pack(side="left", padx=6)

    def _tab_model(self, tab):
        llm, limits, memory = self.cfg["llm"], self.cfg["limits"], self.cfg["memory"]
        box = self._combo(tab, "llm.model", "Model", list(MODELS), llm["model"], width=260,
                          command=lambda m: self.model_hint.configure(text=MODELS.get(m, "")))
        self.model_hint = ctk.CTkLabel(tab, text=MODELS.get(llm["model"], ""), text_color=DIM, anchor="w")
        self.model_hint.pack(fill="x", padx=(190, 12))
        var = ctk.StringVar(value=llm["effort"])
        self.v["llm.effort"] = var
        row = self._row(tab, "Effort (premýšľanie)", "low = najrýchlejšia odpoveď. Vyšší effort = presnejšie, ale pomalšie a drahšie.")
        ctk.CTkSegmentedButton(row, values=["low", "medium", "high"], variable=var,
                               selected_color="#8a8200").pack(side="left")
        self._switch(tab, "llm.fallbacks", "Záložný model", bool(llm.get("fallbacks")),
                     hint="Keď bezpečnostný filter omylom odmietne otázku, zopakuje ju iný model (len Opus).")
        self._entry(tab, "limits.daily_usd_cap", "Denný strop ($)", limits["daily_usd_cap"],
                    hint="Po jeho dosiahnutí Mirana do polnoci neodpovedá.")
        self._entry(tab, "memory.max_exchanges", "Pamäť (výmen)", memory["max_exchanges"],
                    hint="Koľko otázok a odpovedí si pamätá. Viac = lepšie nadväzuje, mierne drahšie.")
        self._entry(tab, "memory.trim_to", "Po zaplnení ponechať", memory.get("trim_to", memory["max_exchanges"]))

    def _tab_game(self, tab):
        from inputs.game_state import cet_installed, find_game_dir

        gs, limits = self.cfg["game_state"], self.cfg["limits"]
        self.game_dir = find_game_dir()
        if self.game_dir is None:
            status, color = "Cyberpunk 2077 sa nenašiel (Steam / GOG / Epic). Po inštalácii otvor nastavenia znova.", RED
        elif not cet_installed(self.game_dir):
            status, color = f"Hra: {self.game_dir}\nCyber Engine Tweaks nie je nainštalovaný — rozbaľ ho do bin\\x64.", RED
        else:
            status, color = f"Hra: {self.game_dir}\nCyber Engine Tweaks: nainštalovaný", CYAN
        ctk.CTkLabel(tab, text=status, text_color=color, anchor="w", justify="left").pack(fill="x", padx=10, pady=(6, 2))
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=4)
        ctk.CTkButton(row, text="Nainštalovať / aktualizovať mod", width=230, fg_color=YELLOW, text_color="#000",
                      command=self._install_mod,
                      state="normal" if self.game_dir and cet_installed(self.game_dir) else "disabled").pack(side="left")
        self.mod_label = ctk.CTkLabel(row, text="", text_color=DIM)
        self.mod_label.pack(side="left", padx=10)

        self._switch(tab, "game_state.enabled", "Telemetria z hry", gs["enabled"],
                     hint="Mirana vie, kde si, aký máš quest, HP a či bojuješ. Bez bežiacej hry sa nič nedeje.")
        self._entry(tab, "game_state.json_path", "Súbor stavu", gs.get("json_path", "auto"), width=420,
                    hint="auto = nájde hru sama. Inak cesta k state.json z CET modu.")
        self._entry(tab, "game_state.hp_low_threshold", "Nízke HP (%)", gs["hp_low_threshold"], width=60)
        self._entry(tab, "game_state.hp_critical_threshold", "Kritické HP (%)", gs["hp_critical_threshold"], width=60)
        self._entry(tab, "limits.proactive_cooldown_sec", "Pauza medzi hláškami (s)", limits["proactive_cooldown_sec"],
                    width=60, hint="Sama od seba sa ozve najviac raz za tento čas. Kritické HP a smrť majú výnimku. Počas rozhovorov a cutscén mlčí.")
        ctk.CTkLabel(tab, text="Kedy sa ozve sama:", text_color=TEXT, anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        grid = ctk.CTkFrame(tab, fg_color="transparent")
        grid.pack(fill="x", padx=30)
        self.speak_vars = {}
        events = [("hp_critical", "kritické HP"), ("hp_low", "nízke HP"), ("death", "smrť"), ("level_up", "nový level"),
                  ("district_change", "nová štvrť"), ("quest_changed", "nový quest"), ("quest_completed", "dokončený quest"),
                  ("wanted_up", "polícia ho hľadá"), ("wanted_clear", "polícia prestala"), ("combat_start", "začiatok boja"),
                  ("combat_end", "koniec boja")]
        current = set(gs.get("speak_on", []))
        for i, (key, label) in enumerate(events):
            var = ctk.BooleanVar(value=key in current)
            self.speak_vars[key] = var
            ctk.CTkCheckBox(grid, text=label, variable=var, fg_color=YELLOW, text_color=TEXT).grid(
                row=i // 4, column=i % 4, sticky="w", padx=6, pady=3)

    def _install_mod(self):
        from inputs.game_state import install_mod

        try:
            path = install_mod(self.game_dir)
            self.mod_label.configure(text="Hotovo — po štarte hry zapisuje " + path.name, text_color=CYAN)
        except Exception as e:
            self.mod_label.configure(text=f"Chyba: {e}", text_color=RED)

    def _tab_stt(self, tab):
        stt = self.cfg["stt"]
        self._combo(tab, "stt.provider", "Prepis reči", ["local", "api"], stt["provider"], width=160,
                    hint="local = Whisper na tvojej grafike (zadarmo). api = OpenAI Whisper (treba OPENAI_API_KEY).")
        self._combo(tab, "stt.local_model", "Whisper model", STT_MODELS, stt["local_model"], width=200,
                    hint="medium = overený kompromis. large-v3 = presnejší, ~2× pomalší, viac VRAM. "
                         "large-v3-turbo v teste prekladal do angličtiny.")
        self._entry(tab, "stt.language", "Jazyk", stt["language"], width=60)

    def _tab_fillers(self, tab):
        fill = self.cfg["fillers"]
        self._switch(tab, "fillers.enabled", "Filler hlášky", fill["enabled"])
        self._switch(tab, "fillers.speak", "Hovoriť ich nahlas", fill.get("speak", True),
                     hint="Vypnuté = filler sa len ukáže na HUD, Mirana ho nepovie.")
        self._slider(tab, "fillers.skip_if_faster_than_ms", "Pauza pred fillerom", fill["skip_if_faster_than_ms"],
                     500, 3000, lambda v: f"{v} ms", hint="Keď odpoveď príde skôr, filler sa nezahrá.")
        ctk.CTkLabel(tab, text="Hlášky (jedna na riadok):", text_color=TEXT, anchor="w").pack(fill="x", padx=10, pady=(8, 0))
        self.fillers_box = self._textbox(tab, "\n".join(fill["lines"]), 130)
        idle = self.cfg.get("idle_nudge") or {}
        self._switch(tab, "idle_nudge.enabled", "Pripomenúť sa po tichu", idle.get("enabled", False),
                     hint="Keď sa dlho neozveš, Mirana sa vtipne ozve sama (nie v boji ani v cutscéne).")
        self._entry(tab, "idle_nudge.after_min", "Po koľkých minútach", idle.get("after_min", 10), width=60)

    def _tab_hud(self, tab):
        hud = self.cfg["overlay"]
        self._switch(tab, "overlay.enabled", "HUD zapnutý", hud["enabled"])
        self._entry(tab, "overlay.port", "Port", hud["port"], hint="OBS Browser Source: http://IP-herného-PC:port")
        self._entry(tab, "overlay.typewriter_ms_per_char", "Písanie (ms/znak)", hud["typewriter_ms_per_char"],
                    hint="Len záloha, keď hlas vypadne. Inak sa text píše v tempe reči.")

    def _tab_chat(self, tab):
        chat = self.cfg.get("twitch_chat") or {}
        self._switch(tab, "twitch_chat.enabled", "Čítať Twitch chat", chat.get("enabled", False),
                     hint="Mirana chat len číta (bez bota, nič nepíše). Sama ho nekomentuje, len keď sa spýtaš, "
                          "napr. „čo píše chat?“")
        self._entry(tab, "twitch_chat.channel", "Kanál", chat.get("channel") or "", width=260,
                    hint="Názov kanála alebo odkaz, napr. twitch.tv/tvojkanal.")
        self._entry(tab, "twitch_chat.max_messages", "Posledných správ", chat.get("max_messages", 15), width=60,
                    hint="Koľko posledných správ Mirana vidí pri tvojej otázke.")
        self._entry(tab, "twitch_chat.max_age_sec", "Nie staršie ako (s)", chat.get("max_age_sec", 300), width=60)
        ctk.CTkLabel(tab, text="Ignorovaní boti (jeden na riadok):", text_color=TEXT,
                     anchor="w").pack(fill="x", padx=10, pady=(8, 0))
        self.ignore_box = self._textbox(tab, "\n".join(chat.get("ignore_users") or []), 120)

    def _tab_safety(self, tab):
        safety = self.cfg.get("safety", {})
        self._switch(tab, "safety.enabled", "Bezpečnostný filter", safety.get("enabled", True),
                     hint="E-maily, telefónne čísla, IP adresy a odkazy sa nevyslovia nikdy.")
        ctk.CTkLabel(tab, text="Zakázané slová (jedno na riadok, stačí začiatok slova):", text_color=TEXT,
                     anchor="w").pack(fill="x", padx=10, pady=(8, 0))
        self.words_box = self._textbox(tab, "\n".join(safety.get("blocked_words", [])), 220)

    def _tab_persona(self, tab):
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
        self._find_tab = tab

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

    # --- testy --------------------------------------------------------------------------------

    def _selected_input(self):
        value = self.v["audio.input_device"].get()
        return None if not value or value.startswith("(") else value

    def _test_mic(self):
        device = self._selected_input()
        self.mic_label.configure(text="Hovor…", text_color=CYAN)

        def run():
            import sounddevice as sd

            from outputs.voice import _ensure_com
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
                self.after(0, lambda: self.mic_label.configure(text=f"Chyba: {e}", text_color=RED))
            self.after(600, self.mic_bar.set, 0)

        threading.Thread(target=run, daemon=True).start()

    def _test_out(self):
        device = _stream_value(self.v["audio.output_device"].get()) or "default"

        def run():
            import sounddevice as sd

            from outputs.voice import _ensure_com, resolve_output
            _ensure_com()
            try:
                device_index = resolve_output(device)
                rate = int(sd.query_devices(device_index)["default_samplerate"])
                tone = (np.sin(2 * np.pi * 660 * np.arange(0, 0.4, 1 / rate)) * 0.2 * 32767).astype(np.int16)
                with sd.OutputStream(samplerate=rate, device=device_index, channels=1, dtype="int16") as stream:
                    stream.write(tone.reshape(-1, 1))
            except Exception as e:
                self.after(0, lambda: self.hint.configure(text=f"Výstup: {e}", text_color=RED))

        threading.Thread(target=run, daemon=True).start()

    def _preview_voice(self):
        cfg = settings.load_editable()
        cfg["audio"]["output_device"] = _stream_value(self.v["audio.output_device"].get()) or "default"
        cfg["audio"]["stream_output_device"] = _stream_value(self.v["audio.stream_output_device"].get())
        cfg["tts"]["voice"] = self.v["tts.voice"].get()
        cfg["tts"]["rate"] = f"{self.v['tts.rate'].get():+d}%"
        cfg["tts"]["pitch"] = f"{self.v['tts.pitch'].get():+d}%"
        cfg["tts"]["sentence_pause_ms"] = self.v["tts.sentence_pause_ms"].get()
        cfg["tts"]["phonetics_file"] = "phonetics.yaml" if self.v["tts.phonetics"].get() else None
        cfg["tts"]["effects"] = {"enabled": True, "preset": self._effects_preset(),
                                 "params": dict((cfg["tts"].get("effects") or {}).get("params") or {})}
        text = self.sample.get()
        self.hint.configure(text="Syntetizujem ukážku…", text_color=DIM)

        def run():
            try:
                from outputs.voice import Voice
                voice = Voice(cfg)
                # po vetach ako pri skutocnej odpovedi, aby bolo pocut aj pauzu medzi vetami
                sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
                clips = [voice.to_device_audio(voice.synthesize(s, timeout=15)) for s in sentences]
                voice.arm()
                for clip in clips:
                    voice.play_audio(clip)
                self.after(0, lambda: self.hint.configure(text="Zmeny sa prejavia po reštarte Mirany.", text_color=DIM))
            except Exception as e:
                self.after(0, lambda: self.hint.configure(text=f"Ukážka zlyhala: {e}", text_color=RED))

        threading.Thread(target=run, daemon=True).start()

    def _effects_preset(self) -> str:
        label = self.v["tts.effects"].get()
        return next((k for k, v in PRESET_LABELS.items() if v == label), label)

    # --- ulozenie -----------------------------------------------------------------------------

    def _collect(self):
        """Hodnoty z formulara -> self.cfg. Vyhodi ValueError s ludskou spravou pri zlom vstupe."""
        c, v = self.cfg, self.v

        def number(key, kind=float, lo=None):
            raw = v[key].get().strip().replace(",", ".")
            try:
                value = kind(raw)
            except ValueError:
                raise ValueError(f"„{raw}“ nie je číslo ({key})")
            if lo is not None and value < lo:
                raise ValueError(f"{key} musí byť aspoň {lo}")
            return value

        _put(c["audio"], "input_device", self._selected_input())
        _put(c["audio"], "output_device", _stream_value(v["audio.output_device"].get()) or "default")
        _put(c["audio"], "volume", settings.load_editable()["audio"].get("volume", 100))  # posuvnik v hlavnom okne
        _put(c["audio"], "stream_output_device", _stream_value(v["audio.stream_output_device"].get()))
        _put(c["audio"], "ptt_key", v["audio.ptt_key"].get())
        _put(c["audio"], "panic_mute_key", v["audio.panic_mute_key"].get())
        if c["audio"]["ptt_key"] == c["audio"]["panic_mute_key"]:
            raise ValueError("Kláves na hovor a panic mute musia byť rôzne.")
        for key in ("audio.ptt_key", "audio.panic_mute_key"):
            try:
                parse_key(v[key].get())
            except ValueError:
                raise ValueError(f"Neznámy kláves „{v[key].get()}“") from None

        _put(c["tts"], "voice", v["tts.voice"].get())
        _put(c["tts"], "rate", f"{v['tts.rate'].get():+d}%".replace("+0%", "0%"))
        _put(c["tts"], "pitch", f"{v['tts.pitch'].get():+d}%".replace("+0%", "0%"))
        _put(c["tts"], "sentence_pause_ms", v["tts.sentence_pause_ms"].get())
        _put(c["tts"], "phonetics_file", "phonetics.yaml" if v["tts.phonetics"].get() else None)
        preset = self._effects_preset()
        if preset not in PRESET_LABELS:
            raise ValueError(f"Neznámy efekt hlasu „{preset}“")
        if "effects" not in c["tts"]:
            c["tts"]["effects"] = {"enabled": True, "preset": preset, "params": {}}
        _put(c["tts"]["effects"], "enabled", True)
        _put(c["tts"]["effects"], "preset", preset)

        _put(c["llm"], "model", v["llm.model"].get())
        _put(c["llm"], "effort", v["llm.effort"].get())
        _put(c["llm"], "fallbacks", "default" if v["llm.fallbacks"].get() else None)
        _put(c["limits"], "daily_usd_cap", number("limits.daily_usd_cap", float, 0.1))
        _put(c["memory"], "max_exchanges", number("memory.max_exchanges", int, 1))
        _put(c["memory"], "trim_to", number("memory.trim_to", int, 0))
        if c["memory"]["trim_to"] > c["memory"]["max_exchanges"]:
            raise ValueError("„Po zaplnení ponechať“ nemôže byť viac ako veľkosť pamäte.")

        _put(c["game_state"], "enabled", v["game_state.enabled"].get())
        _put(c["game_state"], "json_path", v["game_state.json_path"].get().strip() or "auto")
        _put(c["game_state"], "hp_low_threshold", number("game_state.hp_low_threshold", int, 1))
        _put(c["game_state"], "hp_critical_threshold", number("game_state.hp_critical_threshold", int, 1))
        if c["game_state"]["hp_critical_threshold"] >= c["game_state"]["hp_low_threshold"]:
            raise ValueError("Kritické HP musí byť nižšie ako nízke HP.")
        _put(c["limits"], "proactive_cooldown_sec", number("limits.proactive_cooldown_sec", int, 0))
        _put(c["game_state"], "speak_on", [k for k, var in self.speak_vars.items() if var.get()])

        _put(c["stt"], "provider", v["stt.provider"].get())
        _put(c["stt"], "local_model", v["stt.local_model"].get())
        _put(c["stt"], "language", v["stt.language"].get().strip() or "sk")

        _put(c["fillers"], "enabled", v["fillers.enabled"].get())
        _put(c["fillers"], "speak", v["fillers.speak"].get())
        if "idle_nudge" not in c:
            c["idle_nudge"] = {}
        _put(c["idle_nudge"], "enabled", v["idle_nudge.enabled"].get())
        _put(c["idle_nudge"], "after_min", number("idle_nudge.after_min", int, 1))
        _put(c["fillers"], "skip_if_faster_than_ms", int(v["fillers.skip_if_faster_than_ms"].get()))
        lines = [ln.strip() for ln in self.fillers_box.get("1.0", "end").splitlines() if ln.strip()]
        if c["fillers"]["enabled"] and not lines:
            raise ValueError("Zapnuté fillery potrebujú aspoň jednu hlášku.")
        _put(c["fillers"], "lines", lines)

        _put(c["overlay"], "enabled", v["overlay.enabled"].get())
        _put(c["overlay"], "port", number("overlay.port", int, 1024))
        _put(c["overlay"], "typewriter_ms_per_char", number("overlay.typewriter_ms_per_char", int, 5))

        if "twitch_chat" not in c:
            c["twitch_chat"] = {}
        chat = c["twitch_chat"]
        _put(chat, "enabled", v["twitch_chat.enabled"].get())
        _put(chat, "channel", v["twitch_chat.channel"].get().strip())
        _put(chat, "max_messages", number("twitch_chat.max_messages", int, 1))
        _put(chat, "max_age_sec", number("twitch_chat.max_age_sec", int, 10))
        _put(chat, "ignore_users", [u.strip().lower() for u in self.ignore_box.get("1.0", "end").splitlines() if u.strip()])

        c.setdefault("safety", {})
        _put(c["safety"], "enabled", v["safety.enabled"].get())
        words = [w.strip() for w in self.words_box.get("1.0", "end").splitlines() if w.strip()]
        _put(c["safety"], "blocked_words", words)

    def _save(self, restart: bool):
        try:
            self._collect()
        except ValueError as e:
            messagebox.showerror("Nastavenia", str(e), parent=self)
            return

        # novy hlas / tempo / hlasky -> stare fillery by zneli inak, pri starte sa vygeneruju znova
        voice_keys = ("voice", "rate", "pitch", "phonetics_file")
        voice_changed = any(self.cfg["tts"].get(k) != self.original["tts"].get(k) for k in voice_keys)
        lines_changed = list(self.cfg["fillers"]["lines"]) != list(self.original["fillers"]["lines"])
        if voice_changed or lines_changed:
            for wav in (BASE_DIR / "fillers").glob("*.wav"):
                wav.unlink(missing_ok=True)

        settings.save(self.cfg)
        persona = self.persona_box.get("1.0", "end").rstrip()
        if persona != self.persona_original.rstrip():
            settings.save_persona(persona)

        self.app.on_settings_saved(restart)
        self.destroy()
