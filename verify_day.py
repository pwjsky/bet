# -*- coding: utf-8 -*-
"""
单日独立验证
============
取一个已采集但未参与训练的日期, 用其余全部样本训练, 再按日常口径结算。

用法:
  py verify_day.py --date 20260917
  py verify_day.py --date 20260917 --book bet365
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from asian_handicap_model_v3 import (  # noqa: E402
    fit_logreg, sigmoid, standardize_fit, transform,
)
from verify_water_roi import (  # noqa: E402
    build, payout, settle_units, apply_calib,
)

DATA = os.path.join(BASE, "titan_data")
L = json.load(open(os.path.join(DATA, "listings.json"), encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--book", default="crown")
    a = ap.parse_args()

    rows = build(a.book)
    rows = [r for r in rows if abs((r["hg"] - r["ag"]) - r["h"]) > 1e-9]  # 去走水
    test = [r for r in rows if r["date"] == a.date]
    tr = [r for r in rows if r["date"] != a.date]
    if not test:
        print("%s 没有可用样本(检查 euro/water 是否已采集)" % a.date)
        return
    print("%s 验证 %d 场 | 训练 %d 场(%s ~ %s)"
          % (a.date, len(test), len(tr), tr[0]["date"], tr[-1]["date"]))

    X = [[r["p_move"]] for r in tr]
    mu, sd = standardize_fit(X)
    ys = [1 if ((r["hg"] - r["ag"]) - r["h"]) > 0 else 0 for r in tr]
    w, b = fit_logreg(transform(X, mu, sd), ys, l2=3.0, lr=0.1, epochs=1500)
    print("模型 w=%+.4f b=%+.4f (与 today_picks 同口径)" % (w[0], b))

    calib = os.path.join(DATA, "calibration.json")
    edges = [tuple(x) for x in
             json.load(open(calib, encoding="utf-8"))["iso_edges"]] if os.path.exists(calib) else []

    for r in test:
        r["p_raw"] = sigmoid(b + w[0] * (r["p_move"] - mu[0]) / sd[0])
        r["p"] = apply_calib(edges, r["p_raw"])
        r["sig"] = abs(r["p_raw"] - 0.5)
        r["side"] = 1 if r["p"] >= 0.5 else -1
        r["odds"] = r["wo_h"] if r["side"] == 1 else r["wo_a"]
        p_side = r["p"] if r["side"] == 1 else 1 - r["p"]
        r["ev"] = p_side * (1 + r["odds"]) - 1
        u = settle_units(r["h"], r["hg"], r["ag"])
        r["unit"] = u if r["side"] == 1 else -u
        r["pay"] = payout(r["unit"], r["odds"]) - 1.0

    def stat(arr, label):
        if not arr:
            print("  %-22s 无场次" % label)
            return
        n = len(arr)
        wins = sum(1 for r in arr if r["unit"] > 0)
        odds = sum(r["odds"] for r in arr) / n
        roi = sum(r["pay"] for r in arr) / n
        print("  %-22s n=%-3d 命中 %5.1f%%  水位 %.3f  ROI %+6.2f%%  盈亏 %+.2fU"
              % (label, n, 100.0 * wins / n, odds, 100 * roi, sum(r["pay"] for r in arr)))

    print("\n逐日口径:")
    stat(test, "全下")
    for k in (10, 8, 7):
        stat(sorted(test, key=lambda r: -r["sig"])[:k], "Top%d" % k)
    for thr in (0.10, 0.12, 0.15):
        stat([r for r in test if r["sig"] >= thr], "sig>=%.2f" % thr)

    print("\nTop10 明细:")
    print("  %-12s %-22s %-6s %-4s %6s %7s %5s %6s"
          % ("联赛", "对阵", "比分", "方向", "信号", "盘口", "水位", "结果"))
    for r in sorted(test, key=lambda r: -r["sig"])[:10]:
        m = L.get(r["sid"], {})
        res = {1.0: "全赢", 0.5: "半赢", 0.0: "走水",
               -0.5: "半输", -1.0: "全输"}[r["unit"]]
        vs = "%s vs %s" % (m.get("home", ""), m.get("away", ""))
        print("  %-12s %-22s %-6s %-4s %6.3f %+7.2f %5.2f %6s"
              % (m.get("league", "")[:6], vs[:22], "%d-%d" % (r["hg"], r["ag"]),
                 "主" if r["side"] == 1 else "客", r["sig"], r["h"],
                 r["odds"], res))


if __name__ == "__main__":
    main()
