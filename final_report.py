# -*- coding: utf-8 -*-
"""
扩样后的最终汇总
================
用 calibrate_pmove.py 缓存的 5 折样本外概率, 输出:
  1. 全下 / 信号分档
  2. 逐日 TopN
  3. 按月分段(看 edge 是否随样本增加而衰减)

用法:
  py final_report.py
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from verify_water_roi import build, payout, settle_units  # noqa: E402

DATA = os.path.join(BASE, "titan_data")


def main():
    rows = build("crown")
    rows = [r for r in rows if abs((r["hg"] - r["ag"]) - r["h"]) > 1e-9]
    ps = json.load(open(os.path.join(DATA, "oof_pmove.json"), encoding="utf-8"))
    if len(ps) != len(rows):
        print("概率缓存与样本不一致: %d vs %d, 请重跑 calibrate_pmove.py"
              % (len(ps), len(rows)))
        return
    for r, p in zip(rows, ps):
        r["p"] = p
        r["sig"] = abs(p - 0.5)
        r["side"] = 1 if p >= 0.5 else -1
        r["odds"] = r["wo_h"] if r["side"] == 1 else r["wo_a"]
        u = settle_units(r["h"], r["hg"], r["ag"])
        r["unit"] = u if r["side"] == 1 else -u
        r["pay"] = payout(r["unit"], r["odds"]) - 1.0

    ds = sorted(set(r["date"] for r in rows))
    print("样本 %d 场  %d 天  %s ~ %s" % (len(rows), len(ds), ds[0], ds[-1]))

    def stat(arr, label):
        n = len(arr)
        if not n:
            print("  %-18s 无场次" % label)
            return
        wins = sum(1 for r in arr if r["unit"] > 0)
        odds = sum(r["odds"] for r in arr) / n
        roi = sum(r["pay"] for r in arr) / n
        print("  %-18s n=%-5d 命中 %5.1f%%  水位 %.3f  ROI %+6.2f%%"
              % (label, n, 100.0 * wins / n, odds, 100.0 * roi))

    print("\n== 信号分档 ==")
    stat(rows, "全下")
    for t in (0.05, 0.08, 0.10, 0.12, 0.15):
        stat([r for r in rows if r["sig"] >= t], "sig>=%.2f" % t)

    days = {}
    for r in rows:
        days.setdefault(r["date"], []).append(r)

    print("\n== 逐日 TopN (每天按信号取前 N) ==")
    for topn in (1, 3, 5, 10):
        cnt = wins = 0
        profit = 0.0
        odds_sum = 0.0
        day_pnl = []
        for d, arr in days.items():
            arr.sort(key=lambda r: -r["sig"])
            pnl = 0.0
            for r in arr[:topn]:
                cnt += 1
                profit += r["pay"]
                pnl += r["pay"]
                odds_sum += r["odds"]
                if r["unit"] > 0:
                    wins += 1
            day_pnl.append(pnl)
        up = sum(1 for x in day_pnl if x > 0)
        print("  %-6s n=%-4d 日均%4.1f 命中 %5.1f%%  水位 %.3f  ROI %+6.2f%%"
              "  盈利日 %d/%d  最好%+.2fU 最差%+.2fU"
              % ("Top%d" % topn, cnt, 1.0 * cnt / len(day_pnl),
                 100.0 * wins / cnt, odds_sum / cnt, 100.0 * profit / cnt,
                 up, len(day_pnl), max(day_pnl), min(day_pnl)))

    print("\n== 按月分段 (Top10 / 全下) ==")
    months = {}
    for r in rows:
        months.setdefault(r["date"][:6], []).append(r)
    for m in sorted(months):
        arr = months[m]
        cnt = wins = 0
        profit = 0.0
        for d, day in _group(arr).items():
            day.sort(key=lambda r: -r["sig"])
            for r in day[:10]:
                cnt += 1
                profit += r["pay"]
                if r["unit"] > 0:
                    wins += 1
        n = len(arr)
        w2 = sum(1 for r in arr if r["unit"] > 0)
        roi2 = sum(r["pay"] for r in arr) / n
        print("  %s  Top10 n=%-4d 命中 %5.1f%% ROI %+6.2f%%   |   全下 n=%-5d 命中 %5.1f%% ROI %+6.2f%%"
              % (m, cnt, 100.0 * wins / cnt, 100.0 * profit / cnt,
                 n, 100.0 * w2 / n, 100.0 * roi2))


def _group(arr):
    out = {}
    for r in arr:
        out.setdefault(r["date"], []).append(r)
    return out


if __name__ == "__main__":
    main()
