#!/usr/bin/env python3
"""
BB Analyser — Analyse statistique des signaux Bollinger
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
    {"nom": "SL A", "desc": "init -2.5%, pal.5%",          "sl_init": -2.5, "palier": 5.0, "be": None, "color": "#378add", "key": "sla"},
    {"nom": "SL B", "desc": "init -5%, pal.5%",            "sl_init": -5.0, "palier": 5.0, "be": None, "color": "#3b6d11", "key": "slb"},
    {"nom": "SL C", "desc": "init -7.5%, pal.7.5%",        "sl_init": -7.5, "palier": 7.5, "be": None, "color": "#ba7517", "key": "slc"},
    {"nom": "SL D", "desc": "init -2.5% / BE+5% / pal.5%", "sl_init": -2.5, "palier": 5.0, "be":  5.0, "color": "#7b3fa0", "key": "sld"},
]
MOIS_FR = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]


# ─── Construction du dataset ──────────────────────────────────────────────────

def construire_donnees(cycles, mode, config, df_c, df_s):
    """
    Retourne (cycle_data, bb_data, bb_seq_data).

    bb_data     : toutes les touches BB du cycle, indépendantes.
    bb_seq_data : entrées séquentielles (SL A comme gate — on avance de nb_jours SL A
                  après chaque trade). Pour chaque entrée, les 4 SLs sont simulés depuis
                  le même point k, ce qui permet la comparaison inter-SL.
    """
    cycle_data, bb_data, bb_seq_data = [], [], []

    for cycle in cycles:
        jours = cycle["jours"]
        if not jours:
            continue

        j0          = jours[0]
        signal_date = cycle["signal_date"]

        sl_pcts = [
            simuler_sl(jours, 0, mode, sl["sl_init"], sl["palier"], sl["be"])[0]
            for sl in SL_CFGS
        ]

        pe, pf = jours[0]["prix"], jours[-1]["prix"]
        sans_sl = round((pe - pf) / pe * 100 if mode == "short"
                        else (pf - pe) / pe * 100, 2)

        ok_p = verifier_cycle(df_c, signal_date, mode, config)
        ok_s = verifier_cycle(df_s, signal_date, mode, config)

        cycle_data.append({
            "signal_date": signal_date,
            "duree":       len(jours),
            "rsi":  j0["rsi"], "adx": j0["adx"], "vol": j0["vol"],
            "sans_sl":  sans_sl,
            "pct_sla":  sl_pcts[0], "pct_slb": sl_pcts[1],
            "pct_slc":  sl_pcts[2], "pct_sld": sl_pcts[3],
            "ok_pays": ok_p, "ok_secteur": ok_s,
        })

        # ── bb_data : toutes touches BB (4 SL en parallèle) ───────────
        bb_lists = [
            calc_bb_rendement(jours, mode, sl["sl_init"], sl["palier"], sl["be"])[0]
            for sl in SL_CFGS
        ]
        date_to_idx = {j["date"]: idx for idx, j in enumerate(jours)}
        for i in range(len(bb_lists[0])):
            base = bb_lists[0][i]
            bb_data.append({
                "date": base["date"],
                "rsi":  base["rsi"], "adx": base["adx"], "vol": base["vol"],
                "pct_sla": bb_lists[0][i]["pct"],
                "pct_slb": bb_lists[1][i]["pct"],
                "pct_slc": bb_lists[2][i]["pct"],
                "pct_sld": bb_lists[3][i]["pct"],
                "jours_ecoules": date_to_idx.get(base["date"], 0),
                "ok_pays": ok_p, "ok_secteur": ok_s,
            })

        # ── bb_seq_data : séquentiel — gate = SL A ────────────────────
        # Avance de nb_jours SL A après chaque trade ; tous les SL sont
        # simulés depuis le même point k pour permettre la comparaison.
        k = 0
        while k < len(jours):
            j = jours[k]
            if not j["touche_bb"]:
                k += 1
                continue
            results = [
                simuler_sl(jours, k, mode, sl["sl_init"], sl["palier"], sl["be"])
                for sl in SL_CFGS
            ]
            _, raison_a, nb_j_a = results[0]
            bb_seq_data.append({
                "date": j["date"],
                "rsi":  j["rsi"], "adx": j["adx"], "vol": j["vol"],
                "pct_sla": round(results[0][0], 1),
                "pct_slb": round(results[1][0], 1),
                "pct_slc": round(results[2][0], 1),
                "pct_sld": round(results[3][0], 1),
                "jours_ecoules": date_to_idx.get(j["date"], 0),
                "ok_pays": ok_p, "ok_secteur": ok_s,
            })
            if raison_a == "Fin cycle":
                break
            k += nb_j_a

    return cycle_data, bb_data, bb_seq_data


# ─── Fonctions de stats ───────────────────────────────────────────────────────

def bb_stat_rows(items, key_func, tranches):
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


# ─── CSS ──────────────────────────────────────────────────────────────────────

CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f4f0;color:#1a1a1a;padding:2rem;max-width:1400px;margin:0 auto}
h1{font-size:22px;font-weight:500;margin-bottom:4px}
h2{font-size:15px;font-weight:600;margin:2rem 0 0.6rem;padding-bottom:6px;border-bottom:2px solid #e0ddd6}
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
.check-row{display:grid;grid-template-columns:200px 110px 1fr;gap:12px;padding:10px 0;border-bottom:0.5px solid #f0ede8;font-size:12px;align-items:start}
.check-row:last-child{border-bottom:none}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:960px){.two-col{grid-template-columns:1fr}}
.footer{font-size:11px;color:#aaa;margin-top:2rem;padding-top:1rem;border-top:0.5px solid #e0ddd6}

/* ── Toggle view ── */
.view-toggle{display:flex;gap:0;margin-bottom:1.5rem;border-radius:10px;overflow:hidden;border:0.5px solid #e0ddd6;width:fit-content;background:#fff}
.vt-btn{padding:10px 24px;font-size:13px;font-weight:500;border:none;cursor:pointer;background:#fff;color:#666;transition:background .15s,color .15s;outline:none}
.vt-btn:first-child{border-right:0.5px solid #e0ddd6}
.vt-btn.active{background:#1a1a1a;color:#fff;font-weight:600}
.vt-btn:hover:not(.active){background:#f5f4f0}
.view-badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:4px;margin-left:6px;vertical-align:middle}
.vb-bb{background:#eef3fb;color:#185fa5}
.vb-seq{background:#f0ede8;color:#555}

/* ── SL Scorecards ── */
.sl-scores{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:1.8rem}
@media(max-width:900px){.sl-scores{grid-template-columns:repeat(2,1fr)}}
.sl-score{background:#fff;border-radius:10px;padding:16px;border:0.5px solid #e0ddd6;border-top:4px solid var(--slc)}
.sl-score-name{font-size:13px;font-weight:700;color:var(--slc);margin-bottom:2px}
.sl-score-desc{font-size:10px;color:#aaa;margin-bottom:12px}
.sl-score-win{font-size:30px;font-weight:700;line-height:1.1;margin-bottom:2px}
.sl-score-win.g{color:#0f6e56}.sl-score-win.r{color:#a32d2d}.sl-score-win.n{color:#888}
.sl-score-sub{font-size:11px;color:#888;margin-bottom:10px}
.sl-score-cumul{font-size:13px;font-weight:600;margin-bottom:8px}
.sl-score-bar-track{background:#f0ede8;border-radius:4px;height:7px;margin-bottom:10px}
.sl-score-bar-fill{height:100%;border-radius:4px;background:var(--slc)}
.sl-score-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:5px}
.ssl{background:#f8f8f6;border-radius:6px;padding:6px 5px;text-align:center}
.ssl .sl{font-size:9px;color:#bbb;margin-bottom:2px}
.ssl .sv{font-size:12px;font-weight:700}

/* ── Horizontal bar charts ── */
.bar-sect{background:#fff;border-radius:10px;border:0.5px solid #e0ddd6;padding:18px 22px;margin-bottom:1.2rem}
.bar-sect-title{font-size:10px;font-weight:700;color:#aaa;text-transform:uppercase;letter-spacing:.6px;margin-bottom:14px}
.bar-row{display:grid;grid-template-columns:160px 1fr 50px;align-items:center;gap:10px;margin-bottom:8px}
.bar-row:last-child{margin-bottom:0}
.bar-lbl{font-size:11px;color:#444;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-track{background:#f0ede8;border-radius:4px;height:22px;overflow:hidden}
.bar-fill{height:100%;border-radius:4px;display:flex;align-items:center;justify-content:flex-end;padding-right:7px;font-size:10px;font-weight:700;color:#fff;min-width:4px;white-space:nowrap}
.bar-meta{font-size:10px;color:#aaa;text-align:right;line-height:1.3}
/* multi-SL bars */
.mbar-row{display:grid;grid-template-columns:160px 1fr;align-items:start;gap:10px;margin-bottom:10px}
.mbar-lbl{font-size:11px;color:#444;text-align:right;padding-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mbar-stacks{display:flex;flex-direction:column;gap:3px}
.mbar-line{display:flex;align-items:center;gap:6px}
.mbar-track{flex:1;background:#f0ede8;border-radius:3px;height:14px;overflow:hidden}
.mbar-fill{height:100%;border-radius:3px;display:flex;align-items:center;justify-content:flex-end;padding-right:5px;font-size:9px;font-weight:700;color:#fff;min-width:2px}
.mbar-sl-tag{font-size:9px;font-weight:700;width:26px;text-align:right;flex-shrink:0}
.mbar-rend{font-size:10px;font-weight:600;width:44px;text-align:right;flex-shrink:0}

/* ── Month heatmap ── */
.month-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:6px;margin-bottom:1.2rem}
@media(max-width:960px){.month-grid{grid-template-columns:repeat(6,1fr)}}
.mcell{border-radius:8px;padding:10px 4px 8px;text-align:center;border:0.5px solid #e0ddd6}
.mc-name{font-size:11px;font-weight:700}
.mc-n{font-size:10px;color:#888;margin:3px 0}
.mc-pct{font-size:16px;font-weight:700;line-height:1}
.mc-rend{font-size:10px;margin-top:3px}

/* ── Distribution rendements ── */
.dist-wrap{background:#fff;border-radius:10px;border:0.5px solid #e0ddd6;padding:16px 22px;margin-bottom:1.2rem}
.dist-title{font-size:10px;font-weight:700;color:#aaa;text-transform:uppercase;letter-spacing:.6px;margin-bottom:12px}
.dist-bars{display:flex;align-items:flex-end;gap:3px;height:90px}
.dist-bar-col{display:flex;flex-direction:column;align-items:center;flex:1}
.dist-bar-fill{border-radius:3px 3px 0 0;width:100%;min-height:3px}
.dist-bar-cnt{font-size:9px;color:#666;margin-top:2px;font-weight:600}
.dist-bar-lbl{font-size:8px;color:#aaa;margin-top:1px;white-space:nowrap}
.dist-row{display:flex;gap:12px;margin-top:4px}
.dist-legend-item{font-size:10px;color:#666;display:flex;align-items:center;gap:4px}
.dist-dot{width:9px;height:9px;border-radius:2px;flex-shrink:0}

/* ── Rank badges ── */
.rank1{display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;background:#fce97a;color:#7a5800}
.rank2{display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;background:#e4e4e4;color:#555}
.rank3{display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;background:#f0d9b5;color:#7a4d00}
"""

