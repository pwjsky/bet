# -*- coding: utf-8 -*-
"""大小球数据勘查: listings.total_listed 覆盖率 + jsData 大小球字段验证"""
import json
import os
import re
import sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from titan007_collector import fetch  # noqa: E402
from titan_water_collector import parse_rows  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

DATA = os.path.join(BASE, "titan_data")
raw = json.load(open(os.path.join(DATA, "listings.json"), encoding="utf-8"))
print("listings type:", type(raw).__name__, "n:", len(raw))
recs = list(raw.values()) if isinstance(raw, dict) else raw

have = [r for r in recs if r.get("total_listed")]
print("有 total_listed: %d / %d = %.1f%%" % (len(have), len(recs), 100.0 * len(have) / len(recs)))
by_date = Counter(r.get("date") for r in have)
print("按日期(最近12天):", sorted(by_date.items())[-12:])
print("样例:", [(r["date"], r["league"], r["total_listed"], int(r["score"].split("-")[0]) + int(r["score"].split("-")[1]))
               for r in have[:5]])

vals = Counter(r["total_listed"] for r in have)
print("最常见盘口:", vals.most_common(15))

# jsData 字段验证: 取一场今天的比赛
sid = "3102433"
url = "https://live.titan007.com/jsData/%s/%s/%s.js" % (sid[:2], sid[2:4], sid)
txt = fetch(url, "utf-8")
print("\njs len:", len(txt))
for name in ("sOdds", "sOdds8"):
    rows = parse_rows(txt, name)
    print(name, "rows:", len(rows))
    if rows:
        for r in rows[:2] + rows[-2:]:
            print("  标签=%s len=%d" % (r[0], len(r)))
            print("   ", r)
