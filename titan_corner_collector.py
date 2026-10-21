# -*- coding: utf-8 -*-
"""
角球数据采集器
==============
数据源:
  盘口  https://livestatic.titan007.com/jsData/corner/{前2}/{3-4}/{sid}.js
        var cOdds = [让分初盘线,初主水,初客水, 让分即时线,即主水,即客水,
                     总角球初盘线,初大,初小, 即时线,即大,即小]
  结果  https://live.titan007.com/detail/{sid}sb.htm
        teamTvStatisticData 第一段: "0,主角球,客角球,主%,客%"

实测: 约 44% 的已结束场次有角球盘; 角球结果几乎都有。
初盘线是赛前数据, 可用于回测; 即时线多数已滚球, 不可用于赛前下注。

用法:
  py titan_corner_collector.py --start 20260801
  py titan_corner_collector.py --start 20260801 --workers 16
"""
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "titan_data")
OUT = os.path.join(DATA_DIR, "corner.json")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def get(url, ref, retries=2):
    last = None
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": ref})
            with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            if k == 0:
                time.sleep(0.3)
    raise last


def num(x):
    x = x.strip()
    if not x:
        return None
    try:
        return float(x)
    except Exception:
        return None


def parse_js(t):
    m = re.search(r"var\s+cOdds\s*=\s*\[(.*?)\]\s*;", t, re.S)
    if not m:
        return None
    v = [num(x) for x in m.group(1).split(",")]
    if len(v) < 12:
        v += [None] * (12 - len(v))
    d = {"goal_line_o": v[0], "goal_h_o": v[1], "goal_a_o": v[2],
         "goal_line_c": v[3], "goal_h_c": v[4], "goal_a_c": v[5],
         "tot_line_o": v[6], "tot_over_o": v[7], "tot_under_o": v[8],
         "tot_line_c": v[9], "tot_over_c": v[10], "tot_under_c": v[11]}
    if d["tot_line_o"] is None and d["tot_line_c"] is None:
        return None
    return d


def parse_result(t):
    m = re.search(r'teamTvStatisticData\s*=\s*"([^"]*)"', t)
    if m and m.group(1):
        for seg in m.group(1).split("^"):
            f = seg.split(",")
            if len(f) >= 3 and f[0] == "0":
                try:
                    return int(f[1]), int(f[2])
                except Exception:
                    pass
    m = re.search(r"<span[^>]*>(\d+)</span><span>角球</span><span[^>]*>(\d+)</span>", t)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def grab(sid):
    base = "https://live.titan007.com/detail/%ssb.htm" % sid
    cu = "https://livestatic.titan007.com/jsData/corner/%s/%s/%s.js" % (sid[:2], sid[2:4], sid)
    try:
        t = get(cu, base)
    except Exception:
        return None
    if "cOdds" not in t:
        return None
    d = parse_js(t)
    if not d:
        return None
    d["sid"] = sid
    try:
        r = parse_result(get(base, base))
        if r:
            d["hc"], d["ac"] = r
    except Exception:
        pass
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20260601", help="起始日期")
    ap.add_argument("--end", default="99999999", help="结束日期")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    listings = json.load(open(os.path.join(DATA_DIR, "listings.json"), encoding="utf-8"))
    store = {}
    if os.path.exists(OUT):
        try:
            store = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            store = {}
    todo = [sid for sid, v in listings.items()
            if a.start <= (v.get("date") or "") <= a.end
            and v.get("score") not in (None, "-") and sid not in store]
    if a.limit:
        todo = todo[:a.limit]
    print("待采 %d 场, 已有 %d 场, 并发 %d" % (len(todo), len(store), a.workers))

    t0 = time.time()
    got = miss = 0
    buf = {}
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(grab, s): s for s in todo}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                r = f.result()
            except Exception:
                r = None
            if r:
                got += 1
                buf[r["sid"]] = r
            else:
                miss += 1
            if i % 500 == 0 or i == len(todo):
                el = time.time() - t0
                print("  [%d/%d] 命中 %d (%.1f%%) 用时 %.0fs 预计剩余 %.0fs"
                      % (i, len(todo), got, 100 * got / max(1, i), el,
                         el / i * (len(todo) - i)))
                if len(buf) >= 800:
                    store.update(buf)
                    json.dump(store, open(OUT, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=0)
                    buf.clear()
    store.update(buf)
    json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("完成: 新增 %d 场, 无角球盘 %d 场, 总库 %d 场 -> %s"
          % (got, miss, len(store), OUT))


if __name__ == "__main__":
    main()
