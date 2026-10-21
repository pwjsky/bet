# -*- coding: utf-8 -*-
"""验证 tvodds 亚盘接口: 抽 12 场, 对比 company8 全场盘口与比分页 listed。"""
import sys, json, time, random
sys.path.insert(0, r"g:\bet")
from titan007_collector import fetch

listings = json.load(open(r"g:\bet\titan_data\listings.json", encoding="utf-8"))
pool = [r for r in listings.values() if r.get("hcp_listed") is not None]
random.seed(3)
sample = random.sample(pool, 12)

rev = lambda s: s[::-1]


def tvodds(sid):
    path = f"/phone/txt/football/tvodds/{rev(sid[-2:])}/{rev(sid[-4:-2])}/{sid}.txt"
    return fetch("https://livestatic.titan007.com" + path, encoding="utf-8")


for rec in sample:
    sid = rec["id"]
    try:
        txt = tvodds(sid)
    except Exception as e:
        print(sid, "ERR", e); continue
    rows = [x.split("^") for x in txt.strip().split("!") if x.count("^") >= 6]
    out = []
    for f in rows:
        if len(f) >= 7 and f[1] == "1" and f[2] == "0":
            out.append((f[0], f[3], f[4], f[5], f[6]))
    print(f"{sid} listed={rec['hcp_listed']}({rec.get('hdp_val')}) score={rec['score']} "
          f"全场亚盘: {out}")
    time.sleep(0.2)