TOGGLE_JS = """
<script>
function setView(v) {
  document.getElementById('view-bb').style.display  = v === 'bb'  ? '' : 'none';
  document.getElementById('view-seq').style.display = v === 'seq' ? '' : 'none';
  document.getElementById('btn-bb').classList.toggle('active',  v === 'bb');
  document.getElementById('btn-seq').classList.toggle('active', v === 'seq');
}
</script>
"""


# ─── HTML helpers de base ─────────────────────────────────────────────────────

def pct_b(val):
    cls = "bg" if val > 0 else ("br" if val < 0 else "bn")
    return f'<span class="badge {cls}">{val:+.1f}%</span>'

def win_b(pct):
    cls = "bg" if pct >= 55 else ("br" if pct < 40 else "bn")
    return f'<span class="badge {cls}">{pct}%</span>'

def _sl_headers():
    return ('<th>Moy. <span class="sla">SL A</span></th>'
            '<th>Moy. <span class="slb">SL B</span></th>'
            '<th>Moy. <span class="slc">SL C</span></th>'
            '<th>Moy. <span class="sld">SL D</span></th>')

def _sl_cells(r, prefix="moy_sl"):
    return (f'<td>{pct_b(r[prefix+"a"])}</td><td>{pct_b(r[prefix+"b"])}</td>'
            f'<td>{pct_b(r[prefix+"c"])}</td><td>{pct_b(r[prefix+"d"])}</td>')


# ─── Composants visuels ───────────────────────────────────────────────────────

def sl_scorecard_html(bb_data):
    nb = len(bb_data)
    if nb == 0:
        return ""
    cards = []
    for sl in SL_CFGS:
        k    = sl["key"][-1]
        key  = f"pct_sl{k}"
        vals = [b[key] for b in bb_data]
        wins    = sum(1 for v in vals if v > 0)
        win_pct = round(wins / nb * 100)
        cumul   = round(sum(vals), 1)
        moy     = round(sum(vals) / nb, 1)
        best_t  = round(max(vals), 1) if vals else 0
        worst_t = round(min(vals), 1) if vals else 0
        win_cls = "g" if win_pct >= 55 else ("r" if win_pct < 40 else "n")
        cum_col = "#0f6e56" if cumul > 0 else "#a32d2d"
        moy_col = "#0f6e56" if moy > 0 else "#a32d2d"
        cards.append(f"""
<div class="sl-score" style="--slc:{sl['color']}">
  <div class="sl-score-name">{sl['nom']}</div>
  <div class="sl-score-desc">{sl['desc']}</div>
  <div class="sl-score-win {win_cls}">{win_pct}%</div>
  <div class="sl-score-sub">taux de réussite · {wins}/{nb} signaux</div>
  <div class="sl-score-cumul" style="color:{cum_col}">Cumulé {cumul:+.1f}%</div>
  <div class="sl-score-bar-track"><div class="sl-score-bar-fill" style="width:{win_pct}%"></div></div>
  <div class="sl-score-grid">
    <div class="ssl"><div class="sl">Moy./signal</div><div class="sv" style="color:{moy_col}">{moy:+.1f}%</div></div>
    <div class="ssl"><div class="sl">Meilleur</div><div class="sv" style="color:#0f6e56">{best_t:+.1f}%</div></div>
    <div class="ssl"><div class="sl">Pire</div><div class="sv" style="color:#a32d2d">{worst_t:+.1f}%</div></div>
  </div>
</div>""")
    return '<div class="sl-scores">' + "".join(cards) + '</div>'


def dist_rendement_html(bb_data):
    if not bb_data:
        return ""
    BUCKETS = [
        ("< −10%",    None, -10),
        ("−10→−7.5%", -10, -7.5),
        ("−7.5→−5%",  -7.5, -5),
        ("−5→−2.5%",  -5,  -2.5),
        ("−2.5→0%",   -2.5,  0),
        ("0→2.5%",      0,  2.5),
        ("2.5→5%",    2.5,    5),
        ("5→7.5%",    5,    7.5),
        ("7.5→10%",   7.5,   10),
        ("> 10%",      10,  None),
    ]
    nb = len(bb_data)
    all_counts = []
    for sl in SL_CFGS:
        k    = sl["key"][-1]
        vals = [b[f"pct_sl{k}"] for b in bb_data]
        cnts = [sum(1 for v in vals if (lo is None or v >= lo) and (hi is None or v < hi))
                for _, lo, hi in BUCKETS]
        all_counts.append(cnts)

    max_c = max(max(cnts) for cnts in all_counts) or 1
    sections = []
    for sl_i, sl in enumerate(SL_CFGS):
        cnts = all_counts[sl_i]
        bars = ""
        for bi, (label, lo, hi) in enumerate(BUCKETS):
            c = cnts[bi]
            h = max(round(c / max_c * 100), 1) if c > 0 else 0
            col = sl["color"] if (lo is not None and lo >= 0) else "#e0ddd6"
            if lo is None:
                col = "#e0ddd6"
            bars += (f'<div class="dist-bar-col">'
                     f'<div class="dist-bar-fill" style="height:{h}%;background:{col}"></div>'
                     f'<div class="dist-bar-cnt">{c if c > 0 else ""}</div>'
                     f'<div class="dist-bar-lbl">{label}</div>'
                     f'</div>')
        k    = sl["key"][-1]
        vals = [b[f"pct_sl{k}"] for b in bb_data]
        pos_n = sum(1 for v in vals if v > 0)
        neg_n = nb - pos_n
        sections.append(
            f'<div style="flex:1;min-width:280px">'
            f'<div style="font-size:11px;font-weight:700;color:{sl["color"]};margin-bottom:6px">'
            f'{sl["nom"]} — {sl["desc"]}</div>'
            f'<div class="dist-bars">{bars}</div>'
            f'<div class="dist-row">'
            f'<span class="dist-legend-item"><span class="dist-dot" style="background:#0f6e56"></span>+{pos_n} positifs</span>'
            f'<span class="dist-legend-item"><span class="dist-dot" style="background:#e0ddd6"></span>−{neg_n} négatifs</span>'
            f'</div></div>'
        )
    return (f'<div class="dist-wrap">'
            f'<div class="dist-title">Distribution des rendements par stratégie SL ({nb} signaux)</div>'
            f'<div style="display:flex;gap:16px;flex-wrap:wrap">{"".join(sections)}</div>'
            f'</div>')


