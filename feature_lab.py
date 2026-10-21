# -*- coding: utf-8 -*-
"""
跨市场特征诊断
==============
在同一批 5 折样本外数据上, 逐层加入亚盘/欧赔特征, 看是否真有增量。

M0: p_move                                   (现状)
M1: + 亚盘水位差变化 wdiff_move
M2: + 盘口移动 hcp_move
M3: + 欧亚一致性 agree
M4: + 分歧变化 pstd_chg / 返还率变化 rebate_chg / 报价公司数 n_euro

用法:
  py feature_lab.py
  py feature_lab.py --book bet365 --epochs 600
"""
import argparse
import json
import os
import statistics
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from asian_handicap_model_v3 import (  # noqa: E402
    fit_logreg, sigmoid, standardize_fit, transform,
)
from verify_water_roi import payout, settle_units  # noqa: E402

DATA = os.path.join(BASE, "titan_data")
E = json.load(open(os.path.join(DATA, "euro.json"), encoding="utf-8"))
L = json.load(open(os.path.join(DATA, "listings.json"), encoding="utf-8"))
W = json.load(open(os.path.join(DATA, "water.json"), encoding="utf-8"))

MODELS = [
    ("M0", ["p_move"]),
    ("M1", ["p_move", "wdiff_move"]),
    ("M2", ["p_move", "wdiff_move", "hcp_move"]),
    ("M3", ["p_move", "wdiff_move", "hcp_move", "agree"]),
    ("M4", ["p_move", "wdiff_move", "hcp_move", "agree",
            "pstd_chg", "rebate_chg", "n_euro"]),
]


def build_rows(book):
    rows = []
    miss = {"water": 0, "open": 0, "score": 0}
    for sid, e in E.items():
        if e.get("p_move") is None:
            continue
        w = W.get(sid, {}).get(book)
        l = L.get(sid)
        if not w or not l:
            miss["water"] += 1
            continue
        try:
            hg, ag = [int(x) for x in l["score"].split("-")]
        except Exception:
            miss["score"] += 1
            continue
        vals = [w.get("hcp_open"), w.get("hcp_close"),
                w.get("wo_h_open"), w.get("wo_a_open"),
                w.get("wo_h_close"), w.get("wo_a_close")]
        if any(v is None for v in vals):
            miss["open"] += 1
            continue
        ho, hc, who, wao, whc, wac = vals
        r = {
            "sid": sid, "date": l["date"], "league": l.get("league") or "?",
            "p_move": e["p_move"], "h": hc, "hg": hg, "ag": ag,
            "wo_h": whc, "wo_a": wac,
            "hcp_move": hc - ho,
            "wdiff_move": (whc - wac) - (who - wao),
            "pstd_chg": (e.get("p_std_close") or 0.0) - (e.get("p_std_open") or 0.0),
            "rebate_chg": (e.get("rebate_close") or 0.0) - (e.get("rebate_open") or 0.0),
            "n_euro": float(e.get("n_euro") or 0),
        }
        r["agree"] = r["p_move"] * (-r["wdiff_move"])
        r["y"] = 1 if ((hg - ag) - hc) > 0 else 0
        rows.append(r)
    rows.sort(key=lambda r: r["date"])
    print("构建 %d 场 (剔除: 无水位 %d, 无初盘 %d, 无比分 %d)"
          % (len(rows), miss["water"], miss["open"], miss["score"]))
    return rows


