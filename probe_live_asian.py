# -*- coding: utf-8 -*-
"""探测直播详情页里的亚盘数据入口。"""
import sys, re
sys.path.insert(0, r"g:\bet")
from titan007_collector import fetch

sid = "3018834"
html = fetch(f"https://live.titan007.com/detail/{sid}sb.htm", encoding="utf-8")
print("len", len(html))

print("\n=== iframe ===")
for m in dict.fromkeys(re.findall(r"<iframe[^>]*src=['\"]([^'\"]+)", html, re.I)):
    print(" ", m)

print("\n=== script src ===")
for m in dict.fromkeys(re.findall(r"<script[^>]*src=['\"]([^'\"]+)", html, re.I)):
    print(" ", m)

print("\n=== 含 Odds/asia/handicap 的链接 ===")
for m in dict.fromkeys(re.findall(r"['\"]([^'\"]*(?:Odds|odds|Asia|asia|handicap|Handicap)[^'\"]*)['\"]", html)):
    print(" ", m)

print("\n=== 关键词次数 ===")
for kw in ("亚盘", "亚指", "让球", "盘口", "初盘"):
    print(f"  {kw}: {html.count(kw)}")

print("\n=== '亚盘' 上下文 ===")
for m in re.finditer("亚盘|亚指", html):
    print(" ---", re.sub(r"\s+", " ", html[max(0, m.start()-300):m.start()+300])[:600])
