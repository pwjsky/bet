# -*- coding: utf-8 -*-
"""
大小球模型
==========
预测全场大球是否赢盘。数据源全部赛前可得:
  赛果/联赛   titan_data/listings.json
  大小球盘口  titan_data/ou.json      皇冠优先, 365 补充 (全场 [21:27]: 开盘3 + 即时3)
  欧赔        titan_data/euro.json    用 1x2 反推 Poisson 预期总进球
  亚盘        titan_data/water.json   终盘让球

特征:
  p_move      去水大球概率变动 (封盘 - 开盘)
  line_move   大小球盘口变动
  line        封盘盘口
  lam_dev     欧赔隐含总进球 - 大小球盘口 (跨市场分歧)

结论(样本 20260709~20261016, 20997 场):
  单特征 p_move 52.0% 命中 / ROI -4.67%, 加 line_move+line 为 -3.74%。
  大球均水 0.888, 盈亏线 52.9%, 模型命中率始终差 1~3 个点。
  唯一接近正期望的是 "line<=2.25 且 lam_dev>=0.10":
    541 场 / 大球率 54.7% / ROI +3.74%, 但按月仅 3 正 1 负, 不显著, 不作策略。

用法:
  py ou_model.py
  py ou_model.py --feats p_move,line_move,line
"""
import argparse
import collections
import json
import math
import os
import statistics
import sys

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from verify_water_roi import payout  # noqa: E402

DATA = os.path.join(BASE, "titan_data")


