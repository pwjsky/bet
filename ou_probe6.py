# -*- coding: utf-8 -*-
"""测试各月份 jsData 可访问性"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from titan007_collector import fetch  # noqa: E402
from titan_water_collector import parse_rows, num  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

DATA = os.path.join(BASE, "titan_data")
raw = json.load(open(os.path.join(DATA, "listings.json"), encoding="utf-8"))
recs = [r for r in raw.values() if r.get("total_listed")]

by_month = {}
for r in recs:
    by_month.setdefault(r["date"][:6], []).append(r)
print("有大小球盘口的月份:", {k: len(v) for k, v in sorted(by_month.items())})


def ou(row):
    """按行长度解析全场大小球: 46字段->[21:27], 37字段->[15:21]"""
    if len(row) >= 46:
        seg = row[21:27]
    elif len(row) >= 21:
        seg = row[15:21]
    else:
        return None
    over, line, under = num(seg[3]), num(seg[4]), num(seg[5])
    if line is None:
        return None
    return over, line, under


for month in sorted(by_month):
    cand = by_month[month]
    r = cand[0]
    sid = r["id"]
    url = "https://live.titan007.com/jsData/%s/%s/%s.js" % (sid[:2], sid[2:4], sid)
    try:
        txt = fetch(url, "utf-8")
        valid = "error_404" not in txt and len(txt) > 1000
        info = []
        if valid:
            for name in ("sOdds", "sOdds8"):
                rows = parse_rows(txt, name)
                if rows:
                    info.append("%s len=%d ou=%s" % (name, len(rows[0]), ou(rows[0])))
        print(month, sid, r["league"], r["score"], "total=", r["total_listed"],
              "valid=", valid, "|", " ".join(info))
    except Exception as e:
        print(month, sid, "ERR", repr(e))