def bar_chart_win(rows, title="Taux de réussite par tranche (Win% SL A)"):
    if not rows:
        return ""
    best = max(rows, key=lambda r: r["win_pct_a"])
    bars = ""
    for r in rows:
        w     = r["win_pct_a"]
        moy   = r["moy_sla"]
        col   = "#0f6e56" if w >= 55 else ("#ba7517" if w >= 40 else "#c0392b")
        width = max(w, 3)
        star  = " ★" if r is best and w >= 55 else ""
        rend_col = "#0f6e56" if moy > 0 else "#a32d2d"
        bars += (f'<div class="bar-row">'
                 f'<div class="bar-lbl">{r["label"]}{star}</div>'
                 f'<div class="bar-track"><div class="bar-fill" style="width:{width}%;background:{col}">{w}%</div></div>'
                 f'<div class="bar-meta">{r["n"]} sig.<br><span style="color:{rend_col};font-weight:600">{moy:+.1f}%</span></div>'
                 f'</div>')
    return f'<div class="bar-sect"><div class="bar-sect-title">{title}</div>{bars}</div>'


def bar_chart_multi_sl(rows, title="Win% et rendement moyen par tranche — toutes stratégies SL"):
    if not rows:
        return ""
    rows_html = ""
    for r in rows:
        stacks = ""
        for sl in SL_CFGS:
            k        = sl["key"][-1]
            w        = r[f"win_pct_{k}"]
            moy      = r[f"moy_sl{k}"]
            col      = sl["color"]
            rend_col = "#0f6e56" if moy > 0 else "#a32d2d"
            stacks += (f'<div class="mbar-line">'
                       f'<div class="mbar-sl-tag" style="color:{col}">{sl["nom"]}</div>'
                       f'<div class="mbar-track"><div class="mbar-fill" style="width:{max(w,2)}%;background:{col}">{w}%</div></div>'
                       f'<div class="mbar-rend" style="color:{rend_col}">{moy:+.1f}%</div>'
                       f'</div>')
        rows_html += (f'<div class="mbar-row">'
                      f'<div class="mbar-lbl">{r["label"]}<br><span style="font-size:10px;color:#aaa">{r["n"]} signaux</span></div>'
                      f'<div class="mbar-stacks">{stacks}</div>'
                      f'</div>')
    return f'<div class="bar-sect"><div class="bar-sect-title">{title}</div>{rows_html}</div>'


def mois_heatmap(months_bb):
    cells = ""
    for m in range(1, 13):
        items = months_bb.get(m, [])
        name  = MOIS_FR[m - 1]
        if not items:
            cells += (f'<div class="mcell" style="background:#f8f8f8;opacity:.45">'
                      f'<div class="mc-name" style="color:#ccc">{name}</div>'
                      f'<div class="mc-n">—</div>'
                      f'<div class="mc-pct" style="color:#ccc">—</div>'
                      f'</div>')
            continue
        n   = len(items)
        w   = round(sum(1 for b in items if b["pct_sla"] > 0) / n * 100)
        moy = round(sum(b["pct_sla"] for b in items) / n, 1)
        if w >= 65:
            bg, tc = "#d4edda", "#0f6e56"
        elif w >= 55:
            bg, tc = "#eaf3de", "#3b6d11"
        elif w >= 45:
            bg, tc = "#fef9ec", "#ba7517"
        elif w >= 35:
            bg, tc = "#fff0e0", "#a0580c"
        else:
            bg, tc = "#fcebeb", "#a32d2d"
        moy_col = "#0f6e56" if moy > 0 else "#a32d2d"
        cells += (f'<div class="mcell" style="background:{bg}">'
                  f'<div class="mc-name" style="color:{tc}">{name}</div>'
                  f'<div class="mc-n">{n} sig.</div>'
                  f'<div class="mc-pct" style="color:{tc}">{w}%</div>'
                  f'<div class="mc-rend" style="color:{moy_col}">{moy:+.1f}%</div>'
                  f'</div>')
    return f'<div class="month-grid">{cells}</div>'


def bb_table(rows):
    if not rows:
        return "<p style='color:#888;font-size:12px;padding:8px'>Données insuffisantes.</p>"
    best = max(rows, key=lambda r: r["win_pct_a"])
    hdr = (f'<thead><tr><th>Tranche</th><th>N</th>'
           f'<th>Win% <span class="sla">A</span></th>'
           f'<th>Win% <span class="slb">B</span></th>'
           f'<th>Win% <span class="slc">C</span></th>'
           f'<th>Win% <span class="sld">D</span></th>'
           f'{_sl_headers()}</tr></thead>')
    body = "<tbody>"
    for r in rows:
        cls  = "best" if r is best and r["win_pct_a"] >= 55 else ""
        tr   = f' class="{cls}"' if cls else ""
        body += (f'<tr{tr}><td><b>{r["label"]}</b></td><td>{r["n"]}</td>'
                 f'<td>{win_b(r["win_pct_a"])}</td>'
                 f'<td>{win_b(r["win_pct_b"])}</td>'
                 f'<td>{win_b(r["win_pct_c"])}</td>'
                 f'<td>{win_b(r["win_pct_d"])}</td>'
                 f'{_sl_cells(r)}</tr>')
    return f'<div class="table-wrap"><table>{hdr}{body}</tbody></table></div>'


def auto_obs_bb(rows):
    valid = [r for r in rows if r["n"] >= 2]
    if not valid:
        return ""
    best  = max(valid, key=lambda r: r["win_pct_a"])
    worst = min(valid, key=lambda r: r["win_pct_a"])
    parts = []
    if best["win_pct_a"] >= 55:
        parts.append(f'<span style="color:#0f6e56">✓ {best["label"]} : {best["n"]} signaux — '
                     f'{best["win_pct_a"]}% win SL A · moy {best["moy_sla"]:+.1f}% · '
                     f'SL B {best["moy_slb"]:+.1f}% · SL C {best["moy_slc"]:+.1f}% · SL D {best["moy_sld"]:+.1f}%</span>')
    if worst["win_pct_a"] <= 40 and worst is not best:
        parts.append(f'<span style="color:#a32d2d">■ {worst["label"]} : {worst["n"]} signaux — '
                     f'{worst["win_pct_a"]}% win SL A ({worst["moy_sla"]:+.1f}% moy) — zone à éviter</span>')
    return ('<div class="obs">' + ' &nbsp;·&nbsp; '.join(parts) + '</div>') if parts else ""


def mois_table(months_bb):
    hdr = (f'<thead><tr><th>Mois</th><th>N</th>'
           f'<th>Win% <span class="sla">A</span></th>'
           f'<th>Win% <span class="slb">B</span></th>'
           f'<th>Win% <span class="slc">C</span></th>'
           f'<th>Win% <span class="sld">D</span></th>'
           f'{_sl_headers()}</tr></thead>')
    body = "<tbody>"
    for m in sorted(months_bb.keys()):
        sub = months_bb[m]
        n   = len(sub)
        wa  = round(sum(1 for b in sub if b["pct_sla"] > 0) / n * 100)
        wb  = round(sum(1 for b in sub if b["pct_slb"] > 0) / n * 100)
        wc  = round(sum(1 for b in sub if b["pct_slc"] > 0) / n * 100)
        wd  = round(sum(1 for b in sub if b["pct_sld"] > 0) / n * 100)
        body += (f'<tr><td><b>{MOIS_FR[m-1]}</b></td><td>{n}</td>'
                 f'<td>{win_b(wa)}</td><td>{win_b(wb)}</td>'
                 f'<td>{win_b(wc)}</td><td>{win_b(wd)}</td>'
                 f'<td>{pct_b(round(sum(b["pct_sla"] for b in sub)/n,1))}</td>'
                 f'<td>{pct_b(round(sum(b["pct_slb"] for b in sub)/n,1))}</td>'
                 f'<td>{pct_b(round(sum(b["pct_slc"] for b in sub)/n,1))}</td>'
                 f'<td>{pct_b(round(sum(b["pct_sld"] for b in sub)/n,1))}</td></tr>')
    return f'<div class="table-wrap"><table>{hdr}{body}</tbody></table></div>'


def td_table(groups, bb_data):
    hdr = (f'<thead><tr><th>Filtre</th><th>N</th>'
           f'<th>Win% <span class="sla">A</span></th>'
           f'<th>Win% <span class="slb">B</span></th>'
           f'<th>Win% <span class="slc">C</span></th>'
           f'<th>Win% <span class="sld">D</span></th>'
           f'{_sl_headers()}</tr></thead>')
    body = "<tbody>"
    for label, filt in groups:
        sub = [b for b in bb_data if filt(b)]
        n   = len(sub)
        if n == 0:
            continue
        wa = round(sum(1 for b in sub if b["pct_sla"] > 0) / n * 100)
        wb = round(sum(1 for b in sub if b["pct_slb"] > 0) / n * 100)
        wc = round(sum(1 for b in sub if b["pct_slc"] > 0) / n * 100)
        wd = round(sum(1 for b in sub if b["pct_sld"] > 0) / n * 100)
        body += (f'<tr><td><b>{label}</b></td><td>{n}</td>'
                 f'<td>{win_b(wa)}</td><td>{win_b(wb)}</td>'
                 f'<td>{win_b(wc)}</td><td>{win_b(wd)}</td>'
                 f'<td>{pct_b(round(sum(b["pct_sla"] for b in sub)/n,1))}</td>'
                 f'<td>{pct_b(round(sum(b["pct_slb"] for b in sub)/n,1))}</td>'
                 f'<td>{pct_b(round(sum(b["pct_slc"] for b in sub)/n,1))}</td>'
                 f'<td>{pct_b(round(sum(b["pct_sld"] for b in sub)/n,1))}</td></tr>')
    return f'<div class="table-wrap"><table>{hdr}{body}</tbody></table></div>'


