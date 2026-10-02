"""Spustenie Mirany (bez okna). Bezne ju spusta supervisor run.py, ten zas ovladacie okno gui.py."""

import os
import sys

# Spustenie z ikony (pythonw.exe) nema konzolu: sys.stdout/stderr su None a niektore kniznice
# (tqdm pri stahovani modelu, print) by padli. Vystup ide do prazdna, vsetko podstatne je v logs/.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from mirana.app import main  # noqa: E402

if __name__ == "__main__":
    main()
