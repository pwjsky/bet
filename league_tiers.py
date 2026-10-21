# -*- coding: utf-8 -*-
"""
联赛热度分层探查
================
用两个市场指标给联赛分层:
  n_euro   : 该场欧赔报价公司数(热度直接代理)
  p_std    : 各公司去水概率的标准差(分歧越小, 市场越有效)

用法:
  py league_tiers.py
"""
import json
import os
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "titan_data")


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def main():
    euro = load("euro.json")
    listings = load("listings.json")

    agg = {}
    for sid, e in euro.items():
        l = listings.get(sid)
        if not l:
            continue
        lg = l.get("league") or "?"
        a = agg.setdefault(lg, {"n": 0, "n_euro": [], "move": [], "pstd": []})
        a["n"] += 1
        if e.get("n_euro"):
            a["n_euro"].append(e["n_euro"])
        if e.get("p_move") is not None:
            a["move"].append(abs(e["p_move"]))
        if e.get("p_std_open") is not None:
            a["pstd"].append(e["p_std_open"])

    rows = []
    for lg, a in agg.items():
        rows.append({
            "league": lg,
            "n": a["n"],
            "n_euro": statistics.mean(a["n_euro"]) if a["n_euro"] else 0,
            "move": statistics.mean(a["move"]) if a["move"] else 0,
            "pstd": statistics.mean(a["pstd"]) if a["pstd"] else 0,
        })

    print("联赛数 %d, 场次 %d" % (len(rows), sum(r["n"] for r in rows)))
    print("\n== 按报价公司数排序 (前 60) ==")
    print("%-14s %6s %8s %8s %8s" % ("联赛", "场次", "公司数", "|move|", "p_std"))
    for r in sorted(rows, key=lambda x: -x["n_euro"])[:60]:
        print("%-14s %6d %8.1f %8.4f %8.4f"
              % (r["league"], r["n"], r["n_euro"], r["move"], r["pstd"]))

    print("\n== 按场次数排序 (前 40) ==")
    for r in sorted(rows, key=lambda x: -x["n"])[:40]:
        print("%-14s %6d %8.1f %8.4f %8.4f"
              % (r["league"], r["n"], r["n_euro"], r["move"], r["pstd"]))


if __name__ == "__main__":
    main()
