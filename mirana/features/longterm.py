"""Dlhodoba pamat medzi sessions: hra, historia streamov, fakty o Erikovi, divaci. Subor data/memory.json.

Co sa zapisuje a ako:
- game     — postup v hre automaticky z telemetrie (level, lifepath, build, kde skoncil, dokoncene questy)
- streams  — kazdy den streamu: dlzka, smrti, levely, questy, znacky, 2-3 momenty (zo zhrnutia modelom)
- erik     — fakty o Erikovi a dohody (rozhodnutia v hre, co ma rad, co o sebe povedal) — zhrnutie modelom
- viewers  — divaci: automaticky (prvy/posledny prichod, navstevy, pocet sprav, sub/mod) + 1-3 poznamky
             zo zhrnutia modelom (len herne a nevinne veci, ziadne osobne udaje)

Zhrnutie modelom bezi kazdych longterm.checkpoint_min minut, pri vypnuti a pri starte doplni sessions,
ktore sa nestihli spracovat (pad). Spracuje len nove riadky logs/rozhovor-*.jsonl a logs/chat-*.jsonl.

Do promptu ide blok [PAMÄŤ] za personou (zostavi sa pri starte a po zhrnuti — nemeni sa pri kazdej otazke,
aby fungovala cache) a pri otazke riadok [DIVÁCI] len o divakoch, ktori su prave v chate alebo ich Erik
spomenul. Subor sa da upravit v Nastaveniach -> Pamat alebo rucne.
"""

import json
import logging
import re
import threading
import time
import unicodedata
from datetime import date, datetime

from mirana import intents
from mirana.config import BASE_DIR
from mirana.features import Feature
from mirana.store import append_jsonl, read_json, write_json

logger = logging.getLogger(__name__)

MEMORY_PATH = BASE_DIR / "data" / "memory.json"
LOGS_DIR = BASE_DIR / "logs"
MAX_STREAMS = 10
SAVE_EVERY_SEC = 20

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "erik_facts": {"type": "array", "items": {"type": "string"},
                       "description": "Cely aktualizovany zoznam faktov o Erikovi (najviac max_facts)."},
        "viewers": {"type": "array", "items": {
            "type": "object",
            "properties": {"login": {"type": "string"}, "notes": {"type": "array", "items": {"type": "string"}}},
            "required": ["login", "notes"], "additionalProperties": False}},
        "highlights": {"type": "array", "items": {"type": "string"},
                       "description": "Najviac 3 nove najvyraznejsie momenty z tejto casti streamu."},
    },
    "required": ["erik_facts", "viewers", "highlights"],
    "additionalProperties": False,
}

EXTRACT_PROMPT = """Si pamäť AI parťáčky Mirany zo streamu Cyberpunku 2077 (streamer Erik, prezývka Emzo).
Dostaneš doterajšie fakty a nový kus rozhovoru Erika s Miranou a správ z Twitch chatu. Vráť JSON:

erik_facts: CELÝ aktualizovaný zoznam (najviac {max_facts}, ideálne 8 až 15) krátkych faktov po slovensky,
každý najviac 15 slov, každý o niečom inom (žiadne duplicity), čo sa oplatí vedieť aj na ďalšom streame:
- rozhodnutia v hre a ich následky (koho zabil či ušetril, čo nenačítava, s kým to ťahá),
- herný štýl a chute (čo ho baví, čo nie, ako rád hrá), vzhľad jeho V, ak je výrazný,
- dohody s Miranou o tom, ako sa má správať (koľko nadávať, nesúriť do questov...).
Ponechaj staré platné, zlúč podobné, zmeň zastarané, vyhoď zbytočné. NEPÍŠ: techniku Mirany (wiki, oneskorenie,
reštarty, logy, čo vidí či nevidí — to sa mení), atribúty a level (Mirana ich vidí z hry), dočasné veci (HP,
kam práve ide), lore hry, spoilery.

viewers: len diváci, o ktorých sa z TOHTO kusu chatu dá povedať niečo nové: 1-3 krátke poznámky na diváka
(najviac {viewer_notes}), spojené so starými — čo radí, čo ich baví, ako vtipkujú, čomu fandia v hre.
login = presne login z chatu. NIKDY osobné údaje: bydlisko, vek, skutočné meno, zdravie, práca, kontakty,
vzťahy, politika, náboženstvo. Keď o divákovi nič také nie je, nevracaj ho.

highlights: najviac 3 najvýraznejšie momenty tohto kusu streamu, jedna krátka veta (vtipné, dramatické).
Keď nie je nič, prázdne zoznamy. Nevymýšľaj."""


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def _nick_core(nick: str) -> str:
    """"Marek_88" -> "marek", "xXKuboXx" -> "kubo" (na hladanie podla toho, ako Erik nick vyslovi)."""
    core = re.sub(r"(?i)^xx|xx$", "", nick or "")
    return re.sub(r"\d+", "", _norm(core)) or _norm(nick)


