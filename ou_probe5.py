# -*- coding: utf-8 -*-
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from titan007_collector import fetch  # noqa: E402
from titan_water_collector import parse_rows  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

for sid, total in (("3092616", 3.5), ("3092304", 3.25), ("2908798", 2.75)):
    url = "https://live.titan007.com/jsData/%s/%s/%s.js" % (sid[:2], sid[2:4], sid)
    txt = fetch(url, "utf-8")
    print("=" * 40)
    print(sid, "比分页总盘=", total)
    for name in ("sOdds", "sOdds8"):
        rows = parse_rows(txt, name)
        if not rows:
            print(name, "无")
            continue
        r = rows[0]
        print(name, "首行 标签=%s len=%d" % (r[0], len(r)))
        for i, v in enumerate(r):
            if v not in ("", None):
                print("   [%02d] %r" % (i, v))
