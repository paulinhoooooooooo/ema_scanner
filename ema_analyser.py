#!/usr/bin/env python3
"""
EMA Analyser — Backtest cycles haussiers/baissiers
Génère un document comparatif : avec BB vs sans BB
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
    return (100 - (100 / (1 + rs))).round(1)


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
    return dx.ewm(alpha=1/periode, min_periods=periode).mean().round(1)


def calc_bollinger(closes, periode=20, nb_ecarts=2):
    sma = closes.rolling(window=periode).mean()
    std = closes.rolling(window=periode).std()
    return sma + nb_ecarts * std, sma - nb_ecarts * std


def telecharger_donnees(ticker, config, period="1y"):
    tf = config["scan"]["timeframe"]
    try:
        df = yf.download(ticker, period=period, interval=tf, progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            print(f"[WARN] {ticker} — données insuffisantes ({len(df)} bougies)")
            return None
        df = df.dropna()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f"[ERR] {ticker} — {e}")
        return None


def backtest(ticker, df, config, mode="short"):
    """
    Retourne une liste de jours avec leurs indicateurs et touche BB.
    mode : "long" ou "short"
    """
    cfg_ema = config["ema"]
    cfg_bol = config.get("bollinger", {"periode": 20, "ecarts": 2, "actif": True})

    closes  = df["Close"].squeeze().astype(float)
    volumes = df["Volume"].squeeze().astype(float)

    ema8  = calc_ema(closes, cfg_ema["ema8"])
    ema13 = calc_ema(closes, cfg_ema["ema13"])
    ema21 = calc_ema(closes, cfg_ema["ema21"])
    ema55 = calc_ema(closes, cfg_ema["ema55"])

    rsi_s = calc_rsi(closes)
    adx_s = calc_adx(df)
    bh_s, bb_s = calc_bollinger(closes, cfg_bol["periode"], cfg_bol["ecarts"])

    jours = []
    en_cycle = False

    for i in range(1, len(df)):
        e55 = float(ema55.iloc[i]);   e8  = float(ema8.iloc[i])
        e13 = float(ema13.iloc[i]);   e21 = float(ema21.iloc[i])
        e55p = float(ema55.iloc[i-1]); e8p = float(ema8.iloc[i-1])
        e13p = float(ema13.iloc[i-1]); e21p = float(ema21.iloc[i-1])

        haussier = e55 < e8  and e55 < e13  and e55 < e21
        baissier = e55 > e8  and e55 > e13  and e55 > e21
        haussier_pre = e55p < e8p and e55p < e13p and e55p < e21p
        baissier_pre = e55p > e8p and e55p > e13p and e55p > e21p

        if mode == "short":
            debut_cycle = not baissier_pre and baissier
            actif_cycle = baissier
        else:
            debut_cycle = not haussier_pre and haussier
            actif_cycle = haussier

        if debut_cycle:
            en_cycle = True

        if not actif_cycle:
            en_cycle = False

        if not en_cycle:
            continue

        prix     = float(closes.iloc[i])
        prix_pre = float(closes.iloc[i-1])
        rsi = float(rsi_s.iloc[i]) if not pd.isna(rsi_s.iloc[i]) else 0.0
        adx = float(adx_s.iloc[i]) if not pd.isna(adx_s.iloc[i]) else 0.0

        vol_moy = float(volumes.iloc[max(0, i-20):i].mean()) if i >= 5 else float(volumes.iloc[i])
        vol_ratio = round(float(volumes.iloc[i]) / vol_moy, 2) if vol_moy > 0 else 1.0

        # Rendement journalier (inversé pour short)
        rdt = (prix / prix_pre - 1) * 100
        if mode == "short":
            rdt = -rdt

        # Touche BB
        # LONG  → prix <= bande basse  (survente en cycle haussier)
        # SHORT → prix >= bande haute  (surachat en cycle baissier)
        bh = float(bh_s.iloc[i]) if not pd.isna(bh_s.iloc[i]) else None
        bb = float(bb_s.iloc[i]) if not pd.isna(bb_s.iloc[i]) else None

        if mode == "short":
            touche_bb = (bh is not None and prix >= bh)
        else:
            touche_bb = (bb is not None and prix <= bb)

        # Marqueur début cycle
        est_debut = debut_cycle

        jours.append({
            "date":      df.index[i],
            "rendement": round(rdt, 1),
            "rsi":       int(rsi),
            "adx":       int(adx),
            "vol":       vol_ratio,
            "touche_bb": touche_bb,
            "debut":     est_debut,
        })

    return jours


def generer_document(ticker, jours, mode="short", output_path=None):
    """
    Génère le tableau comparatif : colonne avec BB | colonne sans BB
    Format visuel proche de l'image de référence.
    """
    if not jours:
        print(f"Aucun cycle {mode.upper()} trouvé pour {ticker}.")
        return

    mode_label = "SHORT (BAISSIER)" if mode == "short" else "LONG (HAUSSIER)"

    lignes = []

    # En-tête
    lignes.append(f"{'=' * 78}")
    lignes.append(f"  EMA ANALYSER — {ticker}  |  Mode : {mode_label}")
    lignes.append(f"  Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    lignes.append(f"{'=' * 78}")

    # Titres colonnes
    col1 = f"  {'Avec touch BB':^35}"
    col2 = f"  {'Sans touch BB':^35}"
    lignes.append(col1 + " | " + col2)
    lignes.append(f"  {'-' * 35} | {'-' * 35}")

    cumul_avec = 0.0
    cumul_sans = 0.0
    nb_bb = 0

    for j in jours:
        date_str = j["date"].strftime("%d/%m/%Y")
        rdt      = j["rendement"]
        indicateurs = f"RSI {j['rsi']} | ADX {j['adx']} | Vol {j['vol']:.2f}"
        debut_marker = "  ► DÉBUT CYCLE" if j["debut"] else ""

        if debut_marker:
            sep = f"  {'-' * 35} | {'-' * 35}"
            lignes.append(sep)
            lignes.append(f"{debut_marker}")

        # Colonne gauche : avec BB (on filtre : si touche BB on saute le jour = 0%)
        rdt_avec = 0.0 if j["touche_bb"] else rdt
        cumul_avec += rdt_avec

        # Colonne droite : sans BB (toujours le rendement brut)
        rdt_sans = rdt
        cumul_sans += rdt_sans

        if j["touche_bb"]:
            nb_bb += 1

        rdt_avec_str = f"{rdt_avec:+.1f}%"
        rdt_sans_str = f"{rdt_sans:+.1f}%"

        ligne_g = f"  {date_str}  {rdt_avec_str:>7}  {indicateurs}"
        ligne_d = f"  {date_str}  {rdt_sans_str:>7}  {indicateurs}"

        # Marqueur BB colonne droite uniquement
        if j["touche_bb"]:
            ligne_d += "  ◆BB"

        lignes.append(f"{ligne_g:<38} | {ligne_d}")

    # Total
    lignes.append(f"  {'=' * 35} | {'=' * 35}")
    lignes.append(
        f"  {'Σ ' + str(round(cumul_avec, 1)) + '%':>10}  ({nb_bb} touches BB filtrées)"
        f"{'':>10} | "
        f"  {'Σ ' + str(round(cumul_sans, 1)) + '%':>10}"
    )
    lignes.append(f"{'=' * 78}")

    document = "\n".join(lignes)
    print(document)

    if output_path:
        Path(output_path).write_text(document, encoding="utf-8")
        print(f"\n  Document sauvegardé : {output_path}")

    return document


def main():
    parser = argparse.ArgumentParser(
        description="EMA Analyser — Backtest cycles avec/sans BB",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--ticker",   required=False, help="Ticker à analyser (ex: ADA-USD, AAPL)")
    parser.add_argument("--mode",     choices=["long", "short", "both"], default="short",
                        help="Mode : long / short / both (défaut: short)")
    parser.add_argument("--period",   default="1y",
                        help="Période historique (ex: 6mo, 1y, 2y, 3y) (défaut: 1y)")
    parser.add_argument("--output",   help="Fichier de sortie .txt (optionnel)")
    # Arguments ignorés pour compatibilité
    parser.add_argument("--country",  help="(ignoré)")
    parser.add_argument("--sector",   help="(ignoré)")
    args = parser.parse_args()

    config = charger_config()

    # Tickers : argument --ticker OU fichier tickers.txt
    if args.ticker:
        tickers = [args.ticker.upper()]
    else:
        tickers = charger_tickers()

    if not tickers:
        print("Aucun ticker. Utilisez --ticker SYMBOL ou remplissez tickers.txt")
        sys.exit(1)

    modes = ["long", "short"] if args.mode == "both" else [args.mode]

    for ticker in tickers:
        print(f"\nTéléchargement de {ticker} ({args.period})...")
        df = telecharger_donnees(ticker, config, period=args.period)
        if df is None:
            continue

        for mode in modes:
            output = args.output
            if args.output and len(tickers) * len(modes) > 1:
                output = f"{Path(args.output).stem}_{ticker}_{mode}{Path(args.output).suffix}"

            jours = backtest(ticker, df, config, mode=mode)
            generer_document(ticker, jours, mode=mode, output_path=output)


if __name__ == "__main__":
    main()
