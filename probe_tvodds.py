# -*- coding: utf-8 -*-
"""测试直播页亚盘实时接口 /phone/txt/football/tvodds/xx/yy/{sid}.txt"""
import sys, re
sys.path.insert(0, r"g:\bet")
from titan007_collector import fetch

js = fetch("https://live.titan007.com/scoreOddsNew.js", encoding="utf-8")
for m in re.finditer(r"staticUrl\s*=", js):
    print("staticUrl 定义:", re.sub(r"\s+", " ", js[m.start()-80:m.start()+160]))

sid = "3018834"
rev = lambda s: s[::-1]
path = f"/phone/txt/football/tvodds/{rev(sid[-2:])}/{rev(sid[-4:-2])}/{sid}.txt"
print("\npath:", path)

for host in ("https://live.titan007.com", "https://data.titan007.com", "http://live.titan007.com"):
    url = host + path
    try:
        txt = fetch(url, encoding="utf-8")
        print(f"\n### {url} len={len(txt)}")
        print(txt[:1500])
        break
    except Exception as e:
        print(f"### {url} ERR {e}")
