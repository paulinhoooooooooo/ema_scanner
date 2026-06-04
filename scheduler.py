#!/usr/bin/env python3
"""
Planificateur — lance le scan EMA chaque soir à l'heure configurée.
Lance ce script une fois, il tourne en arrière-plan indéfiniment.
"""

import json
import time
import logging
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
LOG_FILE = BASE_DIR / "scheduler.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SCHEDULER] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def charger_heure():
    with open(CONFIG_FILE, "r") as f:
        cfg = json.load(f)
    heure_str = cfg["scan"]["heure"]
    tz_str    = cfg["scan"]["timezone"]
    heure, minute = map(int, heure_str.split(":"))
    return heure, minute, tz_str


def prochain_scan(heure, minute, tz_str):
    tz = ZoneInfo(tz_str)
    now = datetime.now(tz)
    cible = now.replace(hour=heure, minute=minute, second=0, microsecond=0)
    if now >= cible:
        from datetime import timedelta
        cible += timedelta(days=1)
    return cible


def main():
    log.info("Planificateur EMA démarré.")
    dernier_scan = None

    while True:
        try:
            heure, minute, tz_str = charger_heure()
            tz = ZoneInfo(tz_str)
            now = datetime.now(tz)
            aujourd_hui = date.today()

            # Lancer le scan si c'est l'heure et pas encore fait aujourd'hui
            if now.hour == heure and now.minute == minute and dernier_scan != aujourd_hui:
                log.info(f"Lancement du scan ({heure:02d}:{minute:02d})...")
                dernier_scan = aujourd_hui
                script = BASE_DIR / "scanner.py"
                subprocess.run([sys.executable, str(script)], check=False)
                log.info("Scan terminé.")

            # Afficher le prochain scan toutes les heures
            if now.minute == 0 and now.second < 60:
                cible = prochain_scan(heure, minute, tz_str)
                delta = cible - now
                h, m = divmod(int(delta.total_seconds()) // 60, 60)
                log.info(f"Prochain scan dans {h}h{m:02d}m ({cible.strftime('%d/%m %H:%M')})")

        except Exception as e:
            log.error(f"Erreur planificateur : {e}")

        time.sleep(30)  # vérifie toutes les 30 secondes


if __name__ == "__main__":
    main()
