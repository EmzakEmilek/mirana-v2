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

BASE = {
    "in_game": True, "mod_version": 1, "hp": 100, "hp_max": 310, "level": 3, "street_cred": 2, "money": 1200,
    "lifepath": "StreetKid", "district": "Watson", "subdistrict": "Kabuki",
    "quest": "The Ride", "objective": "Get in Jackie's car", "combat": False, "vehicle": None, "weapon": "Unity",
}

# (sekundy, zmeny) — kazdy krok trva dany cas, stav sa zapisuje kazdu sekundu
SCENARIO = [
    (6, {}),
    (6, {"vehicle": "Mizutani Shion", "objective": "Drive to the meeting point"}),
    (5, {"vehicle": None, "subdistrict": "Little China"}),
    (4, {"combat": True, "hp": 70}),
    (4, {"hp": 40}),
    (5, {"hp": 22}),               # hp_low
    (6, {"hp": 8}),                # hp_critical
    (6, {"hp": 65}),
    (6, {"combat": False, "hp": 80}),
    (6, {"level": 4, "street_cred": 3}),
    (8, {"quest": "The Pickup", "objective": "Meet with Jackie at Lizzie's Bar"}),
    (8, {"district": "Pacifica", "subdistrict": "West Wind Estate", "quest": "I Walk the Line",
         "objective": "Talk to Placide"}),
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