def load(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return {}
    return json.load(open(p, encoding="utf-8"))


# ============================================================
# 欧赔 -> Poisson 预期总进球
# ============================================================
K = np.arange(0, 14)
FACT = np.array([math.factorial(int(k)) for k in K], float)
LAM = np.round(np.arange(0.10, 4.201, 0.05), 2)


def _grid():
    rows = []
    pmf = {l: np.exp(-l) * l ** K / FACT for l in LAM}
    for lh in LAM:
        for la in LAM:
            m = np.outer(pmf[lh], pmf[la])
            rows.append((lh, la, np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()))
    return np.array(rows)


GRID = _grid()


def devig3(o):
    ih, id_, ia = 1 / o[0], 1 / o[1], 1 / o[2]
    s = ih + id_ + ia
    return ih / s, id_ / s, ia / s


def implied_total(probs):
    """给定去水 (主胜, 平, 客胜), 返回 (λh, λa) 网格最优解"""
    P = np.asarray(probs, float)
    d = ((GRID[None, :, 2] - P[:, None, 0]) ** 2
         + (GRID[None, :, 3] - P[:, None, 1]) ** 2
         + (GRID[None, :, 4] - P[:, None, 2]) ** 2)
    return GRID[d.argmin(1)][:, :2]


# ============================================================
# 样本构建
# ============================================================
def build():
    listings, ou = load("listings.json"), load("ou.json")
    euro, water = load("euro.json"), load("water.json")

    rows = []
    for sid, g in listings.items():
        pack = ou.get(sid)
        if not pack:
            continue
        src = pack.get("crown") or pack.get("bet365")
        if not src:
            continue
        try:
            hg, ag = [int(x) for x in g["score"].split("-")]
        except Exception:
            continue
        goals, line = hg + ag, src["line_close"]
        if abs(goals - line) < 1e-9:            # 整数盘走水
            continue

        def dv(o, u):
            if not o or not u:
                return None
            a, b = 1.0 / o, 1.0 / u
            return a / (a + b)

        p_open = dv(src["over_open"], src["under_open"])
        p_close = dv(src["over_close"], src["under_close"])
        if p_open is None or p_close is None:
            continue

        e = euro.get(sid) or {}
        w = water.get(sid) or {}
        cw = w.get("crown") or w.get("bet365") or {}
        rows.append({
            "sid": sid, "date": g["date"], "league": g["league"],
            "home": g["home"], "away": g["away"],
            "goals": goals, "line": line, "line_open": src["line_open"],
            "line_move": line - src["line_open"],
            "p_over_close": p_close, "p_over_move": p_close - p_open,
            "over_water": src["over_close"], "under_water": src["under_close"],
            "hcp": cw.get("hcp_close"),
            "probs": devig3(e["odds_close"]) if e.get("odds_close") else None,
            "y": 1 if goals > line else 0,
        })

    sub = [r for r in rows if r["probs"]]
    if sub:
        best = implied_total([r["probs"] for r in sub])
        for r, (lh, la) in zip(sub, best):
            r["lam_dev"] = float(lh + la) - r["line"]
    for r in rows:
        r.setdefault("lam_dev", None)

    rows.sort(key=lambda r: (r["date"], r["sid"]))
    return rows


FEATS = {
    "pmove": lambda r: r["p_over_move"],
    "line_move": lambda r: r["line_move"],
    "line": lambda r: r["line"],
    "pclose": lambda r: r["p_over_close"],
    "lam_dev": lambda r: r["lam_dev"] if r["lam_dev"] is not None else 0.0,
    "hcp": lambda r: r["hcp"] if r["hcp"] is not None else 0.0,
}


# ============================================================
# 逻辑回归 (numpy 批量梯度下降)
# ============================================================
def fit_np(X, y, l2=3.0, lr=0.3, epochs=3000):
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    n = len(X)
    mu, sd = X.mean(0), X.std(0)
    sd[sd < 1e-12] = 1.0
    Z = np.hstack([np.ones((n, 1)), (X - mu) / sd])
    w = np.zeros(X.shape[1] + 1)
    for _ in range(epochs):
        p = 1.0 / (1.0 + np.exp(-Z @ w))
        g = Z.T @ (p - y) / n
        g[1:] += l2 * w[1:] / n
        w -= lr * g
    return w, mu, sd


def oof(rows, names, k=5):
    """按日期分组的 k 折样本外概率"""
    dates = sorted(set(r["date"] for r in rows))
    buckets = [[] for _ in range(k)]
    for i, d in enumerate(dates):
        buckets[i * k // len(dates)].append(d)
    ps = [None] * len(rows)
    for bi in range(k):
        test = set(buckets[bi])
        idx = [i for i, r in enumerate(rows) if r["date"] in test]
        tr = [r for r in rows if r["date"] not in test]
        w, mu, sd = fit_np([[FEATS[n](r) for n in names] for r in tr],
                           [r["y"] for r in tr])
        X = np.asarray([[FEATS[n](rows[i]) for n in names] for i in idx], float)
        Z = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
        p = 1.0 / (1.0 + np.exp(-Z @ w))
        for i, v in zip(idx, p):
            ps[i] = float(v)
    return ps


def settle_ou(goals, line, side):
    k = round((goals - line) * 4)
    if k >= 2:
        u = 1.0
    elif k == 1:
        u = 0.5
    elif k == 0:
        u = 0.0
    elif k == -1:
        u = -0.5
    else:
        u = -1.0
    return u if side == 1 else -u


def roi(arr, side=1):
    pr = 0.0
    win = 0
    for r in arr:
        u = settle_ou(r["goals"], r["line"], side)
        pr += payout(u, r["over_water"] if side == 1 else r["under_water"]) - 1
        if u > 0:
            win += 1
    return 100.0 * win / len(arr), 100.0 * pr / len(arr)


# ============================================================
# 评估
# ============================================================
def evaluate(rows, ps, title):
    n = len(rows)
    profit = 0.0
    wins = 0
    for r, p in zip(rows, ps):
        side = 1 if p >= 0.5 else -1
        u = settle_ou(r["goals"], r["line"], side)
        profit += payout(u, r["over_water"] if side == 1 else r["under_water"]) - 1
        if u > 0:
            wins += 1
    print("\n== %s ==  n=%d  命中 %.1f%%  ROI %+.2f%%"
          % (title, n, 100.0 * wins / n, 100.0 * profit / n))

    print("  %-14s %6s %8s %8s" % ("信号 |p-.5|", "场次", "命中", "ROI"))
    for lo, hi in ((0.00, 0.02), (0.02, 0.05), (0.05, 0.08), (0.08, 1.01)):
        idx = [i for i, p in enumerate(ps) if lo <= abs(p - 0.5) < hi]
        if not idx:
            continue
        pr = sum(payout(settle_ou(rows[i]["goals"], rows[i]["line"],
                                  1 if ps[i] >= 0.5 else -1),
                        rows[i]["over_water"] if ps[i] >= 0.5 else rows[i]["under_water"]) - 1
                 for i in idx)
        wn = sum(1 for i in idx
                 if settle_ou(rows[i]["goals"], rows[i]["line"],
                              1 if ps[i] >= 0.5 else -1) > 0)
        print("  %.2f~%.2f      %6d %7.1f%% %+7.2f%%"
              % (lo, hi, len(idx), 100.0 * wn / len(idx), 100.0 * pr / len(idx)))

    print("  按月:")
    by_month = collections.defaultdict(list)
    for r, p in zip(rows, ps):
        by_month[r["date"][:6]].append((r, p))
    for m in sorted(by_month):
        arr = by_month[m]
        pr = sum(payout(settle_ou(r["goals"], r["line"], 1 if p >= 0.5 else -1),
                        r["over_water"] if p >= 0.5 else r["under_water"]) - 1
                 for r, p in arr)
        wn = sum(1 for r, p in arr
                 if settle_ou(r["goals"], r["line"], 1 if p >= 0.5 else -1) > 0)
        print("    %s n=%-5d 命中 %5.1f%%  ROI %+6.2f%%"
              % (m, len(arr), 100.0 * wn / len(arr), 100.0 * pr / len(arr)))


def rule_report(rows):
    """低盘口 + 欧赔隐含进球高于盘口 的观察清单 (非策略)"""
    cand = [r for r in rows if r["lam_dev"] is not None and r["line"] <= 2.25]
    print("\n== 观察清单: line<=2.25 且 lam_dev>=0.10 ==")
    sel = [r for r in cand if r["lam_dev"] >= 0.10]
    if not sel:
        print("  无样本")
        return
    hit, pr = roi(sel)
    w = statistics.mean(r["over_water"] for r in sel)
    print("  n=%d  大球率 %.1f%%  均水位 %.3f  盈亏线 %.1f%%  ROI %+.2f%%"
          % (len(sel), hit, w, 100 / (1 + w), pr))
    print("  按月:")
    by = collections.defaultdict(list)
    for r in sel:
        by[r["date"][:6]].append(r)
    for m in sorted(by):
        h, p = roi(by[m])
        print("    %s n=%-3d 大球率 %5.1f%%  ROI %+6.2f%%" % (m, len(by[m]), h, p))
    print("  提示: 样本小且按月不稳定, 仅作观察, 不作为投注策略。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feats", default="")
    a = ap.parse_args()

    rows = build()
    print("样本 %d 场  %s ~ %s" % (len(rows), rows[0]["date"], rows[-1]["date"]))
    print("大球率 %.1f%%  均大球水 %.3f  盈亏线 %.1f%%"
          % (100.0 * sum(r["y"] for r in rows) / len(rows),
             statistics.mean(r["over_water"] for r in rows),
             100.0 / (1 + statistics.mean(r["over_water"] for r in rows))))

    if a.feats:
        names = a.feats.split(",")
        evaluate(rows, oof(rows, names), "特征 " + "+".join(names))
        return

    for names in (["pmove"], ["pmove", "line_move"], ["pmove", "line_move", "line"],
                  ["pmove", "line_move", "line", "lam_dev"]):
        evaluate(rows, oof(rows, names), "特征 " + "+".join(names))

    rule_report(rows)


if __name__ == "__main__":
    main()
