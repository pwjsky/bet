# -*- coding: utf-8 -*-
"""比对 jsData 大小球字段与比分页 total_listed"""
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from titan007_collector import fetch  # noqa: E402
from titan_water_collector import parse_rows, num  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

DATA = os.path.join(BASE, "titan_data")
raw = json.load(open(os.path.join(DATA, "listings.json"), encoding="utf-8"))
recs = [r for r in raw.values() if r.get("total_listed")]
sample = [r for r in recs if r["date"] in ("20261016", "20261010", "20260920")][:60]


def ou_val(s):
    parts = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s or "")]
    if not parts:
        return None
    return sum(parts) / len(parts)


def one(r):
    sid = r["id"]
    url = "https://live.titan007.com/jsData/%s/%s/%s.js" % (sid[:2], sid[2:4], sid)
    try:
        txt = fetch(url, "utf-8")
    except Exception:
        return None
    out = {"sid": sid, "total": ou_val(r["total_listed"])}
    for name, key in (("sOdds", "crown"), ("sOdds8", "b365")):
        rows = [x for x in parse_rows(txt, name)
                if len(x) > 20 and x[0] in ("早餐", "未开场")]
        if not rows:
            continue
        last = rows[-1]
        out[key] = (num(last[19]), num(last[18]), num(last[20]))
        out[key + "_semi"] = (num(last[16]), num(last[15]), num(last[17]))
    return out


res = []
with ThreadPoolExecutor(max_workers=8) as ex:
    for f in as_completed([ex.submit(one, r) for r in sample]):
        x = f.result()
        if x:
            res.append(x)

print("样本", len(res))
for k in ("b365", "crown"):
    vals = [x for x in res if x.get(k) and x[k][0] is not None and x["total"]]
    match = sum(1 for x in vals if abs(x[k][0] - x["total"]) < 0.26)
    print("%s 全场盘口(n=%d) 与比分页吻合: %d = %.1f%%" % (k, len(vals), match, 100.0 * match / max(len(vals), 1)))
    print("   差值分布:", Counter(round((x[k][0] - x["total"]) * 4) / 4 for x in vals).most_common(8))
    semi = [x for x in res if x.get(k + "_semi") and x[k + "_semi"][0] is not None and x["total"]]
    smatch = sum(1 for x in semi if abs(x[k + "_semi"][0] - x["total"]) < 0.26)
    print("   半场组(n=%d) 与比分页吻合: %d = %.1f%%" % (len(semi), smatch, 100.0 * smatch / max(len(semi), 1)))

print("\n前 12 场明细:")
for x in res[:12]:
    print(x["sid"], "总盘=%.2f" % x["total"],
          "365=%.2f 水%.2f/%.2f" % (x["b365"][0], x["b365"][1], x["b365"][2]) if x.get("b365") else "",
          "皇冠=%.2f 水%.2f/%.2f" % (x["crown"][0], x["crown"][1], x["crown"][2]) if x.get("crown") else "")
