# -*- coding: utf-8 -*-
"""
亚盘水位采集器
==============
数据源: https://live.titan007.com/jsData/{sid前2位}/{sid第3-4位}/{sid}.js

该文件是分析页 scoreOdds.js 通过 LoadLiveFile() 加载的本场盘口时间序列。
结构 (scoreOdds.js 中 oneRowTd 的索引):
  [0] 时间标签 ('早餐'=开盘, '未开场'=赛前, '45'/'中场'/'76'/'93'=比赛中)
  [1][2] 比分
  [3,4,5]   半场 开盘  主水/盘口/客水
  [6,7,8]   半场 即时
  [9,10,11] 全场 开盘  主水/盘口/客水
  [12,13,14]全场 即时  <-- 赛前最后一次即终盘
  [15..20]  半场大小球
  [21..26]  全场大小球
  [27..32]  半场欧赔
  [33..38]  全场欧赔
  [39]      状态位

sOdds = Crown, sOdds8 = Bet365。其它公司不在此文件。

用法:
  py titan_water_collector.py --limit 200
  py titan_water_collector.py
"""
import argparse
import ast
import json
import os
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "titan_data")
OUT = os.path.join(DATA_DIR, "water.json")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def fetch(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Referer": "https://zq.titan007.com/analysis/%s.htm" % url.split("/")[-1][:-3],
            })
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
    raise last


def find_array(txt, name):
    i = txt.find("var " + name)
    if i < 0:
        return None
    j = txt.find("[", i)
    if j < 0:
        return None
    depth = 0
    for k in range(j, len(txt)):
        c = txt[k]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return txt[j:k + 1]
    return None


def parse_rows(txt, name):
    s = find_array(txt, name)
    if not s:
        return []
    while ",," in s:                 # JS 稀疏数组 [,,] 补成空串
        s = s.replace(",,", ",''")
    try:
        return ast.literal_eval(s)
    except Exception:
        return []


def num(v):
    try:
        return float(v)
    except Exception:
        return None


def wv(v):
    """水位合法性: 0.5~1.5; 8.33/0.01 这类是封盘异常值"""
    x = num(v)
    return x if x is not None and 0.5 <= x <= 1.5 else None


def hp(v):
    """盘口合法性: 可以是 0(平手)和负数"""
    x = num(v)
    return x if x is not None and -10 <= x <= 10 else None


def pick(rows):
    if not rows:
        return None
    pre = [r for r in rows if len(r) > 14 and r[0] in ("早餐", "未开场")]
    if not pre:
        pre = [r for r in rows if len(r) > 14 and r[12] not in ("", None)]
    if not pre:
        return None
    first, last = pre[0], pre[-1]
    out = {
        "hcp_open": hp(first[10]), "wo_h_open": wv(first[9]), "wo_a_open": wv(first[11]),
        "hcp_close": hp(last[10]), "wo_h_close": wv(last[9]), "wo_a_close": wv(last[11]),
        "n_snap": len(rows), "labels": [r[0] for r in rows][:8],
    }
    if out["hcp_close"] is None or out["wo_h_close"] is None or out["wo_a_close"] is None:
        return None
    return out


def one(sid):
    url = "https://live.titan007.com/jsData/%s/%s/%s.js" % (sid[:2], sid[2:4], sid)
    txt = fetch(url)
    rec = {"sid": sid}
    for name, key in (("sOdds", "crown"), ("sOdds8", "bet365")):
        p = pick(parse_rows(txt, name))
        if p:
            rec[key] = p
    return rec if len(rec) > 1 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--shard", type=int, default=0, help="分片序号, 从 0 开始")
    ap.add_argument("--nshard", type=int, default=1, help="分片总数")
    ap.add_argument("--out", help="分片输出文件, 不填则写 titan_data/water.json")
    a = ap.parse_args()

    euro = json.load(open(os.path.join(DATA_DIR, "euro.json"), encoding="utf-8"))
    ids = sorted(euro.keys()) if isinstance(euro, dict) else [r["id"] for r in euro]
    if a.limit:
        ids = ids[:a.limit]

    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            old = {}
    todo = [i for i in ids if i not in old]
    if a.nshard > 1:
        todo = todo[a.shard::a.nshard]
    target = a.out or OUT
    if a.out:
        data = json.load(open(a.out, encoding="utf-8")) if os.path.exists(a.out) else {}
        todo = [i for i in todo if i not in data]
    else:
        data = old
    print("待采 %d 场 (已有 %d)%s"
          % (len(todo), len(old), "" if a.nshard == 1 else " 分片 %d/%d" % (a.shard, a.nshard)))

    t0 = time.time()
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, i): i for i in todo}
        for n, f in enumerate(as_completed(futs), 1):
            try:
                r = f.result()
                if r:
                    data[r["sid"]] = r
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
            if n % 500 == 0:
                json.dump(data, open(target + ".tmp", "w", encoding="utf-8"),
                          ensure_ascii=False)
                os.replace(target + ".tmp", target)
                rate = n / max(time.time() - t0, 1e-6)
                print("  [%d/%d] ok=%d fail=%d %.2f/s 剩余%.1f分"
                      % (n, len(todo), ok, fail, rate, (len(todo) - n) / max(rate, 1e-6) / 60))

    json.dump(data, open(target + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(target + ".tmp", target)
    print("完成 ok=%d fail=%d 总计 %d 场, 用时 %.1f 分"
          % (ok, fail, len(data), (time.time() - t0) / 60))


if __name__ == "__main__":
    main()
