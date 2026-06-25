#!/usr/bin/env python3
"""
EMA Analyser — Backtest cycles haussiers/baissiers avec rendement BB
Génère un document de performance par cycle détecté.
"""

import json
import sys
import argparse
import yfinance as yf
import pandas as pd
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
TICKERS_FILE = BASE_DIR / "tickers.txt"


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
    return rsi.round(1)


def calc_adx(df, periode=14):
    high  = df["High"].squeeze().astype(float)
    low   = df["Low"].squeeze().astype(float)
    close = df["Close"].squeeze().astype(float)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    plus_dm  = high.diff()
    minus_dm = -low.diff()
    plus_dm  = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    atr      = tr.ewm(alpha=1/periode, min_periods=periode).mean()
    plus_di  = 100 * plus_dm.ewm(alpha=1/periode, min_periods=periode).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/periode, min_periods=periode).mean() / atr
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx      = dx.ewm(alpha=1/periode, min_periods=periode).mean()
    return adx.round(1)


def calc_bollinger(closes, periode=20, nb_ecarts=2):
    sma = closes.rolling(window=periode).mean()
    std = closes.rolling(window=periode).std()
    bande_haute = sma + nb_ecarts * std
    bande_basse = sma - nb_ecarts * std
    return bande_haute, bande_basse


def telecharger_donnees(ticker, config, periode="1y"):
    tf = config["scan"]["timeframe"]
    try:
        df = yf.download(ticker, period=periode, interval=tf, progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            print(f"[WARN] {ticker} — données insuffisantes ({len(df)} bougies)")
            return None
        df = df.dropna()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f"[ERR] {ticker} — erreur téléchargement : {e}")
        return None


def analyser_cycles(ticker, df, config, mode="both"):
    """
    Backtest complet par cycle.

    mode : "long"  → uniquement cycles haussiers
           "short" → uniquement cycles baissiers
           "both"  → les deux
    """
    cfg_ema = config["ema"]
    cfg_bol = config.get("bollinger", {"periode": 20, "ecarts": 2, "actif": True})
    bb_periode = cfg_bol["periode"]
    bb_ecarts  = cfg_bol["ecarts"]

    closes  = df["Close"].squeeze().astype(float)
    volumes = df["Volume"].squeeze().astype(float)

    ema8  = calc_ema(closes, cfg_ema["ema8"])
    ema13 = calc_ema(closes, cfg_ema["ema13"])
    ema21 = calc_ema(closes, cfg_ema["ema21"])
    ema55 = calc_ema(closes, cfg_ema["ema55"])

    rsi_series = calc_rsi(closes)
    adx_series = calc_adx(df)

    bande_haute, bande_basse = calc_bollinger(closes, bb_periode, bb_ecarts)

    cycles = []
    cycle_actif = None

    for i in range(1, len(df)):
        date  = df.index[i]
        prix  = float(closes.iloc[i])
        prix_pre = float(closes.iloc[i - 1])

        e55 = float(ema55.iloc[i])
        e8  = float(ema8.iloc[i])
        e13 = float(ema13.iloc[i])
        e21 = float(ema21.iloc[i])

        e55_pre = float(ema55.iloc[i - 1])
        e8_pre  = float(ema8.iloc[i - 1])
        e13_pre = float(ema13.iloc[i - 1])
        e21_pre = float(ema21.iloc[i - 1])

        haussier_act = e55 < e8  and e55 < e13  and e55 < e21
        baissier_act = e55 > e8  and e55 > e13  and e55 > e21
        haussier_pre = e55_pre < e8_pre and e55_pre < e13_pre and e55_pre < e21_pre
        baissier_pre = e55_pre > e8_pre and e55_pre > e13_pre and e55_pre > e21_pre

        rsi = float(rsi_series.iloc[i]) if not pd.isna(rsi_series.iloc[i]) else 0.0
        adx = float(adx_series.iloc[i]) if not pd.isna(adx_series.iloc[i]) else 0.0
        vol_ratio = float(volumes.iloc[i]) / float(volumes.iloc[max(0, i-20):i].mean()) if i >= 20 else 1.0

        bh = float(bande_haute.iloc[i]) if not pd.isna(bande_haute.iloc[i]) else None
        bb = float(bande_basse.iloc[i]) if not pd.isna(bande_basse.iloc[i]) else None

        # --- Détection début / fin de cycles ---

        # Début cycle haussier
        if mode in ("long", "both") and not haussier_pre and haussier_act:
            if cycle_actif:
                cycles.append(cycle_actif)
            cycle_actif = {
                "type": "haussier",
                "debut": date,
                "jours": [],
            }

        # Début cycle baissier
        if mode in ("short", "both") and not baissier_pre and baissier_act:
            if cycle_actif:
                cycles.append(cycle_actif)
            cycle_actif = {
                "type": "baissier",
                "debut": date,
                "jours": [],
            }

        # Fin de cycle (sortie)
        if cycle_actif:
            if cycle_actif["type"] == "haussier" and not haussier_act:
                cycles.append(cycle_actif)
                cycle_actif = None
            elif cycle_actif["type"] == "baissier" and not baissier_act:
                cycles.append(cycle_actif)
                cycle_actif = None

        # Enregistrement du jour dans le cycle actif
        if cycle_actif:
            # Rendement journalier
            rendement = (prix / prix_pre - 1) * 100
            if cycle_actif["type"] == "baissier":
                # En short, le gain est l'inverse du mouvement prix
                rendement = -rendement

            # Touche BB
            # LONG  : prix touche la BANDE BASSE  (survente en haussier)
            # SHORT : prix touche la BANDE HAUTE  (surachat en baissier)
            touche_bb = False
            if cfg_bol.get("actif", True):
                if cycle_actif["type"] == "haussier" and bb is not None:
                    touche_bb = prix <= bb
                elif cycle_actif["type"] == "baissier" and bh is not None:
                    touche_bb = prix >= bh   # ← correction clé : bande HAUTE en short

            cycle_actif["jours"].append({
                "date":      date,
                "prix":      prix,
                "rendement": rendement,
                "rsi":       rsi,
                "adx":       adx,
                "vol":       round(vol_ratio, 2),
                "touche_bb": touche_bb,
            })

    if cycle_actif:
        cycles.append(cycle_actif)

    return cycles


