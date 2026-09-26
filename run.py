"""Supervisor: spusti main.py a pri pade alebo zamrznuti ho restartuje.

- pad (nenulovy exit kod) -> restart o 3 s
- zamrznutie: hlavna slucka v main.py kazdych <=5 s zapisuje data/heartbeat; ked je starsi nez
  HEARTBEAT_TIMEOUT_SEC, proces sa zabije a spusti znova
- najviac MAX_RESTARTS_PER_HOUR restartov za hodinu, potom supervisor skonci (nieco je zle natrvalo)
- Ctrl+C alebo riadne ukoncenie main.py (exit 0) = koniec; "Mirana uz bezi" (exit 3) = koniec

Spustenie: start.bat, alebo  venv\\Scripts\\python run.py
"""

import os
import subprocess
import sys

# Spustenie z ikony (pythonw.exe) nema konzolu: sys.stdout/stderr su None a niektore kniznice
# (tqdm pri stahovani modelu, print) by padli. Vystup ide do prazdna, vsetko podstatne je v logs/.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import time
from collections import deque
from datetime import datetime

from core.config import BASE_DIR
from core.session import EXIT_ALREADY_RUNNING, HEARTBEAT_PATH, LOGS_DIR

HEARTBEAT_TIMEOUT_SEC = 60
STARTUP_GRACE_SEC = 90        # nacitanie Whispera a fillerov, heartbeat este nebezi
MAX_RESTARTS_PER_HOUR = 5
CHECK_EVERY_SEC = 5


def log(message: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} SUPERVISOR: {message}"
    print(line, flush=True)
    LOGS_DIR.mkdir(exist_ok=True)
    with open(LOGS_DIR / "supervisor.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def heartbeat_age() -> float | None:
    try:
        return time.time() - HEARTBEAT_PATH.stat().st_mtime
    except OSError:
        return None


def run_once() -> int:
    """Spusti main.py a strazi ho. Vrati exit kod (alebo -1 pri zabiti pre zamrznutie)."""
    started = time.time()
    proc = subprocess.Popen([sys.executable, "-u", str(BASE_DIR / "main.py")], cwd=BASE_DIR)
    try:
        while proc.poll() is None:
            time.sleep(CHECK_EVERY_SEC)
            age = heartbeat_age()
            if time.time() - started > STARTUP_GRACE_SEC and (age is None or age > HEARTBEAT_TIMEOUT_SEC):
                log(f"main.py zamrzla (heartbeat {age if age is None else round(age)} s), zabijam proces")
                proc.kill()
                proc.wait()
                return -1
        return proc.returncode
    except KeyboardInterrupt:
        proc.wait(timeout=10)  # Ctrl+C dostane aj main.py a skonci sama
        raise


def main() -> None:
    restarts: deque[float] = deque()
    log("start")
    while True:
        try:
            code = run_once()
        except KeyboardInterrupt:
            log("ukoncene cez Ctrl+C")
            return
        if code == 0:
            log("main.py skoncila riadne")
            return
        if code == EXIT_ALREADY_RUNNING:
            log("Mirana uz bezi v inom okne — nic nespustam")
            return
        now = time.time()
        restarts.append(now)
        while restarts and now - restarts[0] > 3600:
            restarts.popleft()
        if len(restarts) > MAX_RESTARTS_PER_HOUR:
            log(f"{len(restarts)} restartov za hodinu — koncim, pozri logs/")
            sys.exit(1)
        log(f"main.py skoncila s kodom {code}, restart {len(restarts)}/{MAX_RESTARTS_PER_HOUR} o 3 s")
        time.sleep(3)


if __name__ == "__main__":
    main()
