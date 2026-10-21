# -*- coding: utf-8 -*-
"""
联赛热度分层的逐日选强回测 + 热度表生成
========================================
1. 用 5 折样本外概率, 按热度分组做逐日 Top10
2. 输出 titan_data/league_tiers.json 供 today_picks.py 使用

用法:
  py tier_backtest.py
"""
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
OUT = os.path.join(DATA, "league_tiers.json")

HOT, MID = 200, 120


def rows_all():
    rows = []
    for r in build("crown"):
        e = E.get(r["sid"], {})
        l = L.get(r["sid"], {})
        if not e.get("n_euro"):
            continue
        r = dict(r)
        r["n_euro"] = e["n_euro"]
        r["league"] = l.get("league") or "?"
        r["y"] = 1 if ((r["hg"] - r["ag"]) - r["h"]) > 0 else 0
        rows.append(r)
    rows = [r for r in rows if abs((r["hg"] - r["ag"]) - r["h"]) > 1e-9]
    rows.sort(key=lambda r: r["date"])
    return rows


def oof(rows, k=5, epochs=800):
    dates = sorted(set(r["date"] for r in rows))
    buckets = [[] for _ in range(k)]
    for i, d in enumerate(dates):
        buckets[i * k // len(dates)].append(d)
    ps = [None] * len(rows)
    for b in range(k):
        td = set(buckets[b])
        tr = [r for r in rows if r["date"] not in td]
        te = [i for i, r in enumerate(rows) if r["date"] in td]
        X = [[r["p_move"]] for r in tr]
        mu, sd = standardize_fit(X)
        w, bb = fit_logreg(transform(X, mu, sd), [r["y"] for r in tr],
                           l2=3.0, lr=0.1, epochs=epochs)
        for i in te:
            ps[i] = sigmoid(bb + w[0] * (rows[i]["p_move"] - mu[0]) / sd[0])
    return ps


def day_topn(rows, n=10):
    days = {}
    for r in rows:
        days.setdefault(r["date"], []).append(r)
    cnt = wins = 0
    profit = 0.0
    odds_sum = 0.0
    up = 0
    day_pnl = []
    for d, arr in days.items():
        arr.sort(key=lambda r: -r["sig"])
        pnl = 0.0
        for r in arr[:n]:
            side = 1 if r["p"] >= 0.5 else -1
            odds = r["wo_h"] if side == 1 else r["wo_a"]
            u = settle_units(r["h"], r["hg"], r["ag"])
            u = u if side == 1 else -u
            pay = payout(u, odds) - 1.0
            cnt += 1
            profit += pay
            pnl += pay
            odds_sum += odds
            if u > 0:
                wins += 1
        day_pnl.append(pnl)
        if pnl > 0:
            up += 1
    if not cnt:
        return "无场次"
    return ("n=%-4d 日均%4.1f 命中 %5.1f%%  水位 %.3f  ROI %+6.2f%%"
            "  盈利日 %d/%d  最差%+.2fU"
            % (cnt, 1.0 * cnt / len(day_pnl), 100.0 * wins / cnt,
               odds_sum / cnt, 100.0 * profit / cnt, up, len(day_pnl),
               min(day_pnl)))


def main():
    rows = rows_all()
    ps = oof(rows)
    for r, p in zip(rows, ps):
        r["p"] = p
        r["sig"] = abs(p - 0.5)
    print("样本 %d 场  %s ~ %s" % (len(rows), rows[0]["date"], rows[-1]["date"]))

    by_lg = {}
    for r in rows:
        by_lg.setdefault(r["league"], []).append(r["n_euro"])
    avg = {lg: statistics.mean(v) for lg, v in by_lg.items()}

    def tier_of(lg):
        v = avg.get(lg)
        if v is None or len(by_lg.get(lg, [])) < 5:
            return "unknown"
        if v >= HOT:
            return "hot"
        if v >= MID:
            return "mid"
        return "cold"

    groups = {"hot": [], "mid": [], "cold": [], "unknown": []}
    for r in rows:
        groups[tier_of(r["league"])].append(r)

    print("\n逐日 Top10 (5 折样本外):")
    for name, label in (("hot", "仅热门"), ("mid", "仅中等"), ("cold", "仅冷门"),
                        ("all", "全部"), ("hotmid", "热门+中等")):
        arr = groups["hot"] + groups["mid"] if name == "hotmid" else (
            rows if name == "all" else groups[name])
        print("  %-10s %s" % (label, day_topn(arr)))

    print("\n逐日 Top5 (5 折样本外):")
    for name, label in (("hot", "仅热门"), ("cold", "仅冷门"), ("all", "全部"),
                        ("hotmid", "热门+中等")):
        arr = groups["hot"] + groups["mid"] if name == "hotmid" else (
            rows if name == "all" else groups[name])
        print("  %-10s %s" % (label, day_topn(arr, 5)))

    table = {}
    for lg, v in by_lg.items():
        if len(v) < 5:
            continue
        table[lg] = {"n": len(v), "n_euro": round(statistics.mean(v), 1),
                     "tier": tier_of(lg)}
    json.dump(table, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已保存 %s (收录 %d 个联赛, 场次>=5)" % (OUT, len(table)))


if __name__ == "__main__":
    main()
