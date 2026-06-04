#!/usr/bin/env python3
"""
EMA Scanner — Détection de croisements et anticipations
Envoie des notifications Telegram dès qu'un signal est détecté.
"""

import json
import os
import sys
import time
import logging
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

# --- Chemins ---
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
TICKERS_FILE = BASE_DIR / "tickers.txt"
LOG_FILE = BASE_DIR / "scanner.log"

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# CHARGEMENT CONFIG & TICKERS
# ─────────────────────────────────────────────

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
    return list(dict.fromkeys(tickers))  # supprime doublons


# ─────────────────────────────────────────────
# CALCUL DES INDICATEURS
# ─────────────────────────────────────────────

def calc_ema(serie: pd.Series, periode: int) -> pd.Series:
    return serie.ewm(span=periode, adjust=False).mean()

def calc_rsi(closes: pd.Series, periode: int = 14) -> float:
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=periode - 1, min_periods=periode).mean()
    avg_loss = loss.ewm(com=periode - 1, min_periods=periode).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1)

def calc_adx(df: pd.DataFrame, periode: int = 14) -> float:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
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


# ─────────────────────────────────────────────
# RÉCUPÉRATION DONNÉES
# ─────────────────────────────────────────────

def telecharger_donnees(ticker: str, config: dict):
    tf = config["scan"]["timeframe"]
    periode = config["scan"]["periode_historique"]
    try:
        df = yf.download(ticker, period=periode, interval=tf, progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            log.warning(f"{ticker} — données insuffisantes ({len(df)} bougies)")
            return None
        df = df.dropna()
        # Aplatir le MultiIndex si présent (yfinance >= 0.2.x)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        log.error(f"{ticker} — erreur téléchargement : {e}")
        return None


# ─────────────────────────────────────────────
# DÉTECTION DES SIGNAUX
# ─────────────────────────────────────────────

def analyser(ticker: str, df: pd.DataFrame, config: dict) -> list:
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

    ema_courte = calc_ema(closes, cfg_ema["courte"])
    ema_longue = calc_ema(closes, cfg_ema["longue"])
    ema_tendance = calc_ema(closes, cfg_ema["tendance"])

    prix_actuel = float(closes.iloc[-1])
    prix_prev    = float(closes.iloc[-2])
    ema_l_actuel = float(ema_longue.iloc[-1])
    ema_l_prev   = float(ema_longue.iloc[-2])
    ema_c_actuel = float(ema_courte.iloc[-1])
    ema_c_prev   = float(ema_courte.iloc[-2])
    ema_t_actuel = float(ema_tendance.iloc[-1])

    vol_actuel = float(volumes.iloc[-1])
    vol_moy    = float(volumes.iloc[-20:].mean())

    rsi = calc_rsi(closes)
    adx = calc_adx(df)

    seuil = cfg_sig["seuil_confirmation_pct"]
    signaux = []

    # ── Filtres optionnels ──
    ok_volume = (not cfg_fil["volume_actif"]) or (vol_actuel >= vol_moy * cfg_fil["volume_multiplicateur"])
    ok_rsi    = (not cfg_fil["rsi_actif"])    or (cfg_fil["rsi_min"] <= rsi <= cfg_fil["rsi_max"])
    ok_adx    = (not cfg_fil["adx_actif"])    or (adx >= cfg_fil["adx_min"])
    filtres_ok = ok_volume and ok_rsi and ok_adx

    ecart_prix_pct = abs(prix_actuel - ema_l_actuel) / ema_l_actuel * 100

    # ── Signal LONG : prix croise au-dessus EMA longue ──
    if cfg_sig["long_actif"] and filtres_ok:
        if prix_prev <= ema_l_prev and prix_actuel > ema_l_actuel and ecart_prix_pct >= seuil:
            signaux.append({
                "type": "LONG",
                "emoji": "🟢",
                "titre": f"Signal Long — {ticker}",
                "detail": (
                    f"Prix {prix_actuel:.2f} vient de passer au-dessus de l'EMA{cfg_ema['longue']} ({ema_l_actuel:.2f})\n"
                    f"Écart : +{ecart_prix_pct:.1f}% | EMA{cfg_ema['tendance']} : {ema_t_actuel:.2f}\n"
                    f"RSI : {rsi} | ADX : {adx}"
                )
            })

    # ── Signal SHORT : prix croise en dessous EMA longue ──
    if cfg_sig["short_actif"] and filtres_ok:
        if prix_prev >= ema_l_prev and prix_actuel < ema_l_actuel and ecart_prix_pct >= seuil:
            signaux.append({
                "type": "SHORT",
                "emoji": "🔴",
                "titre": f"Signal Short — {ticker}",
                "detail": (
                    f"Prix {prix_actuel:.2f} vient de passer sous l'EMA{cfg_ema['longue']} ({ema_l_actuel:.2f})\n"
                    f"Écart : -{ecart_prix_pct:.1f}% | EMA{cfg_ema['tendance']} : {ema_t_actuel:.2f}\n"
                    f"RSI : {rsi} | ADX : {adx}"
                )
            })

    # ── Anticipation : EMA courte proche de l'EMA longue ──
    if cfg_sig["anticipation_actif"]:
        gap_pct = abs(ema_c_actuel - ema_l_actuel) / ema_l_actuel * 100
        marge   = cfg_sig["anticipation_marge_pct"]
        if gap_pct <= marge:
            direction = "haussier" if ema_c_actuel < ema_l_actuel else "baissier"
            emoji_ant = "⚠️🟢" if direction == "haussier" else "⚠️🔴"
            signaux.append({
                "type": f"ANTICIPATION_{direction.upper()}",
                "emoji": emoji_ant,
                "titre": f"Anticipation croisement {direction} — {ticker}",
                "detail": (
                    f"EMA{cfg_ema['courte']} ({ema_c_actuel:.2f}) à seulement {gap_pct:.2f}% de EMA{cfg_ema['longue']} ({ema_l_actuel:.2f})\n"
                    f"Croisement {direction} imminent\n"
                    f"Prix : {prix_actuel:.2f} | RSI : {rsi} | ADX : {adx}"
                )
            })

    return signaux


# ─────────────────────────────────────────────
# NOTIFICATIONS TELEGRAM
# ─────────────────────────────────────────────

def envoyer_telegram(message: str, config: dict) -> bool:
    token   = config["telegram"]["bot_token"]
    chat_id = config["telegram"]["chat_id"]
    if "REMPLACE" in token or "REMPLACE" in str(chat_id):
        log.warning("Telegram non configuré — message non envoyé")
        log.info(f"MESSAGE : {message}")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        if resp.status_code == 200:
            return True
        else:
            log.error(f"Telegram erreur {resp.status_code} : {resp.text}")
            return False
    except Exception as e:
        log.error(f"Telegram exception : {e}")
        return False

def formater_message(signal: dict, ticker: str) -> str:
    return (
        f"{signal['emoji']} <b>{signal['titre']}</b>\n\n"
        f"{signal['detail']}\n\n"
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )


# ─────────────────────────────────────────────
# SCAN PRINCIPAL
# ─────────────────────────────────────────────

def lancer_scan():
    config  = charger_config()
    tickers = charger_tickers()
    log.info(f"=== Scan démarré — {len(tickers)} tickers ===")

    total_signaux = 0
    resultats = []

    for i, ticker in enumerate(tickers, 1):
        log.info(f"[{i}/{len(tickers)}] Analyse de {ticker}...")
        df = telecharger_donnees(ticker, config)
        if df is None:
            continue
        try:
            signaux = analyser(ticker, df, config)
            for sig in signaux:
                total_signaux += 1
                message = formater_message(sig, ticker)
                ok = envoyer_telegram(message, config)
                resultats.append({
                    "ticker": ticker,
                    "type": sig["type"],
                    "envoyé": ok
                })
                log.info(f"  → {sig['type']} détecté — Telegram {'OK' if ok else 'ECHEC'}")
                time.sleep(0.5)  # évite le rate-limit Telegram
        except Exception as e:
            log.error(f"{ticker} — erreur analyse : {e}")
        time.sleep(0.3)  # évite le rate-limit Yahoo Finance

    # ── Résumé ──
    if total_signaux == 0:
        log.info("Aucun signal détecté ce soir.")
        # Message de confirmation que le scan a bien tourné (optionnel)
        config2 = charger_config()
        if config2["telegram"].get("envoyer_resume", False):
            envoyer_telegram(
                f"✅ <b>Scan terminé</b>\n{len(tickers)} titres analysés — aucun signal ce soir.\n"
                f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                config
            )
    else:
        log.info(f"=== Scan terminé — {total_signaux} signal(s) envoyé(s) ===")

    return resultats


if __name__ == "__main__":
    lancer_scan()