def _nick_cores(nick: str) -> set[str]:
    """Ako sa da nick vyslovit: cely ("kubosk") aj casti oddelene _ - . ("Kubo_SK" -> "kubo")."""
    cores = {_nick_core(nick)}
    parts = re.split(r"[_\-. ]+", re.sub(r"(?i)^xx|xx$", "", nick or ""))
    if len(parts) > 1:
        cores |= {c for c in (re.sub(r"\d+", "", _norm(x)) for x in parts) if len(c) >= 4}
    return {c for c in cores if len(c) >= 3}


def _mentioned(nick: str, words: set[str]) -> bool:
    """Spomenul Erik divaka? Aj vysklonovane: Kubo -> Kubovi, Kuba (koncova samohlaska sa meni)."""
    for core in _nick_cores(nick):
        stems = {core}
        if len(core) >= 4 and core[-1] in "aeiouy":
            stems.add(core[:-1])
        for w in words:
            if any(w.startswith(stem) and len(w) - len(stem) <= 3 for stem in stems):
                return True
    return False


class LongTermMemory:
    def __init__(self, config: dict, session_id: str):
        cfg = config.get("longterm") or {}
        self.enabled = cfg.get("enabled", True)
        self.model = cfg.get("model", "claude-sonnet-5-5")
        self.checkpoint_sec = float(cfg.get("checkpoint_min", 30)) * 60
        self.max_facts = int(cfg.get("max_facts", 25))
        self.viewer_notes = int(cfg.get("viewer_notes", 3))
        self.session_id = session_id
        self.chat_path = LOGS_DIR / f"chat-{session_id}.jsonl"
        self._lock = threading.RLock()
        self._dirty = False
        self._saved = 0.0
        self._extracting = threading.Lock()
        self.data = self._load()
        self.block = self._build_block()

    # --- subor ---------------------------------------------------------------------------------

    def _load(self) -> dict:
        data = read_json(MEMORY_PATH, {})
        if not isinstance(data, dict):
            data = {}
        data.setdefault("version", 1)
        data.setdefault("game", {})
        data.setdefault("streams", [])
        data.setdefault("erik", {"facts": []})
        data.setdefault("viewers", {})
        data.setdefault("processed", {})
        return data

    def reload(self) -> None:
        """Po uprave v Nastaveniach: nacitaj subor znova a obnov blok pre prompt."""
        with self._lock:
            self.data = self._load()
            self.block = self._build_block()
        logger.info("pamat znova nacitana")

    def save(self, force: bool = False) -> None:
        with self._lock:
            if not self._dirty and not force:
                return
            if not force and time.time() - self._saved < SAVE_EVERY_SEC:
                return
            if write_json(MEMORY_PATH, self.data, indent=1):
                self._dirty, self._saved = False, time.time()

    # --- automaticke zapisy ------------------------------------------------------------------------

    def update_game(self, snap) -> None:
        """Snimka z hry -> postup (volat napr. raz za 30 s). Do bloku [PAMÄŤ] sa dostane az pri dalsom starte."""
        if not self.enabled or snap is None:
            return
        g = {}
        for key in ("level", "street_cred", "lifepath"):
            if snap.get(key) is not None:
                g[key] = snap.get(key)
        attrs = snap.get("attributes")
        if isinstance(attrs, dict) and attrs:
            g["attributes"] = attrs
        if snap.location:
            g["last_location"] = snap.location
        if snap.quest:
            g["last_quest"] = snap.quest
        story = snap.get("story") if isinstance(snap.get("story"), dict) else None
        if story and isinstance(story.get("main_done"), list):
            g["main_done"] = [q.get("title") for q in story["main_done"] if isinstance(q, dict) and q.get("title")]
        if snap.get("os"):
            g["os"] = snap.get("os")
        g["updated"] = datetime.now().isoformat(timespec="minutes")
        with self._lock:
            self.data["game"].update(g)
            self._dirty = True
        self.save()

    def add_chat(self, msg) -> None:
        """Sprava z chatu: statistika divaka + zapis do logs/chat-<session>.jsonl (podklad pre zhrnutie)."""
        if not self.enabled:
            return
        today = date.today().isoformat()
        with self._lock:
            v = self.data["viewers"].setdefault(msg.login, {
                "nick": msg.nick, "first_seen": today, "last_seen": today, "visits": 1, "messages": 0,
                "badges": [], "notes": []})
            if v.get("last_seen") != today:
                v["visits"] = v.get("visits", 0) + 1
                v["last_seen"] = today
            v["nick"] = msg.nick
            v["messages"] = v.get("messages", 0) + 1
            for badge in ("broadcaster", "moderator", "vip", "subscriber"):
                if badge in msg.badges and badge not in v["badges"]:
                    v["badges"].append(badge)
            self._dirty = True
        append_jsonl(self.chat_path, {"cas": datetime.now().isoformat(timespec="seconds"), "login": msg.login,
                                       "nick": msg.nick, "text": msg.text})
        self.save()

    def update_stream(self, stats: dict, minutes: int) -> None:
        """Dnesny stream v historii (statistiky z mirana.features.highlights)."""
        if not self.enabled:
            return
        today = date.today().isoformat()
        with self._lock:
            streams = self.data["streams"]
            entry = next((s for s in streams if s.get("date") == today), None)
            if entry is None:
                entry = {"date": today, "minutes": 0, "highlights": []}
                streams.append(entry)
                del streams[:-MAX_STREAMS]
            sessions = entry.setdefault("sessions", {})
            sessions[self.session_id] = minutes
            entry["minutes"] = sum(sessions.values())
            for key in ("death", "level_up", "quest_completed", "marker"):
                entry[key] = stats.get(key, 0)
            self._dirty = True
        self.save()

    # --- prompt ------------------------------------------------------------------------------------

    def _build_block(self) -> str | None:
        """[PAMÄŤ] pre system prompt: hra, posledne streamy, fakty o Erikovi. Divaci tu nie su (idu podla chatu)."""
        if not self.enabled:
            return None
        d, parts = self.data, []
        g = d.get("game") or {}
        if g:
            game = []
            if g.get("level"):
                game.append(f"úroveň {g['level']}" + (f", street cred {g['street_cred']}" if g.get("street_cred") else ""))
            if g.get("lifepath"):
                game.append(f"lifepath {g['lifepath']}")
            if isinstance(g.get("attributes"), dict):
                names = {"body": "Telo", "reflexes": "Reflexy", "tech": "Technika", "intelligence": "Inteligencia",
                         "cool": "Chladnokrvnosť"}
                game.append("atribúty " + " ".join(f"{names.get(k, k)} {v}" for k, v in g["attributes"].items()))
            if g.get("main_done"):
                game.append(f"dokončené hlavné questy ({len(g['main_done'])}): " + ", ".join(g["main_done"][-6:]))
            if g.get("last_location") or g.get("last_quest"):
                game.append("naposledy " + ", ".join(x for x in (g.get("last_location"), g.get("last_quest")) if x))
            parts.append("Hra: " + "; ".join(game) + ".")
        streams = [s for s in d.get("streams") or [] if s.get("minutes")]
        if streams:
            lines = []
            for s in streams[-3:]:
                text = (f"{s['date']}: {s['minutes'] // 60} h {s['minutes'] % 60} min, smrti {s.get('death', 0)}, "
                        f"levely {s.get('level_up', 0)}, questy {s.get('quest_completed', 0)}")
                if s.get("highlights"):
                    text += " — " + "; ".join(s["highlights"][:3])
                lines.append(text)
            parts.append("Posledné streamy: " + " | ".join(lines))
        facts = (d.get("erik") or {}).get("facts") or []
        if facts:
            parts.append("O Erikovi: " + " ".join(f if f.endswith(".") else f + "." for f in facts))
        return "[PAMÄŤ] " + "\n".join(parts) if parts else None

    def viewers_line(self, nicks_in_chat: list[str], question: str) -> str | None:
        """[DIVÁCI] o divakoch, ktori su prave v chate alebo ich Erik v otazke spomenul."""
        if not self.enabled:
            return None
        with self._lock:
            viewers = dict(self.data["viewers"])
        wanted = []
        lower_chat = {n.lower() for n in nicks_in_chat}
        words = {_norm(w) for w in re.findall(r"\w+", question)} - {""}
        for login, v in viewers.items():
            if login in lower_chat or (v.get("nick") or "").lower() in lower_chat or _mentioned(v.get("nick") or login, words):
                wanted.append((login, v))
        if not wanted:
            return None
        parts = []
        for login, v in wanted[:8]:
            badges = {"broadcaster": "streamer", "moderator": "mod", "vip": "vip", "subscriber": "sub"}
            tags = [badges[b] for b in v.get("badges", []) if b in badges]
            text = f"{v.get('nick', login)}: {v.get('visits', 1)}. deň na streame, prvýkrát {v.get('first_seen')}"
            if tags:
                text += ", " + "/".join(tags)
            if v.get("notes"):
                text += ", " + "; ".join(v["notes"])
            parts.append(text)
        return "[DIVÁCI] " + " | ".join(parts)

    # --- zabudni --------------------------------------------------------------------------------------

    def forget_viewer(self, question: str) -> str | None:
        """"zabudni Kuba" -> zmaze poznamky o divakovi (statistiky ostanu). Vrati nick, ak ho nasiel."""
        words = {_norm(w) for w in re.findall(r"\w+", question)} - {""}
        with self._lock:
            for login, v in self.data["viewers"].items():
                if _mentioned(v.get("nick") or login, words):
                    v["notes"] = []
                    self._dirty = True
                    self.save(force=True)
                    return v.get("nick", login)
        return None

    def forget_fact(self, client, question: str) -> int:
        """"zabudni, ze..." -> model vyberie fakty o Erikovi, ktore zmazat. Vrati pocet zmazanych."""
        facts = list((self.data.get("erik") or {}).get("facts") or [])
        if not facts:
            return 0
        listing = "\n".join(f"{i}: {f}" for i, f in enumerate(facts))
        try:
            msg = client.messages.create(
                model=self.model, max_tokens=300, output_config={"effort": "low", "format": {"type": "json_schema", "schema": {
                    "type": "object", "properties": {"remove": {"type": "array", "items": {"type": "integer"}}},
                    "required": ["remove"], "additionalProperties": False}}},
                messages=[{"role": "user", "content": f"Fakty:\n{listing}\n\nErik povedal: „{question}“\n"
                                                      "Ktoré fakty (čísla) má Mirana zabudnúť? Keď žiadny nesedí, prázdny zoznam."}])
            remove = set(json.loads(next(b.text for b in msg.content if b.type == "text"))["remove"])
        except Exception as e:
            logger.warning("zabudnutie zlyhalo: %s", e)
            return 0
        with self._lock:
            self.data["erik"]["facts"] = [f for i, f in enumerate(facts) if i not in remove]
            self._dirty = True
            self.block = self._build_block()
        self.save(force=True)
        return len(remove & set(range(len(facts))))

    # --- zhrnutie modelom -------------------------------------------------------------------------

    def _unprocessed(self) -> list[tuple[str, list[str], list[str], int, int]]:
        """(session, otazky+odpovede, chat, novy_offset_rozhovor, novy_offset_chat) pre nespracovane casti."""
        out = []
        processed = self.data.setdefault("processed", {})
        sessions = sorted({p.stem.split("-", 1)[1] for p in LOGS_DIR.glob("rozhovor-*.jsonl")} |
                          {p.stem.split("-", 1)[1] for p in LOGS_DIR.glob("chat-*.jsonl")})
        for sid in sessions[-4:]:  # pri prvom behu aj posledny stream, dalej len nove casti
            done = processed.get(sid, [0, 0])
            talk_lines = _read_lines(LOGS_DIR / f"rozhovor-{sid}.jsonl")
            chat_lines = _read_lines(LOGS_DIR / f"chat-{sid}.jsonl")
            talk, chat = [], []
            for line in talk_lines[done[0]:]:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                question = record_question(r)
                if question and r.get("mirana"):
                    talk.append(f"Erik: {question}\nMirana: {r['mirana']}")
            for line in chat_lines[done[1]:]:
                try:
                    c = json.loads(line)
                except ValueError:
                    continue
                chat.append(f"{c.get('login')} ({c.get('nick')}): {c.get('text')}")
            if not chat_lines and done[0] == 0:
                chat = self._chat_from_talk(sid, talk_lines)  # starsie sessions: chat len v riadkoch [CHAT]
            if talk or chat:
                out.append((sid, talk, chat, len(talk_lines), len(chat_lines)))
        return out

    def _chat_from_talk(self, sid: str, talk_lines: list[str]) -> list[str]:
        """Session bez logs/chat-*.jsonl (pred zavedenim pamate): spravy z riadkov [CHAT] v rozhovore,
        bez duplicit; zaroven zalozi statistiky divakov."""
        labels = {"mod": "moderator", "sub": "subscriber", "vip": "vip", "streamer": "broadcaster"}
        day = f"{sid[:4]}-{sid[4:6]}-{sid[6:8]}"
        seen, out = set(), []
        for line in talk_lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            chat_line = record_chat(record)
            for part in chat_line[7:].split(" | "):
                m = re.match(r"^([^:(]+?)(?: \((mod|sub|vip|streamer)\))?: (.+)$", part.strip())
                if not m or part.startswith(("dnes v chate", "posledné minúty")):
                    continue
                nick, label, text = m.group(1).strip(), m.group(2), m.group(3).strip()
                if (nick, text) in seen:
                    continue
                seen.add((nick, text))
                login = nick.lower()
                out.append(f"{login} ({nick}): {text}")
                with self._lock:
                    v = self.data["viewers"].setdefault(login, {"nick": nick, "first_seen": day, "last_seen": day,
                                                                "visits": 1, "messages": 0, "badges": [], "notes": []})
                    v["messages"] = v.get("messages", 0) + 1
                    if label and labels[label] not in v["badges"]:
                        v["badges"].append(labels[label])
                    self._dirty = True
        return out

    def extract(self, client) -> bool:
        """Zhrnutie novych casti rozhovoru a chatu modelom -> fakty, poznamky o divakoch, momenty. Thread-safe."""
        if not self.enabled or not self._extracting.acquire(blocking=False):
            return False
        try:
            changed = False
            for sid, talk, chat, talk_end, chat_end in self._unprocessed():
                with self._lock:
                    facts = list(self.data["erik"]["facts"])
                    active = {line.split(" ", 1)[0] for line in chat}
                    known = {login: v.get("notes", []) for login, v in self.data["viewers"].items() if login in active}
                payload = ("Doterajšie fakty o Erikovi:\n" + ("\n".join(f"- {f}" for f in facts) or "(žiadne)") +
                           "\n\nDoterajšie poznámky o divákoch z tohto chatu:\n" +
                           ("\n".join(f"- {k}: {'; '.join(n) or '(žiadne)'}" for k, n in known.items()) or "(žiadne)") +
                           "\n\nRozhovor Erika s Miranou:\n" + ("\n\n".join(talk[-150:]) or "(nič)") +
                           "\n\nTwitch chat (login (nick): text):\n" + ("\n".join(chat[-400:]) or "(nič)"))
                msg = client.messages.create(
                    model=self.model, max_tokens=4000,
                    output_config={"effort": "low", "format": {"type": "json_schema", "schema": EXTRACT_SCHEMA}},
                    system=EXTRACT_PROMPT.format(max_facts=self.max_facts, viewer_notes=self.viewer_notes),
                    messages=[{"role": "user", "content": payload}])
                if msg.stop_reason == "refusal":
                    logger.warning("zhrnutie pamate odmietnute")
                    continue
                result = json.loads(next(b.text for b in msg.content if b.type == "text"))
                with self._lock:
                    if isinstance(result.get("erik_facts"), list):
                        self.data["erik"]["facts"] = [str(f).strip() for f in result["erik_facts"] if str(f).strip()][:self.max_facts]
                    for item in result.get("viewers") or []:
                        v = self.data["viewers"].get(item.get("login", "").lower())
                        if v is not None:
                            v["notes"] = [str(n).replace("|", "/").strip() for n in item.get("notes", []) if str(n).strip()][:self.viewer_notes]
                    if result.get("highlights"):
                        day = f"{sid[:4]}-{sid[4:6]}-{sid[6:8]}"
                        entry = next((s for s in self.data["streams"] if s.get("date") == day), None)
                        if entry is None:
                            entry = {"date": day, "minutes": 0, "highlights": []}
                            self.data["streams"].append(entry)
                        entry["highlights"] = (entry.get("highlights", []) + list(result["highlights"]))[-6:]
                    self.data["processed"][sid] = [talk_end, chat_end]
                    self._dirty = True
                    changed = True
                logger.info("pamat: zhrnutie session %s (%d vymen, %d sprav chatu) — faktov %d",
                            sid, len(talk), len(chat), len(self.data["erik"]["facts"]))
            if changed:
                with self._lock:
                    self.block = self._build_block()
                self.save(force=True)
            return changed
        except Exception as e:
            logger.warning("zhrnutie pamate zlyhalo: %s", e)
            return False
        finally:
            self._extracting.release()

    def start(self, client, stats_fn=None) -> None:
        """Na pozadi: doplnenie nespracovanych sessions a zhrnutie kazdych checkpoint_min minut."""
        if not self.enabled:
            return

        def loop():
            self.extract(client)
            while True:
                time.sleep(self.checkpoint_sec)
                if stats_fn is not None:
                    stats_fn()
                self.extract(client)
        threading.Thread(target=loop, name="longterm", daemon=True).start()


