# -*- coding: utf-8 -*-
"""
联赛热度分层回测
================
热度定义:
  n_euro   每场欧赔报价公司数(40~360), 直接反映市场关注度
  p_std    各公司去水概率标准差, 越小说明定价越一致(市场越有效)

分层:
  联赛级: 该联赛所有场次 n_euro 的均值 >=200 热门, 120~200 中等, <120 冷门
  场次级: 单场 n_euro 直接分档(稳健性检验)

模型: 与 today_picks 同口径的单特征 p_move, 按日期滚动样本外

用法:
  py league_split.py
  py league_split.py --book bet365
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
from verify_water_roi import build, payout, settle_units  # noqa: E402

DATA = os.path.join(BASE, "titan_data")
E = json.load(open(os.path.join(DATA, "euro.json"), encoding="utf-8"))
L = json.load(open(os.path.join(DATA, "listings.json"), encoding="utf-8"))

TIERS = [(200, "热门"), (120, "中等"), (0, "冷门")]


def enrich(rows):
    out = []
    for r in rows:
        e = E.get(r["sid"], {})
        l = L.get(r["sid"], {})
        if not e.get("n_euro"):
            continue
        r = dict(r)
        r["n_euro"] = e["n_euro"]
        r["p_std"] = e.get("p_std_open") or 0.0
        r["league"] = l.get("league") or "?"
        out.append(r)
    return out


def rolling_oos(rows):
    """按日期滚动: 每天只用之前的数据训练。"""
    dates = sorted(set(r["date"] for r in rows))
    out = []
    for i in range(5, len(dates)):
        d = dates[i]
        tr = [r for r in rows if r["date"] < d]
        te = [r for r in rows if r["date"] == d]
        if len(tr) < 300 or not te:
            continue
        X = [[r["p_move"]] for r in tr]
        mu, sd = standardize_fit(X)
        w, b = fit_logreg(transform(X, mu, sd), [r["y"] for r in tr],
                          l2=3.0, lr=0.1, epochs=800)
        for r in te:
            p = sigmoid(b + w[0] * (r["p_move"] - mu[0]) / sd[0])
            rr = dict(r)
            rr["p"] = p
            rr["sig"] = abs(p - 0.5)
            rr["side"] = 1 if p >= 0.5 else -1
            rr["odds"] = r["wo_h"] if rr["side"] == 1 else r["wo_a"]
            u = settle_units(r["h"], r["hg"], r["ag"])
            rr["unit"] = u if rr["side"] == 1 else -u
            rr["pay"] = payout(rr["unit"], rr["odds"]) - 1.0
            out.append(rr)
    return out


def stat(arr, label):
    n = len(arr)
    if not n:
        print("  %-20s 无场次" % label)
        return
    wins = sum(1 for r in arr if r["unit"] > 0)
    odds = sum(r["odds"] for r in arr) / n
    roi = sum(r["pay"] for r in arr) / n
    print("  %-20s n=%-5d 命中 %5.1f%%  水位 %.3f  ROI %+6.2f%%"
          % (label, n, 100.0 * wins / n, odds, 100.0 * roi))


def report(rows, label):
    print("\n== %s ==  n=%d" % (label, len(rows)))
    stat(rows, "全下")
    for thr in (0.05, 0.08, 0.10):
        stat([r for r in rows if r["sig"] >= thr], "sig>=%.2f" % thr)
    k = max(1, len(rows) // 5)
    stat(sorted(rows, key=lambda r: -r["sig"])[:k], "信号前20%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="crown")
    a = ap.parse_args()

    rows = enrich(build(a.book))
    rows = [r for r in rows if abs((r["hg"] - r["ag"]) - r["h"]) > 1e-9]
    for r in rows:
        r["y"] = 1 if ((r["hg"] - r["ag"]) - r["h"]) > 0 else 0

    by_lg = {}
    for r in rows:
        by_lg.setdefault(r["league"], []).append(r["n_euro"])
    avg_n = {lg: statistics.mean(v) for lg, v in by_lg.items() if len(v) >= 5}

    print("样本 %d 场  %d 个联赛(>=5场)  %s ~ %s"
          % (len(rows), len(avg_n), rows[0]["date"], rows[-1]["date"]))
    oos = rolling_oos(rows)
    print("滚动样本外 %d 场  %s ~ %s" % (len(oos), oos[0]["date"], oos[-1]["date"]))

    # ---------- 1. 联赛级分层 ----------
    groups = {name: [] for _, name in TIERS}
    for r in oos:
        v = avg_n.get(r["league"])
        if v is None:          # 联赛场次<5, 不参与分层
            continue
        for thr, name in TIERS:
            if v >= thr:
                groups[name].append(r)
                break

    print("\n" + "=" * 62)
    print("联赛级分层 (按该联赛平均报价公司数)")
    print("=" * 62)
    print("  %-6s %6s %6s %8s %8s %8s"
          % ("层级", "场次", "联赛数", "|move|", "p_std", "水位"))
    for _, name in TIERS:
        arr = groups[name]
        if not arr:
            continue
        print("  %-6s %6d %6d %8.4f %8.4f %8.3f"
              % (name, len(arr), len(set(r["league"] for r in arr)),
                 statistics.mean(abs(r["p_move"]) for r in arr),
                 statistics.mean(r["p_std"] for r in arr),
                 statistics.mean(r["odds"] for r in arr)))
    for _, name in TIERS:
        report(groups[name], "联赛级 %s" % name)

    # ---------- 2. 场次级分层 ----------
    print("\n" + "=" * 62)
    print("场次级分层 (按单场报价公司数, 稳健性检验)")
    print("=" * 62)
    fgroups = {name: [] for _, name in TIERS}
    for r in oos:
        for thr, name in TIERS:
            if r["n_euro"] >= thr:
                fgroups[name].append(r)
                break
    for _, name in TIERS:
        report(fgroups[name], "场次级 %s" % name)

    # ---------- 3. 联赛清单 ----------
    print("\n== 热门联赛 (平均报价公司数前 30, 场次>=5) ==")
    print("  %-14s %5s %7s" % ("联赛", "场次", "公司数"))
    for lg, v in sorted(avg_n.items(), key=lambda x: -x[1])[:30]:
        print("  %-14s %5d %7.1f" % (lg, len(by_lg[lg]), v))

    print("\n== 冷门联赛 (平均报价公司数后 20, 场次>=10) ==")
    cold = [(lg, v) for lg, v in avg_n.items() if len(by_lg[lg]) >= 10]
    for lg, v in sorted(cold, key=lambda x: x[1])[:20]:
        print("  %-14s %5d %7.1f" % (lg, len(by_lg[lg]), v))


if __name__ == "__main__":
    main()
