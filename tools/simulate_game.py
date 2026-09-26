"""Simulator CET modu: zapisuje state.json ako mod v hre, aby sa telemetria dala skusat bez hry.

  venv\\Scripts\\python tools\\simulate_game.py                 # scenar (jazda, boj, nizke HP, level, quest)
  venv\\Scripts\\python tools\\simulate_game.py --static        # stale rovnaky stav (na otazky s telemetriou)
  venv\\Scripts\\python tools\\simulate_game.py --path C:\\...\\state.json

Predvolena cesta je data/sim_state.json — v okne Nastavenia -> Hra nastav tuto cestu, alebo
spusti Miranu s MIRANA_GAME_STATE_PATH (pozri inputs/game_state.py).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import BASE_DIR  # noqa: E402

DEFAULT_PATH = BASE_DIR / "data" / "sim_state.json"

# Nazvy ako z hry s ceskym prekladom (tak ich posiela skutocny mod)
BASE = {
    "in_game": True, "mod_version": 2, "hp": 100, "hp_max": 310, "level": 3, "street_cred": 2, "money": 1200,
    "lifepath": "StreetKid", "district": "Watson", "subdistrict": "Kabuki", "time": "21:40", "weather": "24h_weather_rain",
    "quest": "Jízda", "quest_id": "q001_intro", "quest_type": "MainQuest", "objective": "Nastup do Jackieho auta",
    "combat": False, "scene_tier": 1, "wanted": 0, "vehicle": None, "weapon": "Unity", "ammo": 12, "ammo_max": 12, "ammo_reserve": True,
    "heal_charges": 2, "heal_max": 3, "grenade_charges": 1, "grenade_max": 2, "ram": 6, "ram_max": 6,
    "attributes": {"body": 4, "reflexes": 6, "tech": 3, "intelligence": 5, "cool": 3},
    "perk_points": 0, "attribute_points": 0, "cyberware_capacity": 50, "cyberware_free": 18,
    "os": "Militech Paraline", "weapons": ["Unity", "Copperhead"], "armor": 120,
    "story": {"main_done": [{"id": "q000_tutorial", "title": "Uličník"}], "side_done": 0},
}

# (sekundy, zmeny) — kazdy krok trva dany cas, stav sa zapisuje kazdu sekundu
SCENARIO = [
    (6, {}),
    (6, {"vehicle": "Mizutani Shion", "driver": False, "speed_kmh": 74, "radio": "92.9 Night FM",
         "objective": "Dojeď na místo schůzky"}),
    (5, {"vehicle": None, "speed_kmh": None, "radio": None, "subdistrict": "Little China", "scene_tier": 4}),  # cutscena
    (4, {"scene_tier": 1, "combat": True, "hp": 70, "target": {"name": "Tyger Claws", "kind": "npc", "hostile": True, "level": 4, "hp": 60}}),
    (4, {"hp": 40, "wanted": 2}),   # wanted_up
    (5, {"hp": 22, "heal_charges": 1}),               # hp_low
    (6, {"hp": 8, "heal_charges": 0, "ammo": 0}),     # hp_critical
    (6, {"hp": 65, "target": None}),
    (6, {"combat": False, "hp": 80, "wanted": 0}),    # wanted_clear
    (6, {"level": 4, "street_cred": 3, "perk_points": 1, "attribute_points": 1}),
    (8, {"quest": "Vyzvednutí", "quest_id": "q003_maelstrom", "objective": "Setkej se s Jackiem v Lizzie's Baru",
         "story": {"main_done": [{"id": "q000_tutorial", "title": "Uličník"}, {"id": "q001_intro", "title": "Jízda"}], "side_done": 1}}),
    (8, {"quest": "Neobjevené", "quest_id": None, "objective": "Kdo ví, co se tu skrývá?"}),  # pseudo-quest
    (8, {"district": "Pacifika", "subdistrict": "Westwindská osada", "quest": "Kráčím po hraně",
         "quest_id": "q110_voodoo", "objective": "Promluv si s Placidem", "time": "03:15", "weather": "24h_weather_fog"}),
]


def write(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**state, "ts": int(time.time())}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--static", action="store_true", help="stale rovnaky stav")
    parser.add_argument("--speed", type=float, default=1.0, help="2 = scenar dvakrat rychlejsie")
    args = parser.parse_args()
    args.path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(BASE)
    print(f"zapisujem {args.path}  (Ctrl+C = koniec)")
    try:
        if args.static:
            while True:
                write(args.path, state)
                time.sleep(1)
        for seconds, changes in SCENARIO:
            state.update(changes)
            print(f"  {changes or 'start'}")
            end = time.time() + seconds / args.speed
            while time.time() < end:
                write(args.path, state)
                time.sleep(1)
        print("scenar skoncil, stav ostava (Ctrl+C = koniec)")
        while True:
            write(args.path, state)
            time.sleep(1)
    except KeyboardInterrupt:
        write(args.path, {**state, "in_game": False})


if __name__ == "__main__":
    main()