def _read_lines(path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def record_question(r: dict) -> str | None:
    """Erikova otazka zo zaznamu rozhovoru (novy format so zdrojom aj stary s [ERIK] v jednom texte)."""
    if "zdroj" in r:
        return r.get("otazka") if r["zdroj"] in ("voice", "typed") else None
    last = (r.get("erik") or "").split("\n")[-1]
    return last[7:] if last.startswith("[ERIK]") else None


def record_chat(r: dict) -> str:
    """Riadok [CHAT] zo zaznamu rozhovoru (alebo "")."""
    if "kontext" in r:
        return (r.get("kontext") or {}).get("CHAT", "")
    return next((x for x in (r.get("erik") or "").split("\n") if x.startswith("[CHAT]")), "")


class LongTermFeature(Feature):
    """Pamat medzi streamami: [PAMÄŤ] v system prompte, [DIVÁCI] k otazke, "zabudni", zhrnutie modelom."""

    def __init__(self, app):
        super().__init__(app)
        self.memory = LongTermMemory(app.config, app.session_id)
        app.brain.memory_block = lambda: self.memory.block
        self._game_at = 0.0

    def start(self) -> None:
        self.memory.start(self.app.brain.anthropic_client, stats_fn=self.save_stream)

    def save_stream(self) -> None:
        minutes = int((time.time() - self.app.highlights.session_start) // 60)
        self.memory.update_stream(self.app.highlights.stats, minutes)

    def on_chat(self, msg) -> None:
        self.memory.add_chat(msg)

    def on_snapshot(self, snap) -> None:
        if snap and time.time() - self._game_at > 30:
            self._game_at = time.time()
            self.memory.update_game(snap)

    def context(self, turn) -> None:
        if not turn.from_erik:
            return
        question = turn.question
        if intents.wants_forget(question):
            nick = self.memory.forget_viewer(question)
            if nick:
                turn.add("SYSTÉM", f"[SYSTÉM] poznámky o divákovi {nick} sú zmazané")
            else:
                n = self.memory.forget_fact(self.app.brain.anthropic_client, question)
                turn.add("SYSTÉM", f"[SYSTÉM] z pamäte o Erikovi zmazané fakty: {n}" if n
                         else "[SYSTÉM] v pamäti som nič také nenašla")
        turn.add("DIVÁCI", self.memory.viewers_line(self.app.chat.recent_logins(), question))

    def on_command(self, cmd: str, text: str | None) -> bool:
        if cmd == "memory_reload":
            self.memory.reload()
            return True
        return False

    def shutdown(self) -> None:
        """Statistiky dna a zhrnutie modelom (max ~25 s; co nestihne, doplni dalsi start)."""
        self.save_stream()
        self.app.overlay.notice("Ukladám pamäť…")
        worker = threading.Thread(target=self.memory.extract, args=(self.app.brain.anthropic_client,), daemon=True)
        worker.start()
        worker.join(timeout=25)
        self.memory.save(force=True)
