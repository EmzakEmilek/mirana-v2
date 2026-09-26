"""Vytvori odkaz MIRANA na ploche a v Start menu (spusti gui.py cez pythonw.exe, bez konzoly).

Spustenie raz po instalacii:  venv\\Scripts\\python install_shortcut.py
Odinstalovanie: zmaz "MIRANA.lnk" z plochy a zo Start menu (%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs).
"""

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PYTHONW = BASE / "venv" / "Scripts" / "pythonw.exe"
ICON = BASE / "assets" / "mirana.ico"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create(folder_expr: str) -> str:
    script = f"""
$dir = {folder_expr}
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $dir 'MIRANA.lnk'))
$lnk.TargetPath = {_ps_quote(str(PYTHONW))}
$lnk.Arguments = {_ps_quote('"' + str(BASE / 'gui.py') + '"')}
$lnk.WorkingDirectory = {_ps_quote(str(BASE))}
$lnk.IconLocation = {_ps_quote(str(ICON) + ',0')}
$lnk.Description = 'MIRANA - AI partacka pre Cyberpunk stream'
$lnk.Save()
Join-Path $dir 'MIRANA.lnk'
"""
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


if __name__ == "__main__":
    if not PYTHONW.exists():
        sys.exit(f"Chyba {PYTHONW} — najprv vytvor venv (pozri README).")
    # GetFolderPath vrati aj plochu presmerovanu do OneDrive
    print("Plocha:   ", create("[Environment]::GetFolderPath('Desktop')"))
    print("Start menu:", create("[Environment]::GetFolderPath('Programs')"))
