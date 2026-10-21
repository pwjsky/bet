# -*- coding: utf-8 -*-
"""验证历史 jsData 可访问性 + 大小球字段随时间变化"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from titan007_collector import fetch  # noqa: E402
from titan_water_collector import parse_rows  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

DATA = os.path.join(BASE, "titan_data")
raw = json.load(open(os.path.join(DATA, "listings.json"), encoding="utf-8"))
recs = list(raw.values())

for day in ("20261016", "20261010", "20261001", "20260920"):
    cand = [r for r in recs if r.get("date") == day and r.get("total_listed")]
    print("=" * 30)
    print(day, "候选", len(cand))
    for r in cand[:2]:
        sid = r["id"]
        url = "https://live.titan007.com/jsData/%s/%s/%s.js" % (sid[:2], sid[2:4], sid)
        try:
            txt = fetch(url, "utf-8")
        except Exception as e:
            print(" ", sid, r["league"], "ERR", repr(e))
            continue
        ok = len(txt) > 1000 and "error_404" not in txt
        print(" ", sid, r["league"], r["score"], "total=", r["total_listed"], "len=", len(txt), "valid=", ok)
        if not ok:
            continue
        for name in ("sOdds", "sOdds8"):
            rows = parse_rows(txt, name)
            print("   ", name, "rows=", len(rows))
            for x in rows[:3]:
                print("      ", x[0], "hcp=", x[9:12], "ou=", x[15:21])
