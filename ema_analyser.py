#!/usr/bin/env python3
"""
EMA Analyser — Backtest cycles avec SL, BB, pays, secteur
Génère un document HTML identique au template de référence.
"""

import json, sys, argparse, math
import yfinance as yf
import pandas as pd
from datetime import datetime
from pathlib import Path

BASE_DIR    = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
TICKERS_FILE = BASE_DIR / "tickers.txt"


# ─── Chargement config ────────────────────────────────────────────────────────

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


# ─── Indicateurs ──────────────────────────────────────────────────────────────

def calc_ema(serie, periode):
    return serie.ewm(span=periode, adjust=False).mean()

def calc_rsi(closes, periode=14):
    delta    = closes.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
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


# ─── Téléchargement ───────────────────────────────────────────────────────────

def telecharger(ticker, tf, period):
    try:
        df = yf.download(ticker, period=period, interval=tf,
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            return None
        df = df.dropna()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return None


# ─── Détection cycles ─────────────────────────────────────────────────────────

def est_haussier(e55, e8, e13, e21):
    return e55 < e8 and e55 < e13 and e55 < e21

def est_baissier(e55, e8, e13, e21):
    return e55 > e8 and e55 > e13 and e55 > e21

def detecter_cycles(df, config, mode):
    cfg = config["ema"]
    closes  = df["Close"].squeeze().astype(float)
    volumes = df["Volume"].squeeze().astype(float)

    ema8  = calc_ema(closes, cfg["ema8"])
    ema13 = calc_ema(closes, cfg["ema13"])
    ema21 = calc_ema(closes, cfg["ema21"])
    ema55 = calc_ema(closes, cfg["ema55"])
    rsi_s = calc_rsi(closes)
    adx_s = calc_adx(df)

    cfg_bol = config.get("bollinger", {"periode": 20, "ecarts": 2})
    bh_s, bb_s = calc_bollinger(closes, cfg_bol["periode"], cfg_bol["ecarts"])

    cycles = []
    en_cycle = False
    cycle_courant = None

    for i in range(1, len(df)):
        e55 = float(ema55.iloc[i]);   e8 = float(ema8.iloc[i])
        e13 = float(ema13.iloc[i]);   e21 = float(ema21.iloc[i])
        e55p = float(ema55.iloc[i-1]); e8p = float(ema8.iloc[i-1])
        e13p = float(ema13.iloc[i-1]); e21p = float(ema21.iloc[i-1])

        haus_act = est_haussier(e55, e8, e13, e21)
        bais_act = est_baissier(e55, e8, e13, e21)
        haus_pre = est_haussier(e55p, e8p, e13p, e21p)
        bais_pre = est_baissier(e55p, e8p, e13p, e21p)

        debut = (not haus_pre and haus_act) if mode == "long" else (not bais_pre and bais_act)
        actif = haus_act if mode == "long" else bais_act

        if debut:
            if cycle_courant:
                cycles.append(cycle_courant)
            cycle_courant = {
                "signal_idx":  i,
                "signal_date": df.index[i],
                "entry_idx":   i + 1 if i + 1 < len(df) else i,
                "jours":       [],
            }
            en_cycle = True

        if not actif and en_cycle:
            en_cycle = False
            if cycle_courant:
                cycles.append(cycle_courant)
                cycle_courant = None

        if en_cycle and cycle_courant and i > cycle_courant["signal_idx"]:
            prix    = float(closes.iloc[i])
            prix_pre = float(closes.iloc[i - 1])
            rsi = float(rsi_s.iloc[i]) if not pd.isna(rsi_s.iloc[i]) else 0.0
            adx = float(adx_s.iloc[i]) if not pd.isna(adx_s.iloc[i]) else 0.0
            vm  = float(volumes.iloc[max(0, i-20):i].mean()) if i >= 5 else float(volumes.iloc[i])
            vol = round(float(volumes.iloc[i]) / vm, 2) if vm > 0 else 1.0
            bh  = float(bh_s.iloc[i]) if not pd.isna(bh_s.iloc[i]) else None
            bb  = float(bb_s.iloc[i]) if not pd.isna(bb_s.iloc[i]) else None

            # Touche BB avec tolérance (config bollinger.tolerance_pct)
            # LONG  → prix proche de la bande basse par le bas
            # SHORT → prix proche de la bande haute par le haut
            tol = cfg_bol.get("tolerance_pct", 1.0) / 100.0
            if mode == "short":
                touche_bb = (bh is not None and prix >= bh * (1 - tol))
            else:
                touche_bb = (bb is not None and prix <= bb * (1 + tol))

            cycle_courant["jours"].append({
                "date":      df.index[i],
                "prix":      prix,
                "rsi":       int(round(rsi)),
                "adx":       int(round(adx)),
                "vol":       vol,
                "touche_bb": touche_bb,
            })

    if cycle_courant and cycle_courant["jours"]:
        cycles.append(cycle_courant)

    return cycles


# ─── Simulation SL ────────────────────────────────────────────────────────────

def sl_niveau(max_gain, sl_init, palier, be=None):
    """Calcule le niveau SL actuel selon le max_gain atteint."""
    if be is not None:
        if max_gain < be:
            return sl_init
        steps = math.floor((max_gain - be) / palier)
        return steps * palier
    else:
        steps = math.floor(max_gain / palier)
        return sl_init + steps * palier

def simuler_sl(jours, entry_idx, mode, sl_init, palier, be=None):
    """
    Simule une entrée à entry_idx jusqu'à la fin du cycle ou SL.
    Retourne (result_pct, exit_reason, nb_jours).
    """
    if entry_idx >= len(jours):
        return 0.0, "Hors cycle", 0
    entry_price = jours[entry_idx]["prix"]
    max_gain = 0.0

    for k in range(entry_idx, len(jours)):
        prix = jours[k]["prix"]
        if mode == "short":
            gain = (entry_price - prix) / entry_price * 100
        else:
            gain = (prix - entry_price) / entry_price * 100

        max_gain = max(max_gain, gain)
        sl = sl_niveau(max_gain, sl_init, palier, be)

        if gain <= sl:
            raison = "Stop loss" if sl <= 0 or gain < max_gain * 0.5 else "Trailing stop"
            return round(sl, 1), raison, k - entry_idx + 1

    # Fin de cycle sans SL
    prix_fin = jours[-1]["prix"]
    if mode == "short":
        gain_fin = (entry_price - prix_fin) / entry_price * 100
    else:
        gain_fin = (prix_fin - entry_price) / entry_price * 100
    return round(gain_fin, 2), "Fin cycle", len(jours) - entry_idx


def calc_bb_rendement(jours, mode, sl_init, palier, be=None):
    """
    Pour chaque jour avec une touche BB : simule SL depuis CE jour jusqu'à fin de cycle.
    Retourne liste de (date, result_pct, rsi, adx, vol) et la somme totale.
    """
    resultats = []
    total = 0.0
    for k, j in enumerate(jours):
        if not j["touche_bb"]:
            continue  # uniquement les jours avec touche BB
        res, _, _ = simuler_sl(jours, k, mode, sl_init, palier, be)
        total += res
        resultats.append({
            "date": j["date"],
            "pct":  round(res, 1),
            "rsi":  j["rsi"],
            "adx":  j["adx"],
            "vol":  j["vol"],
        })
    return resultats, round(total, 1)


# ─── Indicateurs pays / secteur / vue hebdo ───────────────────────────────────

def verifier_cycle(df_index, date, mode, config):
    """True si l'index est dans le cycle correspondant au mode à la date donnée."""
    if df_index is None or df_index.empty:
        return False
    cfg = config["ema"]
    closes = df_index["Close"].squeeze().astype(float)
    ema8  = calc_ema(closes, cfg["ema8"])
    ema13 = calc_ema(closes, cfg["ema13"])
    ema21 = calc_ema(closes, cfg["ema21"])
    ema55 = calc_ema(closes, cfg["ema55"])

    # Trouver l'index le plus proche de la date
    try:
        idx_loc = df_index.index.searchsorted(date)
        if idx_loc >= len(df_index):
            idx_loc = len(df_index) - 1
        e55 = float(ema55.iloc[idx_loc])
        e8  = float(ema8.iloc[idx_loc])
        e13 = float(ema13.iloc[idx_loc])
        e21 = float(ema21.iloc[idx_loc])
        if mode == "short":
            return est_baissier(e55, e8, e13, e21)
        else:
            return est_haussier(e55, e8, e13, e21)
    except Exception:
        return False


# ─── Génération HTML ──────────────────────────────────────────────────────────

CSS = """*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f4f0;color:#1a1a1a;padding:2rem}
h1{font-size:22px;font-weight:500;margin-bottom:4px}
.meta{font-size:13px;color:#666;margin-bottom:1rem}
.note{font-size:12px;color:#888;background:#eef3fb;border-left:3px solid #378add;padding:8px 12px;border-radius:4px;margin-bottom:1.5rem}
.kpis{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:1rem}
.kpi{background:#fff;border-radius:10px;padding:14px 18px;min-width:120px;border:0.5px solid #e0ddd6}
.kl{font-size:12px;color:#888;margin-bottom:4px}
.kv{font-size:20px;font-weight:500;color:#1a1a1a}
.kv.green{color:#0f6e56}.kv.red{color:#a32d2d}
.sl-compare{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:2rem}
.sl-card{background:#fff;border-radius:10px;padding:14px 18px;border:0.5px solid #e0ddd6}
.sl-a{border-top:3px solid #378add}.sl-b{border-top:3px solid #3b6d11}.sl-c{border-top:3px solid #ba7517}.sl-d{border-top:3px solid #7b3fa0}
.sl-title{font-size:12px;font-weight:500;color:#444;margin-bottom:10px}
.sl-stats{display:flex;gap:16px}
.sl-stats .kl{font-size:11px}.sl-stats .kv{font-size:18px}
.section-title{font-size:14px;font-weight:500;margin-bottom:10px}
.table-wrap{overflow-x:auto;border-radius:10px;border:0.5px solid #e0ddd6;margin-bottom:2rem;background:#fff}
table{width:100%;border-collapse:collapse;font-size:12px}
thead th{background:#f5f4f0;padding:8px 9px;text-align:left;font-weight:500;font-size:11px;color:#666;border-bottom:0.5px solid #e0ddd6;white-space:nowrap}
tbody td{padding:7px 9px;border-bottom:0.5px solid #f0ede8;white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:#faf9f6}
.sl-a-col{background:#f0f6ff}.sl-b-col{background:#f0f8f0}.sl-c-col{background:#fdf6ec}.sl-d-col{background:#f8f0ff}
.bb-col{background:#fef9ec;min-width:160px}.bb-col2{background:#fef3f0;min-width:160px}
.bb-indi{font-size:10px;color:#888;margin-left:3px;white-space:nowrap}
.ht-col{background:#eef7f4;min-width:240px;max-width:320px;vertical-align:top;font-size:11px}
.badge{display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:500}
.bg{background:#eaf3de;color:#3b6d11}.br{background:#fcebeb;color:#a32d2d}
.bn{background:#f0ede8;color:#666}.bi{background:#e6f1fb;color:#185fa5}
.chart-box{background:#fff;border-radius:10px;border:0.5px solid #e0ddd6;padding:1.5rem;margin-bottom:2rem}
.legend{display:flex;gap:16px;margin-bottom:12px;font-size:12px;color:#666}
.legend span{display:flex;align-items:center;gap:6px}
.dot{width:10px;height:10px;border-radius:2px}
.footer{font-size:11px;color:#aaa;margin-top:1rem}"""

def badge(valeur, seuil_vert=None, seuil_rouge=None, fmt=None, inverse=False):
    txt = fmt(valeur) if fmt else str(valeur)
    if seuil_vert is None:
        cls = "bn"
    elif inverse:
        cls = "br" if valeur >= seuil_vert else "bg"
    else:
        cls = "bg" if valeur >= seuil_vert else ("br" if seuil_rouge and valeur < seuil_rouge else "bn")
    return f'<span class="badge {cls}">{txt}</span>'

def badge_pct(val):
    txt = f"{val:+.1f}%"
    cls = "bg" if val > 0 else ("br" if val < 0 else "bn")
    return f'<span class="badge {cls}">{txt}</span>'

def badge_check(ok):
    return f'<span class="badge {"bg" if ok else "br"}">{"✓" if ok else "✗"}</span>'


def generer_html(ticker, cycles, mode, country_ticker, sector_ticker,
                 config, df_country, df_sector, df_weekly, period):
    """Génère le HTML complet."""

    mode_label = "SHORT" if mode == "short" else "LONG"
    mode_color = "#a32d2d" if mode == "short" else "#0f6e56"

    # ── Paramètres SL ────────────────────────────────────────────────
    SL_CONFIGS = [
        {"nom": "SL A", "desc": "SL A — init -2.5%, paliers 5%",
         "sl_init": -2.5, "palier": 5.0, "be": None,
         "col": "sl-a", "col_cls": "sl-a-col",
         "chart_color": "rgba(55,138,221,0.7)"},
        {"nom": "SL B", "desc": "SL B — init -5%, paliers 5%",
         "sl_init": -5.0, "palier": 5.0, "be": None,
         "col": "sl-b", "col_cls": "sl-b-col",
         "chart_color": "rgba(59,109,17,0.7)"},
        {"nom": "SL C", "desc": "SL C — init -7.5%, paliers 7.5%",
         "sl_init": -7.5, "palier": 7.5, "be": None,
         "col": "sl-c", "col_cls": "sl-c-col",
         "chart_color": "rgba(186,117,23,0.7)"},
        {"nom": "SL D", "desc": "SL D — init -2.5%, BE à +5%, paliers 5%",
         "sl_init": -2.5, "palier": 5.0, "be": 5.0,
         "col": "sl-d", "col_cls": "sl-d-col",
         "chart_color": "rgba(123,63,160,0.7)"},
    ]

    # ── Calcul de tous les cycles ─────────────────────────────────────
    resultats = []
    for cycle in cycles:
        jours = cycle["jours"]
        if not jours:
            continue

        entry_idx = 0  # premier jour = N+1

        # SL results
        sl_results = []
        for sl in SL_CONFIGS:
            res, raison, _ = simuler_sl(jours, entry_idx, mode,
                                        sl["sl_init"], sl["palier"], sl["be"])
            sl_results.append({"pct": res, "raison": raison})

        # Sans SL (fin de cycle)
        prix_entree = jours[entry_idx]["prix"]
        prix_fin    = jours[-1]["prix"]
        if mode == "short":
            sans_sl = (prix_entree - prix_fin) / prix_entree * 100
        else:
            sans_sl = (prix_fin - prix_entree) / prix_entree * 100

        # BB touches
        nb_bb = sum(1 for j in jours if j["touche_bb"])

        # BB rendement (SL A et SL B)
        bb_sla, sum_sla = calc_bb_rendement(jours, mode,
                                             SL_CONFIGS[0]["sl_init"],
                                             SL_CONFIGS[0]["palier"],
                                             SL_CONFIGS[0]["be"])
        bb_slb, sum_slb = calc_bb_rendement(jours, mode,
                                             SL_CONFIGS[1]["sl_init"],
                                             SL_CONFIGS[1]["palier"],
                                             SL_CONFIGS[1]["be"])

        # Indicateurs au signal
        j0  = jours[0]
        rsi = j0["rsi"]
        adx = j0["adx"]
        vol = j0["vol"]

        # Pays / Secteur / Vue W
        signal_date = cycle["signal_date"]
        ok_pays    = verifier_cycle(df_country, signal_date, mode, config)
        ok_secteur = verifier_cycle(df_sector,  signal_date, mode, config)
        ok_weekly  = verifier_cycle(df_weekly,  signal_date, mode, config)

        resultats.append({
            "signal_date": signal_date,
            "entry_date":  jours[0]["date"],
            "duree":       len(jours),
            "rsi": rsi, "adx": adx, "vol": vol,
            "ok_pays":    ok_pays,
            "ok_secteur": ok_secteur,
            "ok_weekly":  ok_weekly,
            "sans_sl":    round(sans_sl, 2),
            "sl_results": sl_results,
            "nb_bb":      nb_bb,
            "bb_sla":     bb_sla,
            "bb_slb":     bb_slb,
            "sum_sla":    sum_sla,
            "sum_slb":    sum_slb,
        })

    if not resultats:
        return f"<p>Aucun cycle {mode_label} trouvé pour {ticker}.</p>"

    # ── KPIs globaux ──────────────────────────────────────────────────
    nb_cycles    = len(resultats)
    cumul_sans_sl = sum(r["sans_sl"] for r in resultats)
    wins_sans_sl  = sum(1 for r in resultats if r["sans_sl"] > 0)
    winrate_pct   = round(wins_sans_sl / nb_cycles * 100, 1)

    # SL résumés
    sl_totaux = []
    for j, sl in enumerate(SL_CONFIGS):
        total = sum(r["sl_results"][j]["pct"] for r in resultats)
        wins  = sum(1 for r in resultats if r["sl_results"][j]["pct"] > 0)
        sl_totaux.append({"total": round(total, 1), "wins": wins})

    total_sum_sla = sum(r["sum_sla"] for r in resultats)
    total_sum_slb = sum(r["sum_slb"] for r in resultats)


    # ── HTML ──────────────────────────────────────────────────────────
    html = [f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>EMA Analyser — {ticker}</title>
<style>
{CSS}
</style>
</head>
<body>
<h1>Analyse EMA — {ticker} <span style="font-size:14px;padding:3px 10px;border-radius:4px;background:{'#fcebeb' if mode=='short' else '#eaf3de'};color:{mode_color};margin-left:8px">{mode_label}</span></h1>
<p class="meta">Pays : {country_ticker or '—'} &nbsp;|&nbsp; Secteur : {sector_ticker or '—'} &nbsp;|&nbsp; Mode : {mode_label} &nbsp;|&nbsp; Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
<p class="note">RSI et ADX méthode Wilder (identique TradingView) · Indicateurs lus au bar N (signal) · Entrée au close N+1</p>
"""]

    # KPIs
    kv_wr  = "green" if winrate_pct >= 50 else "red"
    kv_cum = "green" if cumul_sans_sl >= 0 else "red"
    html.append(f"""<div class="kpis">
<div class="kpi"><div class="kl">Cycles</div><div class="kv ">{nb_cycles}</div></div>
<div class="kpi"><div class="kl">Win rate (sans SL)</div><div class="kv {kv_wr}">{'+' if winrate_pct>=0 else ''}{winrate_pct}%</div></div>
<div class="kpi"><div class="kl">Cumulé sans SL</div><div class="kv {kv_cum}">{cumul_sans_sl:+.1f}%</div></div>
</div>""")

    # SL cards
    sl_card_html = ""
    for j, sl in enumerate(SL_CONFIGS):
        t = sl_totaux[j]
        wr_cls = "green" if t["wins"] / nb_cycles >= 0.5 else "red"
        cum_cls = "green" if t["total"] >= 0 else "red"
        sl_card_html += f"""<div class="sl-card {sl['col']}">
          <div class="sl-title">{sl['desc']}</div>
          <div class="sl-stats">
            <div><span class="kl">Win rate</span><span class="kv {wr_cls}">{t['wins']}/{nb_cycles} ({round(t['wins']/nb_cycles*100)}%)</span></div>
            <div><span class="kl">Cumulé</span><span class="kv {cum_cls}">{t['total']:+.1f}%</span></div>
          </div>
        </div>"""
    html.append(f'<div class="sl-compare">{sl_card_html}</div>')


    # Section title
    section = "haussiers" if mode == "long" else "baissiers"
    html.append(f'<div class="section-title">Détail des cycles {section}</div>')
    html.append('<div class="table-wrap"><table>')
    html.append("""<thead><tr>
  <th>#</th><th>Signal N</th><th>Entrée N+1</th><th>Durée</th>
  <th>RSI</th><th>ADX</th><th>Vol×</th><th>Pays</th><th>Secteur</th><th>Vue W</th>
  <th>Sans SL (cycle entier)</th>
  <th class="sl-a-col">SL A (-2.5% / pal.5%)</th>
  <th class="sl-b-col">SL B (-5% / pal.5%)</th>
  <th class="sl-c-col">SL C (-7.5% / pal.7.5%)</th>
  <th class="sl-d-col">SL D (-2.5% / BE +5% / pal.5%)</th>
  <th>BB touches</th>
  <th class="bb-col">Rendement BB (SL -2.5% / pal.5%)</th>
  <th class="bb-col2">Rendement BB (SL -5% / pal.5%)</th>
</tr></thead>
<tbody>""")

    cumul_sla_global = 0.0
    cumul_slb_global = 0.0

    for idx, r in enumerate(resultats):
        # Badges principaux
        rsi_cls = "bn" if r["rsi"] < 50 else ("bg" if r["rsi"] > 60 else "bn")
        adx_cls = "bg" if r["adx"] >= 25 else "bn"
        vol_cls = "bg" if r["vol"] >= 1.2 else ("br" if r["vol"] < 0.7 else "bn")

        sans_sl_badge = badge_pct(r["sans_sl"])

        sl_cells = ""
        for j, sl in enumerate(SL_CONFIGS):
            res = r["sl_results"][j]
            pct_badge = badge_pct(res["pct"])
            raison_badge = f'<span class="badge bn" style="font-size:10px">{res["raison"]}</span>'
            sl_cells += f"<td class='{sl['col_cls']}'>{pct_badge} {raison_badge}</td>"

        bb_badge = f'<span class="badge bi">{r["nb_bb"]}/{r["duree"]}</span>'

        # Sous-lignes BB rendement SL A
        def bb_subrows(bb_list, cumul_global):
            html_sub = ""
            for entry in bb_list:
                pct = entry["pct"]
                total = round(cumul_global + pct, 1)  # not used in display, keep per-day
                pct_b = badge_pct(pct)
                date_b = f'<span class="badge bn" style="font-size:10px;margin-right:3px">{entry["date"].strftime("%d/%m/%Y")}</span>'
                indi = f'<span class="bb-indi">RSI {entry["rsi"]} | ADX {entry["adx"]} | Vol {entry["vol"]:.2f}</span>'
                html_sub += f'<div style="margin-bottom:2px">{date_b}{pct_b}{indi}</div>'
            return html_sub

        sum_sla_total = round(cumul_sla_global + r["sum_sla"], 1)
        sum_slb_total = round(cumul_slb_global + r["sum_slb"], 1)

        bb_sla_html = bb_subrows(r["bb_sla"], cumul_sla_global)
        bb_slb_html = bb_subrows(r["bb_slb"], cumul_slb_global)

        # Totaux en bas de chaque cycle
        sum_sla_b = badge_pct(r["sum_sla"])
        sum_slb_b = badge_pct(r["sum_slb"])

        bb_sla_html += f'<div style="margin-top:4px;font-weight:500">∑{sum_sla_b}</div>'
        bb_slb_html += f'<div style="margin-top:4px;font-weight:500">∑{sum_slb_b}</div>'

        cumul_sla_global += r["sum_sla"]
        cumul_slb_global += r["sum_slb"]

        html.append(f"""<tr>
<td>{idx+1}</td>
<td>{r['signal_date'].strftime('%d/%m/%Y')}</td>
<td>{r['entry_date'].strftime('%d/%m/%Y')}</td>
<td>{r['duree']}j</td>
<td><span class="badge {rsi_cls}">{r['rsi']}</span></td>
<td><span class="badge {adx_cls}">{r['adx']}</span></td>
<td><span class="badge {vol_cls}">{r['vol']:.2f}</span></td>
<td>{badge_check(r['ok_pays'])}</td>
<td>{badge_check(r['ok_secteur'])}</td>
<td>{badge_check(r['ok_weekly'])}</td>
<td>{sans_sl_badge}</td>
{sl_cells}
<td>{bb_badge}</td>
<td class="bb-col">{bb_sla_html}</td>
<td class="bb-col2">{bb_slb_html}</td>
</tr>""")

    # Ligne totaux
    tot_sans_sl = badge_pct(round(cumul_sans_sl, 1))
    tot_sl_cells = ""
    for j, sl in enumerate(SL_CONFIGS):
        t = round(sl_totaux[j]["total"], 1)
        tot_sl_cells += f"<td class='{sl['col_cls']}'><b>{badge_pct(t)}</b></td>"

    total_sla_b = badge_pct(round(cumul_sla_global, 1))
    total_slb_b = badge_pct(round(cumul_slb_global, 1))

    html.append(f"""<tr style="background:#f5f4f0;font-weight:600">
<td colspan="10"><b>TOTAL</b></td>
<td>{tot_sans_sl}</td>
{tot_sl_cells}
<td></td>
<td class="bb-col"><b>∑{total_sla_b}</b></td>
<td class="bb-col2"><b>∑{total_slb_b}</b></td>
</tr>""")

    html.append("</tbody></table></div>")

    # Footer
    html.append(f'<p class="footer">Généré par EMA Analyser · {ticker} · {period} · {datetime.now().strftime("%d/%m/%Y %H:%M")}</p>')

    html.append("</body>\n</html>")

    return "\n".join(html)



# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="EMA Analyser — Génère un rapport HTML de backtest",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--ticker",   required=False, help="Ticker principal (ex: ADA-USD)")
    parser.add_argument("--mode",     choices=["long", "short"], default="short",
                        help="Mode : long (haussier) ou short (baissier)")
    parser.add_argument("--period",   default="3y",
                        help="Période historique (ex: 1y, 2y, 3y, 5y)")
    parser.add_argument("--country",  default=None, help="Ticker index pays (ex: ^GSPC)")
    parser.add_argument("--sector",   default=None, help="Ticker secteur (ex: IXJ)")
    parser.add_argument("--output",   default=None, help="Fichier HTML de sortie")
    args = parser.parse_args()

    config = charger_config()
    tf = config["scan"]["timeframe"]

    tickers = [args.ticker.upper()] if args.ticker else charger_tickers()
    if not tickers:
        print("Aucun ticker. Utilisez --ticker SYMBOL ou remplissez tickers.txt")
        sys.exit(1)

    # Télécharger index pays et secteur une seule fois
    print(f"Téléchargement données annexes...")
    df_country = telecharger(args.country, tf, args.period) if args.country else None
    df_sector  = telecharger(args.sector,  tf, args.period) if args.sector  else None

    for ticker in tickers:
        print(f"Analyse de {ticker} ({args.period}, mode {args.mode.upper()})...")
        df = telecharger(ticker, tf, args.period)
        if df is None:
            print(f"  → Données insuffisantes pour {ticker}, ignoré.")
            continue

        # Vue hebdomadaire du même ticker
        df_weekly = telecharger(ticker, "1wk", args.period)

        cycles = detecter_cycles(df, config, args.mode)
        print(f"  → {len(cycles)} cycle(s) détecté(s)")

        html = generer_html(
            ticker, cycles, args.mode,
            args.country, args.sector,
            config, df_country, df_sector, df_weekly,
            args.period
        )

        output = args.output or f"EMA_Analyser__{ticker.replace('-', '')}.html"
        Path(output).write_text(html, encoding="utf-8")
        print(f"  → Document généré : {output}")

        # Ouvrir automatiquement dans le navigateur
        import webbrowser, os
        webbrowser.open(f"file:///{Path(output).resolve().as_posix()}")


if __name__ == "__main__":
    main()
