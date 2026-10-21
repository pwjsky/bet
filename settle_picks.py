# -*- coding: utf-8 -*-
"""
推荐结算器
==========
读取 titan_data/today_picks_YYYYMMDD.json, 抓当天与次日比分, 逐场结算。

用法:
  py settle_picks.py --date 20261017
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from titan007_collector import fetch, parse_over_day  # noqa: E402
from verify_water_roi import payout, settle_units  # noqa: E402

DATA = os.path.join(BASE, "titan_data")


def live_scores(sids):
    """从盘口时间序列取最新比分。返回 {sid: (标签, 主, 客)}。"""
    out = {}
    for sid in sids:
        try:
            url = "https://live.titan007.com/jsData/%s/%s/%s.js" % (
                sid[:2], sid[2:4], sid)
            txt = fetch(url, "utf-8")
        except Exception:
            continue
        rows = re.findall(r"\['([^']{1,4})',(\d+),(\d+)", txt)
        if rows:
            label, hg, ag = rows[-1]
            out[sid] = (label, int(hg), int(ag))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    a = ap.parse_args()

    path = os.path.join(DATA, "today_picks_%s.json" % a.date)
    picks = json.load(open(path, encoding="utf-8"))

    d0 = datetime.strptime(a.date, "%Y%m%d")
    games = {}
    for i in (0, 1):
        d = (d0 + timedelta(days=i)).strftime("%Y%m%d")
        try:
            for g in parse_over_day(d):
                games[g["id"]] = g
        except Exception as e:
            print("抓 %s 失败: %s" % (d, e))
    print("比分库 %d 场 (含次日)\n" % len(games))
    live = live_scores([p["sid"] for p in picks if p["sid"] not in games])

    cnt = wins = 0
    profit = 0.0
    print("%-2s %-6s %-10s %-22s %-3s %-7s %-6s %-6s %s"
          % ("#", "开赛", "联赛", "对阵", "方向", "比分", "盘口", "水位", "结果"))
    for i, p in enumerate(picks, 1):
        g = games.get(p["sid"])
        if g:
            hg, ag = [int(x) for x in g["score"].split("-")]
            status = ""
        elif p["sid"] in live:
            label, hg, ag = live[p["sid"]]
            if label.isdigit():
                print("%-2d %-6s %-10s %-22s %-3s %-7s %-6s %-6s 进行中(%s')"
                      % (i, p["time"][-5:], p["league"],
                         "%s vs %s" % (p["home"], p["away"]),
                         "主" if p["side"] == 1 else "客",
                         "%d-%d" % (hg, ag), p["hcp"], p["odds"], label))
                continue
            if label in ("未开场", "早餐", "中场"):
                print("%-2d %-6s %-10s %-22s %-3s %-7s %-6s %-6s %s"
                      % (i, p["time"][-5:], p["league"],
                         "%s vs %s" % (p["home"], p["away"]),
                         "主" if p["side"] == 1 else "客",
                         "%d-%d" % (hg, ag), p["hcp"], p["odds"], label))
                continue
            status = label
        else:
            print("%-2d %-6s %-10s %-22s %-3s %-7s %-6s %-6s 无比分"
                  % (i, p["time"][-5:], p["league"],
                     "%s vs %s" % (p["home"], p["away"]),
                     "主" if p["side"] == 1 else "客", "-", p["hcp"], p["odds"]))
            continue
        u = settle_units(p["hcp"], hg, ag)
        if p["side"] == -1:
            u = -u
        pay = payout(u, p["odds"]) - 1.0
        cnt += 1
        profit += pay
        if u > 0:
            wins += 1
        tag = {1.0: "全赢", 0.5: "半赢", 0.0: "走水", -0.5: "半输"}.get(u, "全输")
        print("%-2d %-6s %-10s %-22s %-3s %-7s %-6s %-6s %s %+.2fU"
              % (i, p["time"][-5:], p["league"], "%s vs %s" % (p["home"], p["away"]),
                 "主" if p["side"] == 1 else "客", g["score"], p["hcp"], p["odds"],
                 tag, pay))

    if cnt:
        print("\n合计: %d 场, %d 胜, 命中 %.1f%%, 盈亏 %+.2fU, ROI %+.2f%%"
              % (cnt, wins, 100.0 * wins / cnt, profit, 100.0 * profit / cnt))


if __name__ == "__main__":
    main()
