# -*- coding: utf-8 -*-
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from titan007_collector import fetch  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

for u in ["https://zq.titan007.com/scoreOdds.js?v=4",
          "https://live.titan007.com/scoreOddsNew.js?ver=5"]:
    try:
        t = fetch(u, "utf-8")
    except Exception as e:
        print(u, "ERR", repr(e))
        continue
    print("=" * 30)
    print(u, "len=", len(t))
    for kw in ("大小", "oneRowTd", "sOdds", "dxq", "DX"):
        idxs = [m.start() for m in re.finditer(kw, t)]
        print(" ", kw, len(idxs))
        for i in idxs[:3]:
            print("    ", re.sub(r"\s+", " ", t[max(0, i - 200):i + 350]))