# ─── Section 9 : Synthèse avancée ────────────────────────────────────────────

def _cell_color(w):
    if w >= 65: return "#d4edda", "#0f6e56"
    if w >= 55: return "#eaf3de", "#3b6d11"
    if w >= 45: return "#fef9ec", "#ba7517"
    if w >= 35: return "#fff0e0", "#a0580c"
    return "#fcebeb", "#a32d2d"


def _matrix_html(bb_data, tranches_row, tranches_col, key_row, key_col, title, note=""):
    """Heatmap 2D : win% SL A pour chaque paire de tranches."""
    col_labels = [t[0] for t in tranches_col]
    hdr = f'<thead><tr><th style="background:#f5f4f0;white-space:nowrap">{title}</th>'
    for lbl in col_labels:
        hdr += f'<th style="background:#f5f4f0;text-align:center;white-space:nowrap">{lbl}</th>'
    hdr += '</tr></thead>'

    body = '<tbody>'
    for r_lbl, r_lo, r_hi in tranches_row:
        body += f'<tr><td style="font-weight:600;white-space:nowrap;padding:8px 10px">{r_lbl}</td>'
        for c_lbl, c_lo, c_hi in tranches_col:
            sub = [b for b in bb_data
                   if r_lo <= key_row(b) < r_hi and c_lo <= key_col(b) < c_hi]
            n = len(sub)
            if n < 2:
                body += '<td style="text-align:center;color:#ccc;background:#fafafa;padding:6px">—</td>'
            else:
                w   = round(sum(1 for b in sub if b["pct_sla"] > 0) / n * 100)
                moy = round(sum(b["pct_sla"] for b in sub) / n, 1)
                bg, tc = _cell_color(w)
                mc = "#0f6e56" if moy > 0 else "#a32d2d"
                body += (f'<td style="text-align:center;background:{bg};padding:8px 6px">'
                         f'<div style="font-size:14px;font-weight:700;color:{tc}">{w}%</div>'
                         f'<div style="font-size:10px;color:#888">{n} sig.</div>'
                         f'<div style="font-size:10px;color:{mc}">{moy:+.1f}%</div>'
                         f'</td>')
        body += '</tr>'
    body += '</tbody>'

    note_html = f'<p style="font-size:11px;color:#888;margin-bottom:8px">{note}</p>' if note else ""
    return f'{note_html}<div class="table-wrap"><table>{hdr}{body}</table></div>'


