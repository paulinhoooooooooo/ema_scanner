#!/usr/bin/env python3
"""
BB Analyser — Analyse statistique des cycles et signaux Bollinger
Génère un rapport HTML identique au format PDF de référence.
Usage : python bb_analyser.py --ticker ADA-USD --mode short --period 3y [--country ^GSPC] [--sector IXJ]
"""

import sys, argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ema_analyser import (
    charger_config, charger_tickers, telecharger,
    detecter_cycles, calc_bb_rendement, simuler_sl, verifier_cycle,
)

BASE_DIR = Path(__file__).parent

SL_CFGS = [
    {"nom": "SL A", "desc": "init -2.5%, pal.5%",         "sl_init": -2.5, "palier": 5.0, "be": None, "color": "#378add", "key": "sla"},
    {"nom": "SL B", "desc": "init -5%, pal.5%",           "sl_init": -5.0, "palier": 5.0, "be": None, "color": "#3b6d11", "key": "slb"},
    {"nom": "SL C", "desc": "init -7.5%, pal.7.5%",       "sl_init": -7.5, "palier": 7.5, "be": None, "color": "#ba7517", "key": "slc"},
    {"nom": "SL D", "desc": "init -2.5% / BE+5% / pal.5%","sl_init": -2.5, "palier": 5.0, "be":  5.0, "color": "#7b3fa0", "key": "sld"},
]
MOIS_FR = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]


# ─── Construction du dataset ──────────────────────────────────────────────────

def construire_donnees(cycles, mode, config, df_c, df_s, df_w):
    """
    Retourne deux listes :
    - cycle_data : une entrée par cycle (RSI/ADX/Vol à l'entrée, résultat SL, top-down)
    - bb_data    : une entrée par touche BB (RSI/ADX/Vol au moment du toucher, résultat SL)
    """
    cycle_data, bb_data = [], []

    for cycle in cycles:
        jours = cycle["jours"]
        if not jours:
            continue

        j0           = jours[0]
        signal_date  = cycle["signal_date"]

        # Résultat par SL depuis l'entrée du cycle
        sl_pcts = [
            simuler_sl(jours, 0, mode, sl["sl_init"], sl["palier"], sl["be"])[0]
            for sl in SL_CFGS
        ]

        # Rendement sans SL (fin de cycle)
        pe, pf = jours[0]["prix"], jours[-1]["prix"]
        sans_sl = round((pe - pf) / pe * 100 if mode == "short"
                        else (pf - pe) / pe * 100, 2)

        # Filtres top-down
        ok_p = verifier_cycle(df_c, signal_date, mode, config)
        ok_s = verifier_cycle(df_s, signal_date, mode, config)
        ok_w = verifier_cycle(df_w, signal_date, mode, config)

        cycle_data.append({
            "signal_date": signal_date,
            "duree":       len(jours),
            "rsi":  j0["rsi"], "adx": j0["adx"], "vol": j0["vol"],
            "sans_sl":  sans_sl,
            "pct_sla":  sl_pcts[0], "pct_slb": sl_pcts[1],
            "pct_slc":  sl_pcts[2], "pct_sld": sl_pcts[3],
            "ok_pays":    ok_p, "ok_secteur": ok_s, "ok_weekly": ok_w,
        })

        # Touches BB — calculer pour les 4 configs SL
        bb_lists = [
            calc_bb_rendement(jours, mode, sl["sl_init"], sl["palier"], sl["be"])[0]
            for sl in SL_CFGS
        ]

        for i in range(len(bb_lists[0])):
            base = bb_lists[0][i]
            bb_data.append({
                "date": base["date"],
                "rsi":  base["rsi"], "adx": base["adx"], "vol": base["vol"],
                "pct_sla": bb_lists[0][i]["pct"],
                "pct_slb": bb_lists[1][i]["pct"],
                "pct_slc": bb_lists[2][i]["pct"],
                "pct_sld": bb_lists[3][i]["pct"],
                "cycle_duree": len(jours),
                "ok_pays":    ok_p, "ok_secteur": ok_s, "ok_weekly": ok_w,
            })

    return cycle_data, bb_data


# ─── Fonctions de stats ───────────────────────────────────────────────────────

def stat_rows(items, key_func, tranches):
    """Tranches pour les cycles — win basé sur sans_sl > 0."""
    rows = []
    for label, lo, hi in tranches:
        sub = [it for it in items if lo <= key_func(it) < hi]
        n = len(sub)
        if n == 0:
            continue
        win = sum(1 for it in sub if it["sans_sl"] > 0)
        rows.append({
            "label":   label, "n": n,
            "win_pct": round(win / n * 100),
            "moy_ss":  round(sum(it["sans_sl"] for it in sub) / n, 1),
            "moy_sla": round(sum(it["pct_sla"] for it in sub) / n, 1),
            "moy_slb": round(sum(it["pct_slb"] for it in sub) / n, 1),
            "moy_slc": round(sum(it["pct_slc"] for it in sub) / n, 1),
            "moy_sld": round(sum(it["pct_sld"] for it in sub) / n, 1),
        })
    return rows