def oof(rows, feats, k=5, epochs=600, l2=1.5):
    dates = sorted(set(r["date"] for r in rows))
    buckets = [[] for _ in range(k)]
    for i, d in enumerate(dates):
        buckets[i * k // len(dates)].append(d)
    ps = [None] * len(rows)
    last = None
    for b in range(k):
        td = set(buckets[b])
        tr = [r for r in rows if r["date"] not in td]
        te = [i for i, r in enumerate(rows) if r["date"] in td]
        X = [[r[f] for f in feats] for r in tr]
        mu, sd = standardize_fit(X)
        w, bb = fit_logreg(transform(X, mu, sd), [r["y"] for r in tr],
                           l2=l2, lr=0.1, epochs=epochs)
        for i in te:
            z = bb + sum(w[j] * (rows[i][f] - mu[j]) / sd[j]
                         for j, f in enumerate(feats))
            ps[i] = sigmoid(z)
        last = (w, mu, sd)
    return ps, last


def evaluate(rows, ps, label):
    n = len(ps)
    brier = sum((p - r["y"]) ** 2 for p, r in zip(ps, rows)) / n

    def band(thr):
        arr = [(p, r) for p, r in zip(ps, rows) if abs(p - 0.5) >= thr]
        if not arr:
            return (0, 0.0, 0.0)
        wins = profit = 0
        for p, r in arr:
            side = 1 if p >= 0.5 else -1
            odds = r["wo_h"] if side == 1 else r["wo_a"]
            u = settle_units(r["h"], r["hg"], r["ag"])
            u = u if side == 1 else -u
            profit += payout(u, odds) - 1.0
            if u > 0:
                wins += 1
        return (len(arr), 100.0 * wins / len(arr), 100.0 * profit / len(arr))

    a0 = band(0.0)
    a8 = band(0.08)
    a10 = band(0.10)
    print("  %-4s Brier %.5f | 全下 n=%-4d %5.1f%% ROI %+6.2f%% | "
          "sig>=.08 n=%-4d %5.1f%% ROI %+6.2f%% | "
          "sig>=.10 n=%-3d %5.1f%% ROI %+6.2f%%"
          % (label, brier, a0[0], a0[1], a0[2], a8[0], a8[1], a8[2],
             a10[0], a10[1], a10[2]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="crown")
    ap.add_argument("--epochs", type=int, default=600)
    a = ap.parse_args()

    rows = build_rows(a.book)
    rows = [r for r in rows if abs((r["hg"] - r["ag"]) - r["h"]) > 1e-9]
    print("剔除走水后 %d 场  %s ~ %s" % (len(rows), rows[0]["date"], rows[-1]["date"]))
    print("水位初盘可用率 100%%(已过滤), 特征非零占比: "
          "wdiff_move %.1f%%  hcp_move %.1f%%  pstd_chg %.1f%%"
          % (100.0 * sum(1 for r in rows if abs(r["wdiff_move"]) > 1e-9) / len(rows),
             100.0 * sum(1 for r in rows if abs(r["hcp_move"]) > 1e-9) / len(rows),
             100.0 * sum(1 for r in rows if abs(r["pstd_chg"]) > 1e-9) / len(rows)))

    print("\n单特征与 y 的相关性:")
    for f in ("p_move", "wdiff_move", "hcp_move", "agree", "pstd_chg",
              "rebate_chg", "n_euro"):
        xs = [r[f] for r in rows]
        m = statistics.mean(xs)
        s = statistics.pstdev(xs) or 1.0
        ys = [r["y"] for r in rows]
        my = statistics.mean(ys)
        corr = sum((x - m) * (y - my) for x, y in zip(xs, ys)) / len(xs) / (s * (statistics.pstdev(ys) or 1.0))
        print("  %-11s %+.4f" % (f, corr))

    print("\n5 折样本外对比:")
    results = {}
    for name, feats in MODELS:
        ps, last = oof(rows, feats, epochs=a.epochs)
        evaluate(rows, ps, name)
        results[name] = (ps, feats, last)

    print("\nM4 系数 (标准化后, 正=提高主队赢盘概率):")
    ps, feats, (w, mu, sd) = results["M4"]
    for f, wi in zip(feats, w):
        print("  %-11s %+.4f" % (f, wi))

    base = results["M0"][0]
    others = {k: v[0] for k, v in results.items() if k != "M0"}
    print("\n与 M0 的预测相关性 / 方向分歧率:")
    for name, ps2 in others.items():
        m1, m2 = statistics.mean(base), statistics.mean(ps2)
        cov = sum((x - m1) * (y - m2) for x, y in zip(base, ps2)) / len(base)
        corr = cov / ((statistics.pstdev(base) or 1) * (statistics.pstdev(ps2) or 1))
        diff = sum(1 for x, y in zip(base, ps2) if (x >= 0.5) != (y >= 0.5)) / len(base)
        print("  %-4s corr %.4f  方向分歧 %.1f%%" % (name, corr, 100 * diff))


if __name__ == "__main__":
    main()
