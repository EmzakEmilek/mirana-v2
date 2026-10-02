"""Stare logy do ZIP archivu: logs/archive/<rok-mesiac>.zip (nic sa nemaze bez overenej kopie).

Pri starte Mirany na pozadi: logy sessions (mirana-*.log, rozhovor-*.jsonl, chat-*.jsonl) a momenty
na strih (strih-*.md) starsie ako logging.archive_after_days idu do archivu podla mesiaca. Posledne
KEEP_SESSIONS sessions ostavaju vzdy (dlhodoba pamat z nich doplna zhrnutie). Original sa zmaze az
ked je v ZIP-e a sedi velkost. poznamky.md a supervisor.log ostavaju.
"""

import logging
import re
import threading
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from mirana.features import Feature
from mirana.session import LOGS_DIR

logger = logging.getLogger(__name__)

PATTERN = re.compile(r"^(?:(?:mirana|rozhovor|chat)-(\d{8})-(\d{6})\.(?:log|jsonl)|strih-(\d{8})\.md)$")
KEEP_SESSIONS = 4


def archive_logs(logs_dir: Path, after_days: int, today: date | None = None) -> list[str]:
    """Presunie stare logy do logs/archive/<YYYY-MM>.zip. Vrati mena archivovanych suborov."""
    cutoff = (today or date.today()) - timedelta(days=after_days)
    candidates, sessions = [], set()
    for path in sorted(logs_dir.glob("*")):
        m = PATTERN.match(path.name)
        if not m or not path.is_file():
            continue
        if m.group(1):
            sessions.add(f"{m.group(1)}-{m.group(2)}")
        day = datetime.strptime(m.group(1) or m.group(3), "%Y%m%d").date()
        if day < cutoff:
            candidates.append((day, path, f"{m.group(1)}-{m.group(2)}" if m.group(1) else None))
    keep = set(sorted(sessions)[-KEEP_SESSIONS:])
    by_month: dict[str, list[Path]] = {}
    for day, path, sid in candidates:
        if sid not in keep:
            by_month.setdefault(f"{day:%Y-%m}", []).append(path)

    archived = []
    for month, paths in by_month.items():
        target = logs_dir / "archive" / f"{month}.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED) as z:
            present = set(z.namelist())
            for path in paths:
                if path.name not in present:
                    z.write(path, arcname=path.name)
        with zipfile.ZipFile(target) as z:  # kontrola: subor je v archive, cely a citatelny
            if z.testzip() is not None:
                logger.warning("archiv %s je poskodeny, logy ostavaju", target.name)
                continue
            sizes = {i.filename: i.file_size for i in z.infolist()}
        for path in paths:
            if sizes.get(path.name) == path.stat().st_size:
                path.unlink()
                archived.append(path.name)
    return archived


class LogArchive(Feature):
    def start(self) -> None:
        days = int(self.app.config["logging"]["archive_after_days"])

        def run():
            try:
                done = archive_logs(LOGS_DIR, days)
                if done:
                    logger.info("archiv logov: %d suborov starsich ako %d dni -> logs/archive/", len(done), days)
            except Exception:
                logger.exception("archivacia logov zlyhala (logy ostavaju)")
        threading.Thread(target=run, name="log-archive", daemon=True).start()
