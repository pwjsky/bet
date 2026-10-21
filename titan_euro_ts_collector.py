# -*- coding: utf-8 -*-
"""欧赔公司级时间戳采集器

目的: 重建"赛前 X 小时"的赔率, 用于验证不同出单时点的效果。

数据源: http://1x2d.titan007.com/{sid}.js
  game 数组每段用 | 分隔:
    [2] 公司名  [3][4][5] 初盘  [10][11][12] 即时
    [20] 即时赔率的最后更新时间 '2026,10-1,19,10,11,00'
  MatchTime '2026,10-1,19,19,00,00' 为开赛时间(UTC)

输出 titan_data/euro_ts.json
  { sid: {"ko": "...", "b": [[oh,od,oa,ch,cd,ca,hours_before], ...]} }
  hours_before = 开赛时间 - 该公司即时赔率最后更新时间

用法:
  py titan_euro_ts_collector.py --limit 50
  py titan_euro_ts_collector.py --workers 16
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
DATA = os.path.join(BASE, "titan_data")
OUT = os.path.join(DATA, "euro_ts.json")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
HDR = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
       "Referer": "https://bf.titan007.com/"}


def fetch(url, retries=3):
    last = None
    for i in range(retries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=HDR),
                                          timeout=20, context=CTX).read().decode("utf-8", "ignore")
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(0.4 * (i + 1))
    raise last


def parse_t(s):
    """'2026,10-1,19,19,00,00' -> (年, 月, 日, 时, 分)"""
    p = s.split(",")
    return int(p[0]), int(p[1].split("-")[0]), int(p[2]), int(p[3]), int(p[4])


def to_h(y, mo, d, h, mi):
    return ((y * 12 + mo) * 31 + d) * 24 + h + mi / 60.0


def parse(txt):
    m = re.search(r'MatchTime="([^"]+)"', txt)
    g = re.search(r"var game=Array\((.*?)\);", txt, re.S)
    if not m or not g:
        return None
    try:
        kt = to_h(*parse_t(m.group(1)))
    except Exception:
        return None
    books = []
    for seg in re.findall(r'"([^"]*)"', g.group(1)):
        f = seg.split("|")
        if len(f) < 21:
            continue
        try:
            oh, od, oa = float(f[3]), float(f[4]), float(f[5])
            ch, cd, ca = float(f[10]), float(f[11]), float(f[12])
            ut = to_h(*parse_t(f[20]))
        except Exception:
            continue
        if min(oh, od, oa, ch, cd, ca) <= 1.0:
            continue
        books.append([oh, od, oa, ch, cd, ca, round(kt - ut, 2)])
    if len(books) < 5:
        return None
    return {"ko": m.group(1), "b": books}


def one(sid):
    try:
        return sid, parse(fetch("http://1x2d.titan007.com/%s.js" % sid))
    except Exception:
        return sid, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--nshard", type=int, default=1)
    a = ap.parse_args()

    euro = json.load(open(os.path.join(DATA, "euro.json"), encoding="utf-8"))
    store = {}
    if os.path.exists(a.out):
        try:
            store = json.load(open(a.out, encoding="utf-8"))
        except Exception:
            store = {}
    todo = [s for s in euro if s not in store and int(s) % a.nshard == a.shard]
    if a.limit:
        todo = todo[:a.limit]
    print("待采 %d 场 (已有 %d)" % (len(todo), len(store)), flush=True)

    ok = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, s): s for s in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            sid, d = fu.result()
            if d:
                store[sid] = d
                ok += 1
            else:
                fail += 1
            if i % 1000 == 0:
                json.dump(store, open(a.out, "w", encoding="utf-8"),
                          ensure_ascii=False, separators=(",", ":"))
                print("  %d/%d  ok=%d fail=%d  %.0fs" % (i, len(todo), ok, fail,
                                                         time.time() - t0), flush=True)
    json.dump(store, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("完成: 新增 %d, 失败 %d, 累计 %d, 用时 %.0fs" % (
        ok, fail, len(store), time.time() - t0))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