def _section_synthese(bb_data_view, mode, bb_rsi, bb_adx, bb_vol, bb_dur):
    html = []
    nb   = len(bb_data_view)
    if nb < 5:
        return html

    rsi_lo = 50 if mode == "short" else 40

    if mode == "short":
        RSI_BB = [("RSI < 50",0,50),("RSI 50–60",50,60),("RSI 60–65",60,66),
                  ("RSI 66–70",66,71),("RSI 71–80",71,81),("RSI ≥ 80",80,999)]
    else:
        RSI_BB = [("RSI < 25",0,25),("RSI 25–32",25,33),("RSI 33–40",33,41),
                  ("RSI 41–48",41,49),("RSI ≥ 49",49,999)]

    ADX_BB = [("ADX < 12",0,12),("ADX 12–17",12,18),("ADX 18–22",18,23),
              ("ADX 23–27",23,28),("ADX ≥ 28",28,999)]
    VOL_BB = [("Vol < 0.70",0,0.70),("Vol 0.70–1.0",0.70,1.0),
              ("Vol 1.0–1.5",1.0,1.5),("Vol 1.5–2.5",1.5,2.5),("Vol ≥ 2.5",2.5,999)]
    DUR_BB = [("< 10j",0,10),("10–30j",10,30),("30–60j",30,60),
              ("60–90j",60,90),("≥ 90j",90,9999)]

    html.append('<h2>9 — Synthèse avancée, cyclicité &amp; zones à éviter</h2>')

    # ── 9a. Matrices croisées ─────────────────────────────────────────
    html.append('<h3>Matrices croisées — Win% SL A (cellules colorées)</h3>')
    html.append('<p style="font-size:12px;color:#666;margin-bottom:10px">'
                'Chaque cellule = win% · rendement moyen SL A · nombre de signaux. '
                'Gris = données insuffisantes (&lt; 2 signaux).</p>')

    html.append('<div class="two-col">')

    html.append('<div>')
    html.append('<h3 style="margin-top:0">RSI × ADX</h3>')
    html.append(_matrix_html(bb_data_view, RSI_BB, ADX_BB,
                             lambda b: b["rsi"], lambda b: b["adx"],
                             "RSI \\ ADX"))
    html.append('</div>')

    html.append('<div>')
    html.append('<h3 style="margin-top:0">RSI × Volume</h3>')
    html.append(_matrix_html(bb_data_view, RSI_BB, VOL_BB,
                             lambda b: b["rsi"], lambda b: b["vol"],
                             "RSI \\ Vol"))
    html.append('</div>')

    html.append('</div>')  # two-col

    html.append('<h3>ADX × Volume</h3>')
    html.append(_matrix_html(bb_data_view, ADX_BB, VOL_BB,
                             lambda b: b["adx"], lambda b: b["vol"],
                             "ADX \\ Vol",
                             note="Un ADX faible confirme l'absence de tendance forte — la BB "
                                  "a plus de chances d'agir comme résistance/support."))

    # ── 9b. Cyclicité détaillée ────────────────────────────────────────
    html.append('<h3>Cyclicité — évolution du win% selon la position dans le cycle</h3>')
    html.append('<p style="font-size:12px;color:#666;margin-bottom:8px">'
                'Analyse fine du moment optimal dans le cycle pour agir sur un signal BB. '
                'L\'ancienneté du cycle est connue en temps réel (jours depuis le début du cycle).</p>')

    DUR_DETAIL = [
        ("J1–J5",   0,   6), ("J6–J10",   6,  11), ("J11–J20", 11,  21),
        ("J21–J30", 21,  31), ("J31–J45", 31,  46), ("J46–J60", 46,  61),
        ("J61–J90", 61,  91), ("J91–J120", 91, 121), ("≥ J121", 121, 9999),
    ]

    cyc_rows = []
    for label, lo, hi in DUR_DETAIL:
        sub = [b for b in bb_data_view if lo <= b["jours_ecoules"] < hi]
        n   = len(sub)
        if n == 0:
            continue
        w   = round(sum(1 for b in sub if b["pct_sla"] > 0) / n * 100)
        moy = round(sum(b["pct_sla"] for b in sub) / n, 1)
        wb  = round(sum(1 for b in sub if b["pct_slb"] > 0) / n * 100)
        wc  = round(sum(1 for b in sub if b["pct_slc"] > 0) / n * 100)
        wd  = round(sum(1 for b in sub if b["pct_sld"] > 0) / n * 100)
        cyc_rows.append({
            "label": label, "n": n, "w": w, "moy": moy,
            "wb": wb, "wc": wc, "wd": wd,
            "moy_slb": round(sum(b["pct_slb"] for b in sub)/n,1),
            "moy_slc": round(sum(b["pct_slc"] for b in sub)/n,1),
            "moy_sld": round(sum(b["pct_sld"] for b in sub)/n,1),
        })

    if cyc_rows:
        # Bar chart win%
        bars_c = ""
        for r in cyc_rows:
            col      = "#0f6e56" if r["w"] >= 55 else ("#ba7517" if r["w"] >= 40 else "#c0392b")
            rend_col = "#0f6e56" if r["moy"] > 0 else "#a32d2d"
            bars_c += (f'<div class="bar-row">'
                       f'<div class="bar-lbl">{r["label"]}</div>'
                       f'<div class="bar-track"><div class="bar-fill" style="width:{max(r["w"],3)}%;background:{col}">{r["w"]}%</div></div>'
                       f'<div class="bar-meta">{r["n"]} sig.<br><span style="color:{rend_col};font-weight:600">{r["moy"]:+.1f}%</span></div>'
                       f'</div>')
        html.append(f'<div class="bar-sect"><div class="bar-sect-title">Win% SL A par phase du cycle (J = jours depuis début cycle)</div>{bars_c}</div>')

        # Table détaillée cyclicité
        hdr_c = (f'<thead><tr><th>Phase du cycle</th><th>N</th>'
                 f'<th>Win% <span class="sla">A</span></th>'
                 f'<th>Win% <span class="slb">B</span></th>'
                 f'<th>Win% <span class="slc">C</span></th>'
                 f'<th>Win% <span class="sld">D</span></th>'
                 f'<th>Moy. <span class="sla">SL A</span></th>'
                 f'<th>Moy. <span class="slb">SL B</span></th>'
                 f'<th>Moy. <span class="slc">SL C</span></th>'
                 f'<th>Moy. <span class="sld">SL D</span></th>'
                 f'</tr></thead>')
        body_c = '<tbody>'
        best_phase = max(cyc_rows, key=lambda r: r["w"])
        for r in cyc_rows:
            cls = ' class="best"' if r is best_phase and r["w"] >= 55 else ""
            body_c += (f'<tr{cls}><td><b>{r["label"]}</b></td><td>{r["n"]}</td>'
                       f'<td>{win_b(r["w"])}</td><td>{win_b(r["wb"])}</td>'
                       f'<td>{win_b(r["wc"])}</td><td>{win_b(r["wd"])}</td>'
                       f'<td>{pct_b(r["moy"])}</td><td>{pct_b(r["moy_slb"])}</td>'
                       f'<td>{pct_b(r["moy_slc"])}</td><td>{pct_b(r["moy_sld"])}</td></tr>')
        body_c += '</tbody>'
        html.append(f'<div class="table-wrap"><table>{hdr_c}{body_c}</table></div>')

    # Distribution des signaux selon l'ancienneté
    all_je = [b["jours_ecoules"] for b in bb_data_view]
    if all_je:
        max_je  = max(all_je)
        bk_size = max(max_je // 12, 5)
        n_bk    = max_je // bk_size + 1
        buckets = []
        for bi in range(n_bk):
            lo_b  = bi * bk_size
            hi_b  = (bi + 1) * bk_size
            count = sum(1 for je in all_je if lo_b <= je < hi_b)
            if count > 0 or lo_b <= max_je:
                buckets.append((f"J{lo_b}–{hi_b}", count))
        if buckets:
            max_c  = max(c for _, c in buckets) or 1
            d_bars = ""
            for lbl, c in buckets:
                h = max(round(c / max_c * 100), 1) if c > 0 else 0
                d_bars += (f'<div class="dist-bar-col">'
                           f'<div class="dist-bar-fill" style="height:{h}%;background:#378add;opacity:.7"></div>'
                           f'<div class="dist-bar-cnt">{c if c > 0 else ""}</div>'
                           f'<div class="dist-bar-lbl">{lbl}</div>'
                           f'</div>')
            html.append(f'<div class="dist-wrap">'
                        f'<div class="dist-title">Distribution des signaux BB selon l\'ancienneté du cycle (concentration = cycles récurrents)</div>'
                        f'<div class="dist-bars">{d_bars}</div>'
                        f'</div>')

    # ── 9c. Ce qui ne marche pas ──────────────────────────────────────
    html.append('<h3 style="color:#a32d2d;margin-top:1.8rem">Ce qui ne marche pas — zones à éviter</h3>')
    html.append('<p style="font-size:12px;color:#666;margin-bottom:8px">'
                'Toutes les conditions avec Win% SL A &lt; 40% et ≥ 3 signaux, '
                'classées par taux d\'échec décroissant.</p>')

    BAD = []

    # Par dimension simple
    for dim, rows in [("RSI", bb_rsi), ("ADX", bb_adx), ("Volume", bb_vol), ("Durée cycle", bb_dur)]:
        for r in rows:
            if r["n"] >= 3 and r["win_pct_a"] < 40:
                BAD.append({
                    "dim": dim, "label": r["label"], "n": r["n"],
                    "wa": r["win_pct_a"], "wb": r["win_pct_b"], "wc": r["win_pct_c"], "wd": r["win_pct_d"],
                    "ma": r["moy_sla"],   "mb": r["moy_slb"],   "mc": r["moy_slc"],   "md": r["moy_sld"],
                })

    # Par mois
    months_tmp = {}
    for b in bb_data_view:
        months_tmp.setdefault(b["date"].month, []).append(b)
    for m, items in months_tmp.items():
        n = len(items)
        if n >= 3:
            w = round(sum(1 for b in items if b["pct_sla"] > 0) / n * 100)
            if w < 40:
                BAD.append({
                    "dim": "Mois",
                    "label": MOIS_FR[m - 1], "n": n,
                    "wa": w,
                    "wb": round(sum(1 for b in items if b["pct_slb"] > 0) / n * 100),
                    "wc": round(sum(1 for b in items if b["pct_slc"] > 0) / n * 100),
                    "wd": round(sum(1 for b in items if b["pct_sld"] > 0) / n * 100),
                    "ma": round(sum(b["pct_sla"] for b in items) / n, 1),
                    "mb": round(sum(b["pct_slb"] for b in items) / n, 1),
                    "mc": round(sum(b["pct_slc"] for b in items) / n, 1),
                    "md": round(sum(b["pct_sld"] for b in items) / n, 1),
                })

    # Combinaisons croisées à risque
    CROSS = [
        (f"RSI ≥ {rsi_lo} + ADX ≥ 26",
         lambda b: b["rsi"] >= rsi_lo and b["adx"] >= 26),
        (f"RSI ≥ {rsi_lo} + ADX ≥ 22",
         lambda b: b["rsi"] >= rsi_lo and b["adx"] >= 22),
        (f"RSI ≥ {rsi_lo} + Vol ≥ 2.5",
         lambda b: b["rsi"] >= rsi_lo and b["vol"] >= 2.5),
        ("ADX ≥ 26 + Vol ≥ 2.0",
         lambda b: b["adx"] >= 26 and b["vol"] >= 2.0),
        ("ADX ≥ 26 + Vol ≥ 1.5",
         lambda b: b["adx"] >= 26 and b["vol"] >= 1.5),
        (f"RSI ≥ {rsi_lo} + Vol ≥ 1.5 + ADX ≥ 20",
         lambda b: b["rsi"] >= rsi_lo and b["vol"] >= 1.5 and b["adx"] >= 20),
        ("< 10j cycle + ADX ≥ 22",
         lambda b: b["jours_ecoules"] < 10 and b["adx"] >= 22),
        ("< 10j cycle + Vol ≥ 2.0",
         lambda b: b["jours_ecoules"] < 10 and b["vol"] >= 2.0),
        (f"< 10j cycle + RSI ≥ {rsi_lo}",
         lambda b: b["jours_ecoules"] < 10 and b["rsi"] >= rsi_lo),
    ]
    for label, filt in CROSS:
        sub = [b for b in bb_data_view if filt(b)]
        n   = len(sub)
        if n < 3:
            continue
        w = round(sum(1 for b in sub if b["pct_sla"] > 0) / n * 100)
        if w < 45:
            BAD.append({
                "dim": "Combo",
                "label": label, "n": n,
                "wa": w,
                "wb": round(sum(1 for b in sub if b["pct_slb"] > 0) / n * 100),
                "wc": round(sum(1 for b in sub if b["pct_slc"] > 0) / n * 100),
                "wd": round(sum(1 for b in sub if b["pct_sld"] > 0) / n * 100),
                "ma": round(sum(b["pct_sla"] for b in sub) / n, 1),
                "mb": round(sum(b["pct_slb"] for b in sub) / n, 1),
                "mc": round(sum(b["pct_slc"] for b in sub) / n, 1),
                "md": round(sum(b["pct_sld"] for b in sub) / n, 1),
            })

    BAD.sort(key=lambda x: x["wa"])  # Worst first

    if BAD:
        hdr_b = (f'<thead><tr><th>Type</th><th>Condition</th><th>N</th>'
                 f'<th>Win% <span class="sla">A</span></th>'
                 f'<th>Win% <span class="slb">B</span></th>'
                 f'<th>Win% <span class="slc">C</span></th>'
                 f'<th>Win% <span class="sld">D</span></th>'
                 f'<th>Moy. <span class="sla">SL A</span></th>'
                 f'<th>Moy. <span class="slb">SL B</span></th>'
                 f'<th>Moy. <span class="slc">SL C</span></th>'
                 f'<th>Moy. <span class="sld">SL D</span></th>'
                 f'</tr></thead>')
        body_b = '<tbody>'
        for c in BAD:
            body_b += (f'<tr class="worst">'
                       f'<td><span class="badge br">{c["dim"]}</span></td>'
                       f'<td><b>{c["label"]}</b></td><td>{c["n"]}</td>'
                       f'<td>{win_b(c["wa"])}</td><td>{win_b(c["wb"])}</td>'
                       f'<td>{win_b(c["wc"])}</td><td>{win_b(c["wd"])}</td>'
                       f'<td>{pct_b(c["ma"])}</td><td>{pct_b(c["mb"])}</td>'
                       f'<td>{pct_b(c["mc"])}</td><td>{pct_b(c["md"])}</td>'
                       f'</tr>')
        body_b += '</tbody>'
        html.append(f'<div class="table-wrap"><table>{hdr_b}{body_b}</table></div>')

        # Bar chart des pires conditions
        worst_bars = ""
        for c in BAD[:10]:
            w   = c["wa"]
            lbl = c["label"] if len(c["label"]) <= 38 else c["label"][:35] + "…"
            worst_bars += (f'<div class="bar-row">'
                           f'<div class="bar-lbl">{lbl}</div>'
                           f'<div class="bar-track"><div class="bar-fill" style="width:{max(w,3)}%;background:#c0392b">{w}%</div></div>'
                           f'<div class="bar-meta">{c["n"]} sig.<br><span style="color:#a32d2d;font-weight:600">{c["ma"]:+.1f}%</span></div>'
                           f'</div>')
        html.append(f'<div class="bar-sect"><div class="bar-sect-title">Pires conditions identifiées — Win% SL A (classées par taux d\'échec décroissant)</div>{worst_bars}</div>')
    else:
        html.append('<p style="color:#888;font-size:12px;padding:8px;background:#fff;border-radius:8px;border:0.5px solid #e0ddd6">'
                    'Aucune condition clairement sous-performante identifiée (toutes les zones ≥ 40% win ou données insuffisantes).</p>')

    return html


# ─── Génération d'un panneau complet (BB ou Séquentiel) ──────────────────────

def _panel_sections(bb_data_view, mode, sl_cumuls, best_sl_i, rsi_bb, adx_bb, vol_bb, dur_bb, is_seq=False):
    """
    Génère les sections 1–8 pour un jeu de données bb (toutes touches ou séquentiel).
    Retourne une liste de chaînes HTML.
    """
    html = []
    nb   = len(bb_data_view)

    if nb == 0:
        html.append('<p style="color:#888;padding:16px">Aucun signal pour cette vue.</p>')
        return html

    # Scorecards + profil moyen
    html.append(sl_scorecard_html(bb_data_view))
    avg_rsi = round(sum(b["rsi"] for b in bb_data_view) / nb, 1)
    avg_adx = round(sum(b["adx"] for b in bb_data_view) / nb, 1)
    avg_vol = round(sum(b["vol"] for b in bb_data_view) / nb, 2)
    avg_je  = round(sum(b["jours_ecoules"] for b in bb_data_view) / nb)
    html.append(
        f'<div class="kpis" style="margin-bottom:1rem">'
        f'<div class="kpi"><div class="kl">Signaux</div><div class="kv">{nb}</div></div>'
        f'<div class="kpi"><div class="kl">RSI moyen au signal</div><div class="kv">{avg_rsi}</div></div>'
        f'<div class="kpi"><div class="kl">ADX moyen au signal</div><div class="kv">{avg_adx}</div></div>'
        f'<div class="kpi"><div class="kl">Volume moyen au signal</div><div class="kv">{avg_vol}×</div></div>'
        f'<div class="kpi"><div class="kl">Ancienneté moy. du cycle</div><div class="kv">{avg_je}j</div></div>'
        f'</div>'
    )
    html.append(dist_rendement_html(bb_data_view))

    bb_rsi  = bb_stat_rows(bb_data_view, lambda b: b["rsi"], rsi_bb)
    bb_adx  = bb_stat_rows(bb_data_view, lambda b: b["adx"], adx_bb)
    bb_vol  = bb_stat_rows(bb_data_view, lambda b: b["vol"], vol_bb)
    bb_dur  = bb_stat_rows(bb_data_view, lambda b: b["jours_ecoules"], dur_bb)

    # ── 1 — Vue d'ensemble ──────────────────────────────────────────
    html.append('<h2 class="bb-title">1 — Signaux Bollinger — Vue d\'ensemble</h2>')

    rsi_lo = 50 if mode == "short" else 40
    COMBOS_OV = [
        ("Total",                lambda b: True),
        (f"RSI < {rsi_lo} au signal BB",
         (lambda b: b["rsi"] < 50) if mode=="short" else (lambda b: b["rsi"] < 40)),
        (f"RSI ≥ {rsi_lo} au signal BB",
         (lambda b: b["rsi"] >= 50) if mode=="short" else (lambda b: b["rsi"] >= 40)),
        ("ADX < 20 au signal BB",  lambda b: b["adx"] < 20),
        ("ADX 20–26 au signal BB", lambda b: 20 <= b["adx"] < 26),
        ("ADX ≥ 26 au signal BB",  lambda b: b["adx"] >= 26),
        ("ADX ≤ 20 + Vol < 1.5",   lambda b: b["adx"] <= 20 and b["vol"] < 1.5),
        (f"ADX ≤ 22 + RSI < {rsi_lo}",
         (lambda b: b["adx"] <= 22 and b["rsi"] < 50) if mode=="short"
         else (lambda b: b["adx"] <= 22 and b["rsi"] < 40)),
    ]

    hdr_ov = (f'<thead><tr><th>Critère / Filtre</th><th>Signaux</th>'
              f'<th>Win% <span class="sla">A</span></th>'
              f'<th>Win% <span class="slb">B</span></th>'
              f'<th>Win% <span class="slc">C</span></th>'
              f'<th>Win% <span class="sld">D</span></th>'
              + _sl_headers() + '</tr></thead>')
    body_ov  = "<tbody>"
    ov_bar_r = []
    for label, filt in COMBOS_OV:
        sub = [b for b in bb_data_view if filt(b)]
        n   = len(sub)
        if n < 2 and label != "Total":
            continue
        if n == 0:
            continue
        wa   = round(sum(1 for b in sub if b["pct_sla"] > 0) / n * 100)
        wb   = round(sum(1 for b in sub if b["pct_slb"] > 0) / n * 100)
        wc   = round(sum(1 for b in sub if b["pct_slc"] > 0) / n * 100)
        wd   = round(sum(1 for b in sub if b["pct_sld"] > 0) / n * 100)
        msla = round(sum(b["pct_sla"] for b in sub)/n,1)
        mslb = round(sum(b["pct_slb"] for b in sub)/n,1)
        mslc = round(sum(b["pct_slc"] for b in sub)/n,1)
        msld = round(sum(b["pct_sld"] for b in sub)/n,1)
        bold = ' style="font-weight:600"' if label == "Total" else ""
        body_ov += (f'<tr{bold}><td><b>{label}</b></td><td>{n}</td>'
                    f'<td>{win_b(wa)}</td><td>{win_b(wb)}</td>'
                    f'<td>{win_b(wc)}</td><td>{win_b(wd)}</td>'
                    f'<td>{pct_b(msla)}</td><td>{pct_b(mslb)}</td>'
                    f'<td>{pct_b(mslc)}</td><td>{pct_b(msld)}</td></tr>')
        ov_bar_r.append({"label": label, "n": n, "win_pct_a": wa, "moy_sla": msla})
    html.append(f'<div class="table-wrap"><table>{hdr_ov}{body_ov}</tbody></table></div>')
    html.append(bar_chart_win(ov_bar_r, "Win% SL A selon le filtre appliqué"))

    # ── 2 — RSI ──────────────────────────────────────────────────────
    html.append('<h2>2 — RSI au moment du signal BB</h2>')
    html.append(auto_obs_bb(bb_rsi))
    html.append(bb_table(bb_rsi))
    html.append(bar_chart_multi_sl(bb_rsi, "Win% et rendement moyen par tranche RSI — toutes stratégies"))

    # ── 3 — ADX ──────────────────────────────────────────────────────
    html.append('<h2>3 — ADX au moment du signal BB</h2>')
    html.append(auto_obs_bb(bb_adx))
    html.append(bb_table(bb_adx))
    html.append(bar_chart_multi_sl(bb_adx, "Win% et rendement moyen par tranche ADX — toutes stratégies"))

    # ── 4 — Volume ───────────────────────────────────────────────────
    html.append('<h2>4 — Volume au moment du signal BB</h2>')
    html.append(auto_obs_bb(bb_vol))
    html.append(bb_table(bb_vol))
    html.append(bar_chart_multi_sl(bb_vol, "Win% et rendement moyen par tranche Volume — toutes stratégies"))

    # ── 5 — Saisonnalité ─────────────────────────────────────────────
    html.append('<h2>5 — Saisonnalité des signaux BB</h2>')
    months_bb = {}
    for b in bb_data_view:
        months_bb.setdefault(b["date"].month, []).append(b)
    html.append('<p style="font-size:12px;color:#666;margin-bottom:10px">Heatmap : couleur = taux de réussite SL A · chiffre bas = rendement moyen SL A</p>')
    html.append(mois_heatmap(months_bb))
    html.append(mois_table(months_bb))

    # ── 6 — Durée + Filtres ──────────────────────────────────────────
    html.append('<h2>6 — Contexte du cycle hôte et filtres top-down</h2>')
    html.append('<div class="two-col">')
    html.append('<div>')
    html.append('<h3>Ancienneté du cycle au moment du toucher BB</h3>')
    html.append('<p style="font-size:11px;color:#888;margin-bottom:8px">Jours écoulés depuis le début du cycle — information disponible en temps réel.</p>')
    html.append(auto_obs_bb(bb_dur))
    html.append(bb_table(bb_dur))
    html.append(bar_chart_win(bb_dur, "Win% SL A selon l'ancienneté du cycle"))
    html.append('</div>')
    html.append('<div>')
    html.append('<h3>Filtres top-down au signal BB</h3>')
    html.append(td_table([
        ("Pays ✓ + Secteur ✓", lambda b: b["ok_pays"] and b["ok_secteur"]),
        ("Pays ✓ seul",         lambda b: b["ok_pays"] and not b["ok_secteur"]),
        ("Secteur ✓ seul",      lambda b: not b["ok_pays"] and b["ok_secteur"]),
        ("Aucun filtre",        lambda b: not b["ok_pays"] and not b["ok_secteur"]),
    ], bb_data_view))
    html.append('</div>')
    html.append('</div>')  # two-col

    # ── 7 — Combinaisons ─────────────────────────────────────────────
    html.append('<h2>7 — Combinaisons optimales BB</h2>')
    html.append('<p style="font-size:12px;color:#666;margin-bottom:10px">Classement par Win% SL A décroissant. '
                '<span class="rank1">Or</span> ≥ 60% · '
                '<span class="rank2">Argent</span> 50–59% · '
                '<span class="rank3">Bronze</span> 40–49%</p>')

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
        (f"≥ 30j depuis début cycle + RSI < {rsi_lo}",
         lambda b: b["jours_ecoules"] >= 30 and b["rsi"] < rsi_lo),
        ("≥ 30j depuis début cycle + ADX < 22",
         lambda b: b["jours_ecoules"] >= 30 and b["adx"] < 22),
        (f"≥ 30j depuis début cycle + RSI < {rsi_lo} + ADX < 22",
         lambda b: b["jours_ecoules"] >= 30 and b["rsi"] < rsi_lo and b["adx"] < 22),
    ]

    combo_rows = []
    for label, filt in COMBOS:
        sub = [b for b in bb_data_view if filt(b)]
        n   = len(sub)
        if n < 2:
            continue
        wa   = round(sum(1 for b in sub if b["pct_sla"] > 0) / n * 100)
        wb   = round(sum(1 for b in sub if b["pct_slb"] > 0) / n * 100)
        wc   = round(sum(1 for b in sub if b["pct_slc"] > 0) / n * 100)
        wd   = round(sum(1 for b in sub if b["pct_sld"] > 0) / n * 100)
        msla = round(sum(b["pct_sla"] for b in sub)/n,1)
        mslb = round(sum(b["pct_slb"] for b in sub)/n,1)
        mslc = round(sum(b["pct_slc"] for b in sub)/n,1)
        msld = round(sum(b["pct_sld"] for b in sub)/n,1)
        combo_rows.append((label, n, wa, wb, wc, wd, msla, mslb, mslc, msld))

    combo_rows.sort(key=lambda x: x[2], reverse=True)

    hdr_c = (f'<thead><tr><th>#</th><th>Combinaison</th><th>N</th>'
             f'<th>Win% <span class="sla">A</span></th>'
             f'<th>Win% <span class="slb">B</span></th>'
             f'<th>Win% <span class="slc">C</span></th>'
             f'<th>Win% <span class="sld">D</span></th>'
             + _sl_headers() + '</tr></thead>')
    body_c = "<tbody>"
    for ri, (label, n, wa, wb, wc, wd, msla, mslb, mslc, msld) in enumerate(combo_rows):
        tr_cls = (' class="best"' if wa >= 60 else ' class="worst"' if wa < 35 else '')
        if ri == 0:
            rbadge = '<span class="rank1">1er</span>'
        elif ri == 1:
            rbadge = '<span class="rank2">2e</span>'
        elif ri == 2:
            rbadge = '<span class="rank3">3e</span>'
        else:
            rbadge = f'<span style="font-size:11px;color:#ccc">{ri+1}</span>'
        body_c += (f'<tr{tr_cls}><td style="text-align:center">{rbadge}</td>'
                   f'<td><b>{label}</b></td><td>{n}</td>'
                   f'<td>{win_b(wa)}</td><td>{win_b(wb)}</td>'
                   f'<td>{win_b(wc)}</td><td>{win_b(wd)}</td>'
                   f'<td>{pct_b(msla)}</td><td>{pct_b(mslb)}</td>'
                   f'<td>{pct_b(mslc)}</td><td>{pct_b(msld)}</td></tr>')
    html.append(f'<div class="table-wrap"><table>{hdr_c}{body_c}</tbody></table></div>')

    if combo_rows:
        top_bars = ""
        for ri, (label, n, wa, wb, wc, wd, msla, mslb, mslc, msld) in enumerate(combo_rows[:8]):
            col      = "#0f6e56" if wa >= 55 else ("#ba7517" if wa >= 40 else "#c0392b")
            rend_col = "#0f6e56" if msla > 0 else "#a32d2d"
            lbl_s    = label if len(label) <= 38 else label[:35] + "…"
            top_bars += (f'<div class="bar-row">'
                         f'<div class="bar-lbl">{lbl_s}</div>'
                         f'<div class="bar-track"><div class="bar-fill" style="width:{max(wa,3)}%;background:{col}">{wa}%</div></div>'
                         f'<div class="bar-meta">{n} sig.<br><span style="color:{rend_col};font-weight:600">{msla:+.1f}%</span></div>'
                         f'</div>')
        html.append(f'<div class="bar-sect"><div class="bar-sect-title">Top combinaisons — Win% SL A (rendement moy. SL A)</div>{top_bars}</div>')

    # ── 8 — Checklist ────────────────────────────────────────────────
    html.append('<h2>8 — Checklist d\'entrée optimale (BB)</h2>')

    def best_f(rows):
        valid = [r for r in rows if r["n"] >= 3]
        return max(valid, key=lambda r: r["win_pct_a"]) if valid else None

    b_rsi = best_f(bb_rsi)
    b_adx = best_f(bb_adx)
    b_vol = best_f(bb_vol)
    b_dur = best_f(bb_dur)

    months_bb2 = {}
    for b in bb_data_view:
        months_bb2.setdefault(b["date"].month, []).append(b)
    best_m   = max(months_bb2.items(),
                   key=lambda kv: sum(1 for b in kv[1] if b["pct_sla"] > 0)/len(kv[1])) if months_bb2 else None
    worst_ms = [MOIS_FR[m-1] for m, bs in months_bb2.items()
                if len(bs) >= 2 and sum(1 for b in bs if b["pct_sla"] > 0)/len(bs) < 0.35]

    adx26      = [b for b in bb_data_view if b["adx"] >= 26]
    adx26_warn = (len(adx26) >= 3
                  and round(sum(1 for b in adx26 if b["pct_sla"] > 0)/len(adx26)*100) <= 40)

    checklist = [
        ("Stratégie SL conseillée", "Obligatoire", "#185fa5",
         f'{SL_CFGS[best_sl_i]["nom"]} ({SL_CFGS[best_sl_i]["desc"]}) — meilleur cumulé cycles ({sl_cumuls[best_sl_i]:+.1f}%)'),
    ]
    if b_rsi:
        checklist.append(("RSI au signal BB", "Recommandé", "#3b6d11",
            f'{b_rsi["label"]} — {b_rsi["win_pct_a"]}% win SL A · moy {b_rsi["moy_sla"]:+.1f}% · '
            f'SL B {b_rsi["moy_slb"]:+.1f}% · SL C {b_rsi["moy_slc"]:+.1f}%'))
    if b_adx:
        checklist.append(("ADX au signal BB", "Recommandé", "#3b6d11",
            f'{b_adx["label"]} — {b_adx["win_pct_a"]}% win SL A · moy {b_adx["moy_sla"]:+.1f}%'))
    if b_vol and b_vol["win_pct_a"] >= 55:
        checklist.append(("Volume au signal BB", "Optionnel", "#888",
            f'{b_vol["label"]} — {b_vol["win_pct_a"]}% win SL A · moy {b_vol["moy_sla"]:+.1f}%'))
    if b_dur and b_dur["win_pct_a"] >= 60:
        checklist.append(("Ancienneté du cycle", "Optionnel", "#888",
            f'{b_dur["label"]} — {b_dur["win_pct_a"]}% win : phase optimale pour entrer sur BB'))
    if best_m:
        wr_m   = round(sum(1 for b in best_m[1] if b["pct_sla"] > 0)/len(best_m[1])*100)
        detail = f"Meilleur mois : {MOIS_FR[best_m[0]-1]} ({wr_m}%)"
        if worst_ms:
            detail += f" — mois à éviter : {', '.join(worst_ms)}"
        checklist.append(("Saisonnalité", "Optionnel", "#888", detail))
    if adx26_warn:
        wr26 = round(sum(1 for b in adx26 if b["pct_sla"] > 0)/len(adx26)*100)
        checklist.append(("ADX ≥ 26 au signal BB", "Éviter", "#a32d2d",
            f'{len(adx26)} signaux concernés, {wr26}% win SL A — '
            f'tendance forte = BB peu fiable comme signal de retournement'))
    if combo_rows:
        tl, tn, twa = combo_rows[0][0], combo_rows[0][1], combo_rows[0][2]
        if twa >= 55:
            checklist.append(("Meilleure combinaison", "Recommandé", "#3b6d11",
                f'« {tl} » — {twa}% win SL A sur {tn} signaux'))

    html.append('<div class="checklist">')
    for critere, obligation, color, detail in checklist:
        icon = "●" if obligation == "Obligatoire" else ("▲" if obligation == "Recommandé" else ("◆" if obligation == "Optionnel" else "✕"))
        html.append(
            f'<div class="check-row">'
            f'<div style="font-weight:600">{critere}</div>'
            f'<div style="font-weight:700;color:{color}">{icon} {obligation}</div>'
            f'<div style="color:#444">{detail}</div>'
            f'</div>'
        )
    html.append('</div>')

    # ── 9 — Synthèse avancée ─────────────────────────────────────────
    html.extend(_section_synthese(bb_data_view, mode, rsi_bb, adx_bb, vol_bb, dur_bb))

    return html


