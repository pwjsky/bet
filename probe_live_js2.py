# -*- coding: utf-8 -*-
import sys, re
sys.path.insert(0, r"g:\bet")
from titan007_collector import fetch

js = fetch("https://live.titan007.com/scoreOddsNew.js", encoding="utf-8")
for fn in ("getOddsShowData", "initOddsData", "getShowOdds", "updateOdds", "refreshOdds"):
    i = js.find("function " + fn)
    if i < 0:
        i = js.find(fn)
    print(f"\n===== {fn} @ {i} =====")
    print(re.sub(r"\s+", " ", js[i:i + 1800]))