def formater_document(ticker, cycles, mode="both"):
    lignes = []
    lignes.append("=" * 60)
    lignes.append(f"  EMA ANALYSER — {ticker}")
    mode_label = {"long": "HAUSSIER", "short": "BAISSIER", "both": "HAUSSIER + BAISSIER"}
    lignes.append(f"  Mode : {mode_label.get(mode, mode.upper())}")
    lignes.append(f"  Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    lignes.append("=" * 60)

    total_rendement = 0.0
    nb_cycles = 0
    nb_bb_touches = 0

    for cycle in cycles:
        if not cycle["jours"]:
            continue

        type_cycle = cycle["type"].upper()
        debut = cycle["debut"].strftime("%d/%m/%Y")
        fin   = cycle["jours"][-1]["date"].strftime("%d/%m/%Y")
        rendement_cycle = sum(j["rendement"] for j in cycle["jours"])
        bb_touches_cycle = sum(1 for j in cycle["jours"] if j["touche_bb"])

        lignes.append("")
        lignes.append(f"  ▶ CYCLE {type_cycle} : {debut} → {fin}")
        lignes.append(f"    Durée : {len(cycle['jours'])} jours | "
                      f"Rendement : {rendement_cycle:+.1f}% | "
                      f"Touches BB : {bb_touches_cycle}")
        lignes.append("  " + "-" * 56)

        cumul = 0.0
        for j in cycle["jours"]:
            cumul += j["rendement"]
            date_str = j["date"].strftime("%d/%m/%Y")
            rdt_str  = f"{j['rendement']:+.1f}%"
            cumul_str = f"{cumul:+.1f}%"
            bb_marker = " ◆BB" if j["touche_bb"] else ""
            lignes.append(
                f"  {date_str}  {rdt_str:>7}  (cum {cumul_str:>8})  "
                f"RSI {j['rsi']:.0f} | ADX {j['adx']:.0f} | Vol {j['vol']:.2f}"
                f"{bb_marker}"
            )

        total_rendement += rendement_cycle
        nb_cycles += 1
        nb_bb_touches += bb_touches_cycle

    lignes.append("")
    lignes.append("=" * 60)
    lignes.append(f"  RÉSUMÉ : {nb_cycles} cycle(s)")
    lignes.append(f"  Rendement total : {total_rendement:+.1f}%")
    lignes.append(f"  Touches BB totales : {nb_bb_touches}")
    lignes.append("=" * 60)

    return "\n".join(lignes)


def main():
    parser = argparse.ArgumentParser(description="EMA Analyser — Backtest cycles")
    parser.add_argument("tickers", nargs="*", help="Tickers à analyser (défaut : tickers.txt)")
    parser.add_argument("--mode", choices=["long", "short", "both"], default="both",
                        help="Mode d'analyse (long/short/both)")
    parser.add_argument("--periode", default="1y",
                        help="Période historique yfinance (ex: 6mo, 1y, 2y)")
    parser.add_argument("--output", help="Fichier de sortie (optionnel)")
    args = parser.parse_args()

    config = charger_config()

    tickers = args.tickers if args.tickers else charger_tickers()
    if not tickers:
        print("Aucun ticker fourni.")
        sys.exit(1)

    resultats = []

    for ticker in tickers:
        print(f"Analyse de {ticker}...")
        df = telecharger_donnees(ticker, config, periode=args.periode)
        if df is None:
            continue
        cycles = analyser_cycles(ticker, df, config, mode=args.mode)
        doc    = formater_document(ticker, cycles, mode=args.mode)
        resultats.append(doc)
        print(doc)
        print()

    if args.output and resultats:
        output_path = Path(args.output)
        output_path.write_text("\n\n".join(resultats), encoding="utf-8")
        print(f"Document sauvegardé : {output_path}")


if __name__ == "__main__":
    main()