def bb_stat_rows(items, key_func, tranches):
    """Tranches pour les touches BB — win par SL séparément."""
    rows = []
    for label, lo, hi in tranches:
        sub = [it for it in items if lo <= key_func(it) < hi]
        n = len(sub)
        if n == 0:
            continue
        wa = sum(1 for it in sub if it["pct_sla"] > 0)
        wb = sum(1 for it in sub if it["pct_slb"] > 0)
        wc = sum(1 for it in sub if it["pct_slc"] > 0)
        wd = sum(1 for it in sub if it["pct_sld"] > 0)
        rows.append({
            "label": label, "n": n,
            "win_a": wa, "win_pct_a": round(wa / n * 100),
            "win_b": wb, "win_pct_b": round(wb / n * 100),
            "win_c": wc, "win_pct_c": round(wc / n * 100),
            "win_d": wd, "win_pct_d": round(wd / n * 100),
            "moy_sla": round(sum(it["pct_sla"] for it in sub) / n, 1),
            "moy_slb": round(sum(it["pct_slb"] for it in sub) / n, 1),
            "moy_slc": round(sum(it["pct_slc"] for it in sub) / n, 1),
            "moy_sld": round(sum(it["pct_sld"] for it in sub) / n, 1),
        })
    return rows


# ─── HTML helpers ─────────────────────────────────────────────────────────────

CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f4f0;color:#1a1a1a;padding:2rem;max-width:1400px;margin:0 auto}
h1{font-size:22px;font-weight:500;margin-bottom:4px}
h2{font-size:15px;font-weight:600;margin:2rem 0 0.5rem;padding-bottom:6px;border-bottom:2px solid #e0ddd6}
h2.bb-title{border-bottom-color:#1a1a1a;margin-top:2.5rem;padding-top:1rem;border-top:3px solid #1a1a1a}
h3{font-size:13px;font-weight:500;color:#555;margin:1.2rem 0 0.4rem}
.meta{font-size:13px;color:#666;margin-bottom:0.5rem}
.note{font-size:12px;color:#888;background:#eef3fb;border-left:3px solid #378add;padding:8px 12px;border-radius:4px;margin-bottom:1.5rem}
.obs{font-size:12px;margin:4px 0 10px;line-height:1.7}
.kpis{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:1.5rem}
.kpi{background:#fff;border-radius:10px;padding:14px 18px;min-width:120px;border:0.5px solid #e0ddd6}
.kl{font-size:12px;color:#888;margin-bottom:4px}
.kv{font-size:20px;font-weight:500}
.kv.green{color:#0f6e56}.kv.red{color:#a32d2d}
.table-wrap{overflow-x:auto;border-radius:10px;border:0.5px solid #e0ddd6;margin-bottom:1.2rem;background:#fff}
table{width:100%;border-collapse:collapse;font-size:12px}
thead th{background:#f5f4f0;padding:8px 9px;text-align:left;font-weight:500;font-size:11px;color:#666;border-bottom:0.5px solid #e0ddd6;white-space:nowrap}
tbody td{padding:7px 9px;border-bottom:0.5px solid #f0ede8;white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:#faf9f6}
tr.best td{background:#f0fff4!important}
tr.worst td{background:#fff5f5!important}
.badge{display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:500}
.bg{background:#eaf3de;color:#3b6d11}.br{background:#fcebeb;color:#a32d2d}
.bn{background:#f0ede8;color:#666}.bi{background:#e6f1fb;color:#185fa5}
.sla{color:#378add;font-weight:600}.slb{color:#3b6d11;font-weight:600}
.slc{color:#ba7517;font-weight:600}.sld{color:#7b3fa0;font-weight:600}
.checklist{background:#fff;border-radius:10px;border:0.5px solid #e0ddd6;padding:1.5rem;margin-bottom:2rem}
.check-row{display:grid;grid-template-columns:200px 110px 1fr;gap:12px;padding:8px 0;border-bottom:0.5px solid #f0ede8;font-size:12px;align-items:start}
.check-row:last-child{border-bottom:none}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:960px){.two-col{grid-template-columns:1fr}}
.footer{font-size:11px;color:#aaa;margin-top:2rem}
"""

def pct_b(val):
    cls = "bg" if val > 0 else ("br" if val < 0 else "bn")
    return f'<span class="badge {cls}">{val:+.1f}%</span>'

def win_b(pct, extra=""):
    cls = "bg" if pct >= 55 else ("br" if pct < 40 else "bn")
    return f'<span class="badge {cls}">{pct}%{extra}</span>'

def _sl_headers():
    return ('<th><span class="sla">SL A</span></th><th><span class="slb">SL B</span></th>'
            '<th><span class="slc">SL C</span></th><th><span class="sld">SL D</span></th>')

def _sl_cells(r, prefix="moy_sl"):
    return (f'<td>{pct_b(r[prefix+"a"])}</td><td>{pct_b(r[prefix+"b"])}</td>'
            f'<td>{pct_b(r[prefix+"c"])}</td><td>{pct_b(r[prefix+"d"])}</td>')

def cycle_table(rows):
    if not rows:
        return "<p style='color:#888;font-size:12px;padding:8px'>Données insuffisantes.</p>"
    best  = max(rows, key=lambda r: r["win_pct"])
    worst = min(rows, key=lambda r: r["win_pct"])
    hdr = (f'<thead><tr><th>Tranche</th><th>N</th><th>Win %</th>'
           f'<th>Moy. sans SL</th>{_sl_headers()}</tr></thead>')
    body = "<tbody>"
    for r in rows:
        cls = ("best" if r is best and r["win_pct"] >= 55
               else "worst" if r is worst and r["win_pct"] <= 40 else "")
        tr = f' class="{cls}"' if cls else ""
        body += (f'<tr{tr}><td><b>{r["label"]}</b></td><td>{r["n"]}</td>'
                 f'<td>{win_b(r["win_pct"])}</td><td>{pct_b(r["moy_ss"])}</td>'
                 f'{_sl_cells(r)}</tr>')
    return f'<div class="table-wrap"><table>{hdr}{body}</tbody></table></div>'


def bb_table(rows):
    if not rows:
        return "<p style='color:#888;font-size:12px;padding:8px'>Données insuffisantes.</p>"
    best = max(rows, key=lambda r: r["win_pct_a"]) if rows else None
    hdr = (f'<thead><tr><th>Tranche</th><th>N</th>'
           f'<th>Win% <span class="sla">A</span></th>'
           f'<th>Win% <span class="slb">B</span></th>'
           f'<th>Win% <span class="slc">C</span></th>'
           f'<th>Win% <span class="sld">D</span></th>'
           f'{_sl_headers()}</tr></thead>')
    body = "<tbody>"
    for r in rows:
        cls = "best" if r is best and r["win_pct_a"] >= 55 else ""
        tr = f' class="{cls}"' if cls else ""
        body += (f'<tr{tr}><td><b>{r["label"]}</b></td><td>{r["n"]}</td>'
                 f'<td>{win_b(r["win_pct_a"])}</td>'
                 f'<td>{win_b(r["win_pct_b"])}</td>'
                 f'<td>{win_b(r["win_pct_c"])}</td>'
                 f'<td>{win_b(r["win_pct_d"])}</td>'
                 f'{_sl_cells(r)}</tr>')
    return f'<div class="table-wrap"><table>{hdr}{body}</tbody></table></div>'


def auto_obs_cycle(rows):
    valid = [r for r in rows if r["n"] >= 2]
    if not valid:
        return ""
    best  = max(valid, key=lambda r: r["win_pct"])
    worst = min(valid, key=lambda r: r["win_pct"])
    parts = []
    if best["win_pct"] >= 55:
        parts.append(f'<span style="color:#0f6e56">✓ {best["label"]} : {best["n"]} cycles, {best["win_pct"]}% win — SL A {best["moy_sla"]:+.1f}%</span>')
    if worst["win_pct"] <= 40 and worst is not best:
        parts.append(f'<span style="color:#a32d2d">■ {worst["label"]} : {worst["n"]} cycles, {worst["win_pct"]}% win — zone à éviter</span>')
    return ('<div class="obs">' + ' &nbsp;&nbsp;·&nbsp;&nbsp; '.join(parts) + '</div>') if parts else ""


def auto_obs_bb(rows):
    valid = [r for r in rows if r["n"] >= 2]
    if not valid:
        return ""
    best  = max(valid, key=lambda r: r["win_pct_a"])
    worst = min(valid, key=lambda r: r["win_pct_a"])
    parts = []
    if best["win_pct_a"] >= 55:
        parts.append(f'<span style="color:#0f6e56">✓ {best["label"]} : {best["n"]} signaux, {best["win_pct_a"]}% gains SL A ({best["moy_sla"]:+.1f}% moy)</span>')
    if worst["win_pct_a"] <= 40 and worst is not best:
        parts.append(f'<span style="color:#a32d2d">■ {worst["label"]} : {worst["n"]} signaux, {worst["win_pct_a"]}% gains SL A — zone à éviter</span>')
    return ('<div class="obs">' + ' &nbsp;&nbsp;·&nbsp;&nbsp; '.join(parts) + '</div>') if parts else ""


def td_table(groups, cycle_data_or_bb, is_bb=False):
    """Table Pays/Secteur/Vue W générique."""
    key_a = "win_pct_a" if is_bb else "win_pct"
    hdr = (f'<thead><tr><th>Filtre</th><th>N</th><th>Win %</th>'
           + ('' if is_bb else '<th>Moy. sans SL</th>')
           + _sl_headers() + '</tr></thead>')
    body = "<tbody>"
    for label, filt in groups:
        sub = [it for it in cycle_data_or_bb if filt(it)]
        n = len(sub)
        if n == 0:
            continue
        if is_bb:
            wa = round(sum(1 for b in sub if b["pct_sla"] > 0) / n * 100)
            row_cells = (f'<td><b>{label}</b></td><td>{n}</td><td>{win_b(wa)}</td>'
                         f'<td>{pct_b(round(sum(b["pct_sla"] for b in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(b["pct_slb"] for b in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(b["pct_slc"] for b in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(b["pct_sld"] for b in sub)/n,1))}</td>')
        else:
            wc = round(sum(1 for c in sub if c["sans_sl"] > 0) / n * 100)
            mss = round(sum(c["sans_sl"] for c in sub) / n, 1)
            row_cells = (f'<td><b>{label}</b></td><td>{n}</td><td>{win_b(wc)}</td>'
                         f'<td>{pct_b(mss)}</td>'
                         f'<td>{pct_b(round(sum(c["pct_sla"] for c in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(c["pct_slb"] for c in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(c["pct_slc"] for c in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(c["pct_sld"] for c in sub)/n,1))}</td>')
        body += f"<tr>{row_cells}</tr>"
    return f'<div class="table-wrap"><table>{hdr}{body}</tbody></table></div>'


def mois_table(items_by_month, is_bb=False):
    hdr = (f'<thead><tr><th>Mois</th><th>N</th><th>Win %</th>'
           + ('' if is_bb else '<th>Moy. sans SL</th>')
           + _sl_headers() + '</tr></thead>')
    body = "<tbody>"
    for m in sorted(items_by_month.keys()):
        sub = items_by_month[m]
        n = len(sub)
        if is_bb:
            wa = round(sum(1 for b in sub if b["pct_sla"] > 0) / n * 100)
            row_cells = (f'<td><b>{MOIS_FR[m-1]}</b></td><td>{n}</td><td>{win_b(wa)}</td>'
                         f'<td>{pct_b(round(sum(b["pct_sla"] for b in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(b["pct_slb"] for b in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(b["pct_slc"] for b in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(b["pct_sld"] for b in sub)/n,1))}</td>')
        else:
            wc = round(sum(1 for c in sub if c["sans_sl"] > 0) / n * 100)
            mss = round(sum(c["sans_sl"] for c in sub) / n, 1)
            row_cells = (f'<td><b>{MOIS_FR[m-1]}</b></td><td>{n}</td><td>{win_b(wc)}</td>'
                         f'<td>{pct_b(mss)}</td>'
                         f'<td>{pct_b(round(sum(c["pct_sla"] for c in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(c["pct_slb"] for c in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(c["pct_slc"] for c in sub)/n,1))}</td>'
                         f'<td>{pct_b(round(sum(c["pct_sld"] for c in sub)/n,1))}</td>')
        body += f"<tr>{row_cells}</tr>"
    return f'<div class="table-wrap"><table>{hdr}{body}</tbody></table></div>'


# ─── Génération HTML principale ───────────────────────────────────────────────

def generer_analyse(ticker, cycle_data, bb_data, mode, country_t, sector_t, period, config):
    if not cycle_data:
        return f"<p>Aucune donnée pour {ticker}.</p>"

    mode_label = "SHORT" if mode == "short" else "LONG"
    mode_color = "#a32d2d" if mode == "short" else "#0f6e56"
    mode_bg    = "#fcebeb" if mode == "short" else "#eaf3de"

    nb_cycles = len(cycle_data)
    nb_bb     = len(bb_data)

    # Stats globales cycles
    wins_ss   = sum(1 for c in cycle_data if c["sans_sl"] > 0)
    cumul_ss  = round(sum(c["sans_sl"] for c in cycle_data), 1)
    sl_cumuls = [round(sum(c[f"pct_sl{k}"] for c in cycle_data), 1) for k in "abcd"]
    sl_wins   = [sum(1 for c in cycle_data if c[f"pct_sl{k}"] > 0) for k in "abcd"]
    best_sl_i = max(range(4), key=lambda i: sl_cumuls[i])

    # Stats globales BB
    bb_wins_a  = sum(1 for b in bb_data if b["pct_sla"] > 0) if nb_bb else 0
    bb_cumul_a = round(sum(b["pct_sla"] for b in bb_data), 1) if nb_bb else 0

    # ─── Header ────────────────────────────────────────────────────────
    html = [f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8">
<title>BB Stats — {ticker}</title>
<style>{CSS}</style>
</head>
<body>
<h1>Analyse statistique BB — {ticker}
  <span style="font-size:14px;padding:3px 10px;border-radius:4px;background:{mode_bg};color:{mode_color};margin-left:8px">{mode_label}</span>
  <span style="font-size:14px;padding:3px 10px;border-radius:4px;background:#f0ede8;color:#555;margin-left:6px">{period}</span>
</h1>
<p class="meta">Pays : {country_t or '—'} · Secteur : {sector_t or '—'} · Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')} · RSI/ADX méthode Wilder · Entrée au close N+1</p>
<p class="note">Ce rapport analyse <b>{nb_cycles} cycles {mode_label.lower()}s</b> et <b>{nb_bb} signaux BB intra-cycle</b>. Les sections 1–8 couvrent le niveau des cycles (conditions d'entrée). Les sections 9–15 se focalisent sur les signaux Bollinger.</p>
"""]

    # ─── KPIs ──────────────────────────────────────────────────────────
    html.append('<div class="kpis">')
    html.append(f'<div class="kpi"><div class="kl">Cycles {mode_label}</div><div class="kv">{nb_cycles}</div></div>')
    wr_ss = round(wins_ss / nb_cycles * 100)
    html.append(f'<div class="kpi"><div class="kl">Win rate cycles</div><div class="kv {"green" if wr_ss >= 50 else "red"}">{wr_ss}%</div></div>')
    html.append(f'<div class="kpi"><div class="kl">Cumulé sans SL</div><div class="kv {"green" if cumul_ss >= 0 else "red"}">{cumul_ss:+.1f}%</div></div>')
    html.append(f'<div class="kpi"><div class="kl">Meilleur SL</div><div class="kv" style="font-size:16px;color:{SL_CFGS[best_sl_i]["color"]}">{SL_CFGS[best_sl_i]["nom"]} ({sl_cumuls[best_sl_i]:+.1f}%)</div></div>')
    if nb_bb > 0:
        wr_bb = round(bb_wins_a / nb_bb * 100)
        html.append(f'<div class="kpi"><div class="kl">Signaux BB</div><div class="kv">{nb_bb}</div></div>')
        html.append(f'<div class="kpi"><div class="kl">Win% BB (SL A)</div><div class="kv {"green" if wr_bb >= 50 else "red"}">{wr_bb}%</div></div>')
        html.append(f'<div class="kpi"><div class="kl">Cumulé BB (SL A)</div><div class="kv {"green" if bb_cumul_a >= 0 else "red"}">{bb_cumul_a:+.1f}%</div></div>')
    html.append('</div>')

    # ─── Section 1 : Résumé SL ─────────────────────────────────────────
    html.append('<h2>1 — Résumé des stratégies SL sur les cycles</h2>')
    html.append('<div class="table-wrap"><table><thead><tr><th>Stratégie</th><th>Règle</th><th>Win rate</th><th>Cumulé</th><th>Note</th></tr></thead><tbody>')
    for i, sl in enumerate(SL_CFGS):
        wr = round(sl_wins[i] / nb_cycles * 100)
        cum = sl_cumuls[i]
        is_best = (i == best_sl_i)
        tr_s = ' style="background:#fffbf0"' if is_best else ''
        note = " ← meilleur cumulé" if is_best else ""
        html.append(f'<tr{tr_s}><td><b><span class="{sl["key"]}">{sl["nom"]}</span></b>{note}</td>'
                    f'<td style="color:#666">{sl["desc"]}</td>'
                    f'<td>{win_b(wr, f" ({sl_wins[i]}/{nb_cycles})")}</td>'
                    f'<td>{pct_b(cum)}</td>'
                    f'<td style="font-size:11px;color:#666">{"Capture les grandes tendances" if sl["palier"] >= 7.5 else "Protection rapide" if sl["sl_init"] == -2.5 and sl["be"] is None else "Bon compromis" if sl["sl_init"] == -5.0 else "Breakeven intégré"}</td></tr>')
    html.append('</tbody></table></div>')

    # ─── Tranches pour les cycles ───────────────────────────────────────
    RSI_C = [("RSI < 50",0,50),("RSI 50–59",50,60),("RSI 60–65",60,66),("RSI 66–70",66,71),("RSI ≥ 71",71,999)]
    ADX_C = [("ADX < 12",0,12),("ADX 12–17",12,18),("ADX 18–22",18,23),("ADX 23–27",23,28),("ADX ≥ 28",28,999)]
    VOL_C = [("Vol < 0.85",0,0.85),("Vol 0.85–1.10",0.85,1.10),("Vol 1.10–1.60",1.10,1.60),("Vol ≥ 1.60",1.60,999)]
    DUR_C = [("< 10j",0,10),("10–40j",10,40),("40–70j",40,70),("70–110j",70,110),("≥ 110j",110,9999)]

    html.append('<h2>2 — RSI d\'entrée (signal de cycle)</h2>')
    rsi_c = stat_rows(cycle_data, lambda c: c["rsi"], RSI_C)
    html.append(auto_obs_cycle(rsi_c))
    html.append(cycle_table(rsi_c))

    html.append('<h2>3 — ADX d\'entrée (signal de cycle)</h2>')
    adx_c = stat_rows(cycle_data, lambda c: c["adx"], ADX_C)
    html.append(auto_obs_cycle(adx_c))
    html.append(cycle_table(adx_c))

    html.append('<h2>4 — Volume d\'entrée (signal de cycle)</h2>')
    vol_c = stat_rows(cycle_data, lambda c: c["vol"], VOL_C)
    html.append(auto_obs_cycle(vol_c))
    html.append(cycle_table(vol_c))

    html.append('<h2>5 — Durée des cycles</h2>')
    dur_c = stat_rows(cycle_data, lambda c: c["duree"], DUR_C)
    html.append(auto_obs_cycle(dur_c))
    html.append(cycle_table(dur_c))

    html.append('<h2>6 — Filtres top-down (Pays + Secteur)</h2>')
    html.append(td_table([
        ("Pays ✓ + Secteur ✓", lambda c: c["ok_pays"] and c["ok_secteur"]),
        ("Pays ✓ seul (Secteur ✗)", lambda c: c["ok_pays"] and not c["ok_secteur"]),
        ("Secteur ✓ seul (Pays ✗)", lambda c: not c["ok_pays"] and c["ok_secteur"]),
        ("Aucun filtre", lambda c: not c["ok_pays"] and not c["ok_secteur"]),
    ], cycle_data))

    html.append('<h2>7 — Vue Weekly</h2>')
    html.append(td_table([
        ("Vue W ✓ confirmée", lambda c: c["ok_weekly"]),
        ("Vue W ✗ absente",   lambda c: not c["ok_weekly"]),
    ], cycle_data))

    html.append('<h2>8 — Saisonnalité des cycles (mois du signal)</h2>')
    months_c = {}
    for c in cycle_data:
        months_c.setdefault(c["signal_date"].month, []).append(c)
    html.append(mois_table(months_c, is_bb=False))

    # ═══════════════════════════════════════════════════
    # PARTIE BB (focus principal)
    # ═══════════════════════════════════════════════════

    if not bb_data:
        html.append('<h2 class="bb-title">9 — Signaux Bollinger</h2>')
        html.append('<p style="color:#888;padding:8px">Aucun signal BB détecté sur cette période.</p>')
        html.append(f'<p class="footer">BB Analyser · {ticker} · {period} · {datetime.now().strftime("%d/%m/%Y %H:%M")}</p>')
        html.append('</body></html>')
        return "\n".join(html)

    # Tranches RSI/ADX adaptées au mode
    if mode == "short":
        # En SHORT : touche BB haute → RSI souvent élevé (surachat)
        RSI_BB = [("RSI < 50",0,50),("RSI 50–60",50,60),("RSI 60–65",60,66),("RSI 66–70",66,71),("RSI 71–80",71,81),("RSI ≥ 80",80,999)]
    else:
        # En LONG : touche BB basse → RSI souvent bas (survente)
        RSI_BB = [("RSI < 25",0,25),("RSI 25–32",25,33),("RSI 33–40",33,41),("RSI 41–48",41,49),("RSI ≥ 49",49,999)]

    ADX_BB  = [("ADX < 12",0,12),("ADX 12–17",12,18),("ADX 18–22",18,23),("ADX 23–27",23,28),("ADX ≥ 28",28,999)]
    VOL_BB  = [("Vol < 0.70",0,0.70),("Vol 0.70–1.0",0.70,1.0),("Vol 1.0–1.5",1.0,1.5),("Vol 1.5–2.5",1.5,2.5),("Vol ≥ 2.5",2.5,999)]
    DUR_BB  = [("Cycle < 40j",0,40),("Cycle 40–70j",40,70),("Cycle 70–110j",70,110),("Cycle ≥ 110j",110,9999)]

    html.append('<h2 class="bb-title">9 — Signaux Bollinger — Vue d\'ensemble</h2>')

    # Tableau résumé global avec combos clés
    COMBOS_OV = [
        ("Total",                          lambda b: True),
        ("RSI < 50 au signal BB" if mode=="short" else "RSI < 40 au signal BB",
         (lambda b: b["rsi"] < 50) if mode=="short" else (lambda b: b["rsi"] < 40)),
        ("RSI ≥ 50 au signal BB" if mode=="short" else "RSI ≥ 40 au signal BB",
         (lambda b: b["rsi"] >= 50) if mode=="short" else (lambda b: b["rsi"] >= 40)),
        ("ADX < 20 au signal BB",          lambda b: b["adx"] < 20),
        ("ADX 20–26 au signal BB",         lambda b: 20 <= b["adx"] < 26),
        ("ADX ≥ 26 au signal BB",          lambda b: b["adx"] >= 26),
        ("ADX ≤ 20 + Vol < 1.5",           lambda b: b["adx"] <= 20 and b["vol"] < 1.5),
        ("ADX ≤ 22 + RSI < 50" if mode=="short" else "ADX ≤ 22 + RSI < 40",
         (lambda b: b["adx"] <= 22 and b["rsi"] < 50) if mode=="short"
         else (lambda b: b["adx"] <= 22 and b["rsi"] < 40)),
    ]

    hdr_ov = (f'<thead><tr><th>Critère</th><th>Signaux</th>'
              f'<th>Win% <span class="sla">A</span></th>'
              f'<th>Win% <span class="slb">B</span></th>'
              f'<th>Win% <span class="slc">C</span></th>'
              f'<th>Win% <span class="sld">D</span></th>'
              + _sl_headers() + '</tr></thead>')
    body_ov = "<tbody>"
    for label, filt in COMBOS_OV:
        sub = [b for b in bb_data if filt(b)]
        n = len(sub)
        if n < 2 and label != "Total":
            continue
        if n == 0:
            continue
        wa = round(sum(1 for b in sub if b["pct_sla"] > 0) / n * 100)
        wb = round(sum(1 for b in sub if b["pct_slb"] > 0) / n * 100)
        wc = round(sum(1 for b in sub if b["pct_slc"] > 0) / n * 100)
        wd = round(sum(1 for b in sub if b["pct_sld"] > 0) / n * 100)
        msla = round(sum(b["pct_sla"] for b in sub)/n,1)
        mslb = round(sum(b["pct_slb"] for b in sub)/n,1)
        mslc = round(sum(b["pct_slc"] for b in sub)/n,1)
        msld = round(sum(b["pct_sld"] for b in sub)/n,1)
        is_total = label == "Total"
        tr_s = ' style="font-weight:600"' if is_total else ""
        body_ov += (f'<tr{tr_s}><td><b>{label}</b></td><td>{n}</td>'
                    f'<td>{win_b(wa)}</td><td>{win_b(wb)}</td>'
                    f'<td>{win_b(wc)}</td><td>{win_b(wd)}</td>'
                    f'<td>{pct_b(msla)}</td><td>{pct_b(mslb)}</td>'
                    f'<td>{pct_b(mslc)}</td><td>{pct_b(msld)}</td></tr>')
    html.append(f'<div class="table-wrap"><table>{hdr_ov}{body_ov}</tbody></table></div>')

    html.append('<h2>10 — RSI au moment du signal BB</h2>')
    bb_rsi = bb_stat_rows(bb_data, lambda b: b["rsi"], RSI_BB)
    html.append(auto_obs_bb(bb_rsi))
    html.append(bb_table(bb_rsi))

    html.append('<h2>11 — ADX au moment du signal BB</h2>')
    bb_adx = bb_stat_rows(bb_data, lambda b: b["adx"], ADX_BB)
    html.append(auto_obs_bb(bb_adx))
    html.append(bb_table(bb_adx))

    html.append('<h2>12 — Volume au moment du signal BB</h2>')
    bb_vol = bb_stat_rows(bb_data, lambda b: b["vol"], VOL_BB)
    html.append(auto_obs_bb(bb_vol))
    html.append(bb_table(bb_vol))

    html.append('<h2>13 — Saisonnalité des signaux BB</h2>')
    months_bb = {}
    for b in bb_data:
        months_bb.setdefault(b["date"].month, []).append(b)
    html.append(mois_table(months_bb, is_bb=True))

    html.append('<h2>14 — Contexte du cycle hôte et filtres top-down</h2>')
    html.append('<div class="two-col">')

    html.append('<div><h3>Durée du cycle hôte</h3>')
    bb_dur = bb_stat_rows(bb_data, lambda b: b["cycle_duree"], DUR_BB)
    html.append(bb_table(bb_dur))
    html.append(auto_obs_bb(bb_dur))
    html.append('</div>')

    html.append('<div><h3>Filtres top-down et Vue W au signal BB</h3>')
    html.append(td_table([
        ("Pays ✓ + Secteur ✓", lambda b: b["ok_pays"] and b["ok_secteur"]),
        ("Pays ✓ seul",         lambda b: b["ok_pays"] and not b["ok_secteur"]),
        ("Secteur ✓ seul",      lambda b: not b["ok_pays"] and b["ok_secteur"]),
        ("Aucun",               lambda b: not b["ok_pays"] and not b["ok_secteur"]),
        ("Vue W ✓",             lambda b: b["ok_weekly"]),
        ("Vue W ✗",             lambda b: not b["ok_weekly"]),
    ], bb_data, is_bb=True))
    html.append('</div>')

    html.append('</div>')  # two-col

    # ─── Section 15 : Combinaisons ──────────────────────────────────────
    html.append('<h2>15 — Combinaisons optimales BB</h2>')

    rsi_lo = 50 if mode == "short" else 40
    COMBOS = [
        (f"RSI < {rsi_lo} + ADX < 18",
         lambda b: b["rsi"] < rsi_lo and b["adx"] < 18),
        (f"RSI < {rsi_lo} + ADX 18–22",
         lambda b: b["rsi"] < rsi_lo and 18 <= b["adx"] < 23),
        (f"RSI < {rsi_lo} + ADX 23–27",
         lambda b: b["rsi"] < rsi_lo and 23 <= b["adx"] < 28),
        (f"RSI ≥ {rsi_lo} + ADX < 20",
         lambda b: b["rsi"] >= rsi_lo and b["adx"] < 20),
        (f"RSI < {rsi_lo} + ADX < 22 + Vol < 2",
         lambda b: b["rsi"] < rsi_lo and b["adx"] < 22 and b["vol"] < 2),
        (f"RSI < {rsi_lo} + ADX ≥ 26",
         lambda b: b["rsi"] < rsi_lo and b["adx"] >= 26),
        ("Pays ✓ + Sect ✓ + ADX < 22",
         lambda b: b["ok_pays"] and b["ok_secteur"] and b["adx"] < 22),
        (f"Pays ✓ + Sect ✓ + RSI < {rsi_lo}",
         lambda b: b["ok_pays"] and b["ok_secteur"] and b["rsi"] < rsi_lo),
        (f"Cycle ≥ 70j + RSI < {rsi_lo}",
         lambda b: b["cycle_duree"] >= 70 and b["rsi"] < rsi_lo),
        ("Cycle ≥ 70j + ADX < 22",
         lambda b: b["cycle_duree"] >= 70 and b["adx"] < 22),
        (f"Cycle ≥ 70j + RSI < {rsi_lo} + ADX < 22",
         lambda b: b["cycle_duree"] >= 70 and b["rsi"] < rsi_lo and b["adx"] < 22),
    ]

    combo_rows = []
    for label, filt in COMBOS:
        sub = [b for b in bb_data if filt(b)]
        n = len(sub)
        if n < 2:
            continue
        wa = round(sum(1 for b in sub if b["pct_sla"] > 0) / n * 100)
        wb = round(sum(1 for b in sub if b["pct_slb"] > 0) / n * 100)
        wc = round(sum(1 for b in sub if b["pct_slc"] > 0) / n * 100)
        wd = round(sum(1 for b in sub if b["pct_sld"] > 0) / n * 100)
        msla = round(sum(b["pct_sla"] for b in sub)/n,1)
        mslb = round(sum(b["pct_slb"] for b in sub)/n,1)
        mslc = round(sum(b["pct_slc"] for b in sub)/n,1)
        msld = round(sum(b["pct_sld"] for b in sub)/n,1)
        combo_rows.append((label, n, wa, wb, wc, wd, msla, mslb, mslc, msld))

    combo_rows.sort(key=lambda x: x[2], reverse=True)

    hdr_c = (f'<thead><tr><th>Combinaison</th><th>N</th>'
             f'<th>Win% <span class="sla">A</span></th>'
             f'<th>Win% <span class="slb">B</span></th>'
             f'<th>Win% <span class="slc">C</span></th>'
             f'<th>Win% <span class="sld">D</span></th>'
             + _sl_headers() + '</tr></thead>')
    body_c = "<tbody>"
    for label, n, wa, wb, wc, wd, msla, mslb, mslc, msld in combo_rows:
        tr_s = (' class="best"' if wa >= 60 else ' class="worst"' if wa < 35 else '')
        body_c += (f'<tr{tr_s}><td><b>{label}</b></td><td>{n}</td>'
                   f'<td>{win_b(wa)}</td><td>{win_b(wb)}</td>'
                   f'<td>{win_b(wc)}</td><td>{win_b(wd)}</td>'
                   f'<td>{pct_b(msla)}</td><td>{pct_b(mslb)}</td>'
                   f'<td>{pct_b(mslc)}</td><td>{pct_b(msld)}</td></tr>')
    html.append(f'<div class="table-wrap"><table>{hdr_c}{body_c}</tbody></table></div>')

    # ─── Section 16 : Checklist ─────────────────────────────────────────
    html.append('<h2>16 — Checklist d\'entrée optimale (BB)</h2>')

    # Dériver les meilleurs filtres automatiquement
    def best_bb_filter(rows):
        valid = [r for r in rows if r["n"] >= 3]
        return max(valid, key=lambda r: r["win_pct_a"]) if valid else None

    best_rsi = best_bb_filter(bb_rsi)
    best_adx = best_bb_filter(bb_adx)
    best_vol = best_bb_filter(bb_vol)
    best_dur = best_bb_filter(bb_dur)

    # Meilleurs et pires mois BB
    best_m = max(months_bb.items(),
                 key=lambda kv: sum(1 for b in kv[1] if b["pct_sla"] > 0)/len(kv[1])) if months_bb else None
    worst_ms = [MOIS_FR[m-1] for m, bs in months_bb.items()
                if len(bs) >= 2 and sum(1 for b in bs if b["pct_sla"] > 0)/len(bs) < 0.35]

    # ADX ≥ 26 warning
    adx26 = [b for b in bb_data if b["adx"] >= 26]
    adx26_warn = (len(adx26) >= 3
                  and round(sum(1 for b in adx26 if b["pct_sla"] > 0)/len(adx26)*100) <= 40)

    checklist = [
        ("Stratégie SL",       "Obligatoire", "#185fa5",
         f'{SL_CFGS[best_sl_i]["nom"]} ({SL_CFGS[best_sl_i]["desc"]}) — meilleur cumulé sur les cycles ({sl_cumuls[best_sl_i]:+.1f}%)'),
    ]
    if best_rsi:
        checklist.append(("RSI au signal BB", "Recommandé", "#3b6d11",
            f'{best_rsi["label"]} — meilleure zone ({best_rsi["win_pct_a"]}% win SL A, {best_rsi["moy_sla"]:+.1f}% moy)'))
    if best_adx:
        checklist.append(("ADX au signal BB", "Recommandé", "#3b6d11",
            f'{best_adx["label"]} — zone optimale ({best_adx["win_pct_a"]}% win SL A)'))
    if best_vol and best_vol["win_pct_a"] >= 55:
        checklist.append(("Volume au signal BB", "Optionnel", "#888",
            f'{best_vol["label"]} — {best_vol["win_pct_a"]}% win SL A'))
    if best_dur and best_dur["win_pct_a"] >= 60:
        checklist.append(("Durée cycle hôte", "Optionnel", "#888",
            f'{best_dur["label"]} — {best_dur["win_pct_a"]}% win : préférer les signaux BB dans les cycles longs'))
    if best_m:
        m_label = MOIS_FR[best_m[0]-1]
        wr_m = round(sum(1 for b in best_m[1] if b["pct_sla"] > 0)/len(best_m[1])*100)
        detail = f"Meilleur mois : {m_label} ({wr_m}%)"
        if worst_ms:
            detail += f" — éviter : {', '.join(worst_ms)}"
        checklist.append(("Saisonnalité", "Optionnel", "#888", detail))
    if adx26_warn:
        wr26 = round(sum(1 for b in adx26 if b["pct_sla"] > 0)/len(adx26)*100)
        checklist.append(("ADX ≥ 26 signal BB", "Éviter", "#a32d2d",
            f'{len(adx26)} signaux, {wr26}% win SL A — ADX fort = tendance établie, BB peu fiable'))

    html.append('<div class="checklist">')
    for critere, obligation, color, detail in checklist:
        html.append(f'<div class="check-row">'
                    f'<div style="font-weight:500">{critere}</div>'
                    f'<div style="font-weight:600;color:{color}">{obligation}</div>'
                    f'<div style="color:#444;font-size:12px">{detail}</div>'
                    f'</div>')
    html.append('</div>')

    cfg_bol = config.get("bollinger", {})
    html.append(f'<p class="footer">BB Analyser · {ticker} · {period} · {datetime.now().strftime("%d/%m/%Y %H:%M")} · '
                f'Données Yahoo Finance · RSI/ADX Wilder · BB {cfg_bol.get("periode",20)} périodes ×{cfg_bol.get("ecarts",2)} '
                f'± {cfg_bol.get("tolerance_pct",1.0)}% tolérance · Les résultats passés ne préjugent pas des résultats futurs.</p>')
    html.append('</body></html>')

    return "\n".join(html)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="BB Analyser — Analyse statistique des signaux Bollinger")
    parser.add_argument("--ticker",  required=False)
    parser.add_argument("--mode",    choices=["long", "short"], default="short")
    parser.add_argument("--period",  default="3y")
    parser.add_argument("--country", default=None)
    parser.add_argument("--sector",  default=None)
    parser.add_argument("--output",  default=None)
    args = parser.parse_args()

    config = charger_config()
    tf     = config["scan"]["timeframe"]

    tickers = [args.ticker.upper()] if args.ticker else charger_tickers()
    if not tickers:
        print("Aucun ticker. Utilisez --ticker SYMBOL ou remplissez tickers.txt")
        sys.exit(1)

    print("Téléchargement données annexes...")
    df_country = telecharger(args.country, tf, args.period) if args.country else None
    df_sector  = telecharger(args.sector,  tf, args.period) if args.sector  else None

    for ticker in tickers:
        print(f"Analyse BB de {ticker} ({args.period}, mode {args.mode.upper()})...")
        df = telecharger(ticker, tf, args.period)
        if df is None:
            print(f"  → Données insuffisantes pour {ticker}, ignoré.")
            continue

        df_weekly = telecharger(ticker, "1wk", args.period)
        cycles    = detecter_cycles(df, config, args.mode)
        print(f"  → {len(cycles)} cycle(s) détecté(s)")

        cycle_data, bb_data = construire_donnees(
            cycles, args.mode, config, df_country, df_sector, df_weekly
        )
        print(f"  → {len(bb_data)} signal(s) BB")

        html = generer_analyse(
            ticker, cycle_data, bb_data, args.mode,
            args.country, args.sector, args.period, config
        )

        output = args.output or f"BB_Stats__{ticker.replace('-', '')}.html"
        Path(output).write_text(html, encoding="utf-8")
        print(f"  → Rapport généré : {output}")

        import webbrowser
        webbrowser.open(f"file:///{Path(output).resolve().as_posix()}")


if __name__ == "__main__":
    main()