# ─── Génération HTML principale ───────────────────────────────────────────────

def generer_analyse(ticker, cycle_data, bb_data, bb_seq_data, mode,
                    country_t, sector_t, period, config):
    if not cycle_data:
        return f"<p>Aucune donnée pour {ticker}.</p>"

    mode_label = "SHORT" if mode == "short" else "LONG"
    mode_color = "#a32d2d" if mode == "short" else "#0f6e56"
    mode_bg    = "#fcebeb" if mode == "short" else "#eaf3de"

    nb_cycles = len(cycle_data)
    nb_bb     = len(bb_data)
    nb_seq    = len(bb_seq_data)

    sl_cumuls = [round(sum(c[f"pct_sl{k}"] for c in cycle_data), 1) for k in "abcd"]
    best_sl_i = max(range(4), key=lambda i: sl_cumuls[i])

    if mode == "short":
        RSI_BB = [("RSI < 50",0,50),("RSI 50–60",50,60),("RSI 60–65",60,66),
                  ("RSI 66–70",66,71),("RSI 71–80",71,81),("RSI ≥ 80",80,999)]
    else:
        RSI_BB = [("RSI < 25",0,25),("RSI 25–32",25,33),("RSI 33–40",33,41),
                  ("RSI 41–48",41,49),("RSI ≥ 49",49,999)]

    ADX_BB = [("ADX < 12",0,12),("ADX 12–17",12,18),("ADX 18–22",18,23),
              ("ADX 23–27",23,28),("ADX ≥ 28",28,999)]
    VOL_BB = [("Vol < 0.70",0,0.70),("Vol 0.70–1.0",0.70,1.0),
              ("Vol 1.0–1.5",1.0,1.5),("Vol 1.5–2.5",1.5,2.5),("Vol ≥ 2.5",2.5,999)]
    DUR_BB = [("< 10j depuis début cycle",0,10),("10–30j",10,30),
              ("30–60j",30,60),("60–90j",60,90),("≥ 90j",90,9999)]

    cfg_bol  = config.get("bollinger", {})
    footer   = (f'<p class="footer">BB Analyser · {ticker} · {period} · '
                f'{datetime.now().strftime("%d/%m/%Y %H:%M")} · '
                f'Données Yahoo Finance · RSI/ADX Wilder · '
                f'BB {cfg_bol.get("periode",20)} périodes ×{cfg_bol.get("ecarts",2)} '
                f'± {cfg_bol.get("tolerance_pct",1.0)}% tolérance · '
                f'Les résultats passés ne préjugent pas des résultats futurs.</p>')

    # ── KPIs globaux (communs aux deux vues) ──
    kpis_communs = ['<div class="kpis">']
    kpis_communs.append(f'<div class="kpi"><div class="kl">Cycles {mode_label}</div><div class="kv">{nb_cycles}</div></div>')
    for i, sl in enumerate(SL_CFGS):
        k       = sl["key"][-1]
        wr_bb   = round(sum(1 for b in bb_data if b[f"pct_sl{k}"] > 0) / nb_bb * 100) if nb_bb else 0
        cum_bb  = round(sum(b[f"pct_sl{k}"] for b in bb_data), 1) if nb_bb else 0
        wr_seq  = round(sum(1 for b in bb_seq_data if b[f"pct_sl{k}"] > 0) / nb_seq * 100) if nb_seq else 0
        cum_seq = round(sum(b[f"pct_sl{k}"] for b in bb_seq_data), 1) if nb_seq else 0
        col_bb  = "green" if wr_bb >= 50 else "red"
        col_seq = "green" if wr_seq >= 50 else "red"
        kpis_communs.append(
            f'<div class="kpi">'
            f'<div class="kl">{sl["nom"]} · BB ({nb_bb} sig.)</div>'
            f'<div class="kv {col_bb}">{wr_bb}%</div>'
            f'<div style="font-size:11px;color:#888;margin-top:2px">cumulé {cum_bb:+.1f}%</div>'
            f'</div>'
            f'<div class="kpi">'
            f'<div class="kl">{sl["nom"]} · Séq. ({nb_seq} sig.)</div>'
            f'<div class="kv {col_seq}">{wr_seq}%</div>'
            f'<div style="font-size:11px;color:#888;margin-top:2px">cumulé {cum_seq:+.1f}%</div>'
            f'</div>'
        )
    kpis_communs.append('</div>')

    # ── Générer les deux panneaux ──
    panel_bb  = _panel_sections(bb_data,      mode, sl_cumuls, best_sl_i,
                                RSI_BB, ADX_BB, VOL_BB, DUR_BB, is_seq=False)
    panel_seq = _panel_sections(bb_seq_data,  mode, sl_cumuls, best_sl_i,
                                RSI_BB, ADX_BB, VOL_BB, DUR_BB, is_seq=True)

    note_seq = (f'<p class="note" style="background:#f5f0fb;border-left-color:#7b3fa0">'
                f'Vue <b>BB Séquentiel</b> : entrée sur la 1ère touche BB du cycle, puis on attend '
                f'la sortie SL A avant de ré-entrer sur la prochaine touche. '
                f'Tous les SLs sont simulés depuis le même point d\'entrée. '
                f'{nb_seq} trades sur {nb_bb} touches totales ({round(nb_seq/nb_bb*100) if nb_bb else 0}% des signaux exploités).</p>')

    html_parts = [f"""<!DOCTYPE html>
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
"""]

    # Toggle
    html_parts.append(
        f'<div class="view-toggle">'
        f'<button class="vt-btn active" id="btn-bb" onclick="setView(\'bb\')">'
        f'Rendement BB <span class="view-badge vb-bb">{nb_bb} signaux</span></button>'
        f'<button class="vt-btn" id="btn-seq" onclick="setView(\'seq\')">'
        f'BB Séquentiel <span class="view-badge vb-seq">{nb_seq} signaux</span></button>'
        f'</div>'
    )

    # Commun
    html_parts.extend(kpis_communs)

    # Vue BB
    html_parts.append('<div id="view-bb">')
    html_parts.append(f'<p class="note">Ce rapport analyse <b>{nb_cycles} cycles {mode_label.lower()}s</b> et <b>{nb_bb} signaux BB intra-cycle</b> (chaque touche BB est analysée indépendamment). Tolérance BB : {cfg_bol.get("tolerance_pct",1.0)}%.</p>')
    html_parts.extend(panel_bb)
    html_parts.append(footer)
    html_parts.append('</div>')

    # Vue Séquentielle
    html_parts.append('<div id="view-seq" style="display:none">')
    html_parts.append(note_seq)
    html_parts.extend(panel_seq)
    html_parts.append(footer)
    html_parts.append('</div>')

    html_parts.append(TOGGLE_JS)
    html_parts.append('</body></html>')
    return "\n".join(html_parts)


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

        cycles = detecter_cycles(df, config, args.mode)
        print(f"  → {len(cycles)} cycle(s) détecté(s)")

        cycle_data, bb_data, bb_seq_data = construire_donnees(
            cycles, args.mode, config, df_country, df_sector
        )
        print(f"  → {len(bb_data)} signal(s) BB · {len(bb_seq_data)} signal(s) séquentiels")

        html = generer_analyse(
            ticker, cycle_data, bb_data, bb_seq_data, args.mode,
            args.country, args.sector, args.period, config
        )

        output = args.output or f"BB_Stats__{ticker.replace('-', '')}.html"
        Path(output).write_text(html, encoding="utf-8")
        print(f"  → Rapport généré : {output}")

        import webbrowser
        webbrowser.open(f"file:///{Path(output).resolve().as_posix()}")


if __name__ == "__main__":
    main()
