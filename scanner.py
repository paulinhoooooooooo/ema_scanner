#!/usr/bin/env python3
#!/usr/bin/env python3
"""
EMA Scanner — Détection de croisements EMA entre elles
Surveille EMA55 vs EMA21, EMA13, EMA8
Envoie des notifications Telegram dès qu'un signal est détecté.
"""

import json
import sys
import time
import logging
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
TICKERS_FILE = BASE_DIR / "tickers.txt"
LOG_FILE = BASE_DIR / "scanner.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def charger_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def charger_tickers():
    tickers = []
    with open(TICKERS_FILE, "r", encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if ligne and not ligne.startswith("#"):
                tickers.append(ligne.upper())
    return list(dict.fromkeys(tickers))

def calc_ema(serie, periode):
    return serie.ewm(span=periode, adjust=False).mean()

def calc_rsi(closes, periode=14):
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=periode - 1, min_periods=periode).mean()
    avg_loss = loss.ewm(com=periode - 1, min_periods=periode).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1)

def calc_adx(df, periode=14):
    high = df["High"].squeeze().astype(float)
    low = df["Low"].squeeze().astype(float)
    close = df["Close"].squeeze().astype(float)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    atr = tr.ewm(alpha=1/periode, min_periods=periode).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/periode, min_periods=periode).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/periode, min_periods=periode).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1/periode, min_periods=periode).mean()
    return round(float(adx.iloc[-1]), 1)

