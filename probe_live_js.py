# -*- coding: utf-8 -*-
import sys, re
sys.path.insert(0, r"g:\bet")
from titan007_collector import fetch

js = fetch("https://live.titan007.com/scoreOddsNew.js", encoding="utf-8")
print("len", len(js))
print("\n=== ajax / url ===")
for u in dict.fromkeys(re.findall(r"['\"]([^'\"]*(?:aspx|ashx|\.js|txt|api)[^'\"]*)['\"]", js)):
    print(" ", u)
print("\n=== odds 函数名 ===")
for m in dict.fromkeys(re.findall(r"function\s+(\w*[Oo]dds\w*)\s*\(", js)):
    print(" ", m)

html = fetch("https://live.titan007.com/detail/3018834sb.htm", encoding="utf-8")
i = html.find("oddsDiv")
print("\n=== oddsDiv 上下文 ===")
print(re.sub(r"\s+", " ", html[max(0, i-800):i+800]))