def telecharger_donnees(ticker, config):
    tf = config["scan"]["timeframe"]
    periode = config["scan"]["periode_historique"]
    try:
        df = yf.download(ticker, period=periode, interval=tf, progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            log.warning(f"{ticker} — données insuffisantes ({len(df)} bougies)")
            return None
        df = df.dropna()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        log.error(f"{ticker} — erreur téléchargement : {e}")
        return None

def analyser(ticker, df, config):
    cfg_ema = config["ema"]
    cfg_sig = config["signaux"]
    cfg_fil = config["filtres"]

    closes = df["Close"].squeeze()
    if isinstance(closes, pd.DataFrame):
        closes = closes.iloc[:, 0]
    closes = closes.dropna().astype(float)

    volumes = df["Volume"].squeeze()
    if isinstance(volumes, pd.DataFrame):
        volumes = volumes.iloc[:, 0]
    volumes = volumes.dropna().astype(float)

    ema8  = calc_ema(closes, cfg_ema["ema8"])
    ema13 = calc_ema(closes, cfg_ema["ema13"])
    ema21 = calc_ema(closes, cfg_ema["ema21"])
    ema55 = calc_ema(closes, cfg_ema["ema55"])

    prix_actuel = float(closes.iloc[-1])
    rsi = calc_rsi(closes)
    adx = calc_adx(df)

    vol_actuel = float(volumes.iloc[-1])
    vol_moy    = float(volumes.iloc[-20:].mean())

    ok_volume = (not cfg_fil["volume_actif"]) or (vol_actuel >= vol_moy * cfg_fil["volume_multiplicateur"])
    ok_rsi    = (not cfg_fil["rsi_actif"])    or (cfg_fil["rsi_min"] <= rsi <= cfg_fil["rsi_max"])
    ok_adx    = (not cfg_fil["adx_actif"])    or (adx >= cfg_fil["adx_min"])
    filtres_ok = ok_volume and ok_rsi and ok_adx

    marge = cfg_sig["anticipation_marge_pct"]
    signaux = []

    # Paires : EMA55 comparée à chaque EMA rapide
    paires = [
        (ema21, "EMA21"),
        (ema13, "EMA13"),
        (ema8,  "EMA8"),
    ]

    for ema_rapide, label in paires:
        e55_act = float(ema55.iloc[-1])
        e55_pre = float(ema55.iloc[-2])
        er_act  = float(ema_rapide.iloc[-1])
        er_pre  = float(ema_rapide.iloc[-2])
        gap_pct = abs(e55_act - er_act) / er_act * 100

        # Signal HAUSSIER : EMA55 repasse au-dessus de l'EMA rapide
        if cfg_sig["long_actif"] and filtres_ok:
            if e55_pre <= er_pre and e55_act > er_act:
                signaux.append({
                    "emoji": "🟢",
                    "titre": f"Croisement Haussier — {ticker}",
                    "detail": (
                        f"EMA55 ({e55_act:.2f}) vient de passer AU-DESSUS de {label} ({er_act:.2f})\n"
                        f"Prix : {prix_actuel:.2f} | RSI : {rsi} | ADX : {adx}"
                    )
                })

        # Signal BAISSIER : EMA55 passe en dessous de l'EMA rapide
        if cfg_sig["short_actif"] and filtres_ok:
            if e55_pre >= er_pre and e55_act < er_act:
                signaux.append({
                    "emoji": "🔴",
                    "titre": f"Croisement Baissier — {ticker}",
                    "detail": (
                        f"EMA55 ({e55_act:.2f}) vient de passer EN-DESSOUS de {label} ({er_act:.2f})\n"
                        f"Prix : {prix_actuel:.2f} | RSI : {rsi} | ADX : {adx}"
                    )
                })

        # Anticipation : EMA55 s'approche de l'EMA rapide
        if cfg_sig["anticipation_actif"] and gap_pct <= marge:
            # Pas encore croisé
            if (e55_act > er_act) == (e55_pre > er_pre):
                direction = "baissier" if e55_act > er_act else "haussier"
                emoji_ant = "⚠️🔴" if direction == "baissier" else "⚠️🟢"
                signaux.append({
                    "emoji": emoji_ant,
                    "titre": f"Anticipation {direction} — {ticker}",
                    "detail": (
                        f"EMA55 ({e55_act:.2f}) à {gap_pct:.2f}% de {label} ({er_act:.2f})\n"
                        f"Croisement {direction} imminent\n"
                        f"Prix : {prix_actuel:.2f} | RSI : {rsi} | ADX : {adx}"
                    )
                })

    return signaux

def envoyer_telegram(message, config):
    token   = config["telegram"]["bot_token"]
    chat_id = config["telegram"]["chat_id"]
    if "REMPLACE" in str(token) or "REMPLACE" in str(chat_id):
        log.warning("Telegram non configuré")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        log.error(f"Telegram exception : {e}")
        return False

def formater_message(signal):
    return (
        f"{signal['emoji']} <b>{signal['titre']}</b>\n\n"
        f"{signal['detail']}\n\n"
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )

def lancer_scan():
    config  = charger_config()
    tickers = charger_tickers()
    log.info(f"=== Scan démarré — {len(tickers)} tickers ===")

    total_signaux = 0

    for i, ticker in enumerate(tickers, 1):
        log.info(f"[{i}/{len(tickers)}] Analyse de {ticker}...")
        df = telecharger_donnees(ticker, config)
        if df is None:
            continue
        try:
            signaux = analyser(ticker, df, config)
            for sig in signaux:
                total_signaux += 1
                message = formater_message(sig)
                ok = envoyer_telegram(message, config)
                log.info(f"  → {sig['titre']} — Telegram {'OK' if ok else 'ECHEC'}")
                time.sleep(0.5)
        except Exception as e:
            log.error(f"{ticker} — erreur analyse : {e}")
        time.sleep(0.3)

    if total_signaux == 0:
        log.info("Aucun signal détecté.")
        if config["telegram"].get("envoyer_resume", False):
            envoyer_telegram(
                f"✅ <b>Scan terminé</b>\n{len(tickers)} titres analysés — aucun signal.\n"
                f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                config
            )
    else:
        log.info(f"=== Scan terminé — {total_signaux} signal(s) ===")

if __name__ == "__main__":
    lancer_scan()
