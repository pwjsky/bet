# -*- coding: utf-8 -*-
"""
titan007 欧赔采集器
====================
数据源: http://1x2d.titan007.com/{sid}.js
        var game = Array("公司ID|记录ID|公司名|初主|初平|初客|初主率|初平率|初客率|初返还|
                          即主|即平|即客|即主率|即平率|即客率|即返还|...|更新时间|简称|...")

输出字段与 titan_data/euro.json 保持一致(口径不能改, 否则模型分布会漂):
  n_euro       开盘公司数
  odds_open    各公司初盘三赔的逐列中位数
  odds_close   各公司即时三赔的逐列中位数
  p_open/p_close  中位数赔率去水后的主胜概率
  p_std_close  各公司即时去水主胜概率的标准差(分歧度)
  rebate_close 各公司即时返还率(%)的中位数

用法:
  py titan_euro_collector.py --verify 3
  py titan_euro_collector.py --dates 20260921-20260930
  py titan_euro_collector.py --dates 20260921,20260922
  py titan_euro_collector.py --dates 20260921-20260930 --workers 6
"""
import argparse
import json
import math
import os
import re
import ssl
import statistics
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "titan_data")
LISTINGS = os.path.join(DATA_DIR, "listings.json")
EURO = os.path.join(DATA_DIR, "euro.json")

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://bf.titan007.com/",
}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

_lock = threading.Lock()


def fetch(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                raw = r.read()
            for enc in ("utf-8", "gbk", "gb18030"):
                try:
                    return raw.decode(enc)
                except Exception:
                    continue
            return raw.decode("utf-8", errors="ignore")
        except Exception as e:
            last = e
            time.sleep(0.8 * (attempt + 1))
    raise last


def to_float(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except Exception:
        return None


def devig(odds):
    inv = [1.0 / v for v in odds]
    s = sum(inv)
    return [v / s for v in inv]


def parse_js(txt):
    m = re.search(r"var\s+game\s*=\s*Array\((.*?)\)\s*;", txt, re.S)
    if not m:
        return None
    items = re.findall(r'"([^"]*)"', m.group(1))
    opens, closes = [], []
    for it in items:
        f = it.split("|")
        if len(f) < 17:
            continue
        o = [to_float(f[3]), to_float(f[4]), to_float(f[5])]
        c = [to_float(f[10]), to_float(f[11]), to_float(f[12])]
        ro = to_float(f[9])
        rc = to_float(f[16])
        if None not in o:
            opens.append(o)
        if None not in c:
            closes.append(c)
    if not opens or not closes:
        return None

    med_o = [statistics.median(x[i] for x in opens) for i in range(3)]
    med_c = [statistics.median(x[i] for x in closes) for i in range(3)]
    po, pc = devig(med_o), devig(med_c)
    pc_each = [devig(x)[0] for x in closes]
    rebates = [to_float(f) for f in
               [it.split("|")[16] for it in items if len(it.split("|")) >= 17]]
    rebates = [x for x in rebates if x]
    return {
        "n_euro": len(closes),
        "odds_open": [round(x, 4) for x in med_o],
        "odds_close": [round(x, 4) for x in med_c],
        "p_open": po[0],
        "p_close": pc[0],
        "p_move": pc[0] - po[0],
        "p_std_open": statistics.pstdev([devig(x)[0] for x in opens]) if len(opens) > 1 else 0.0,
        "p_std_close": statistics.pstdev(pc_each) if len(pc_each) > 1 else 0.0,
        "rebate_open": 0.0,
        "rebate_close": statistics.median(rebates) if rebates else 0.0,
    }


def expand_dates(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            from datetime import date, timedelta
            d0 = date(int(a[:4]), int(a[4:6]), int(a[6:]))
            d1 = date(int(b[:4]), int(b[4:6]), int(b[6:]))
            while d0 <= d1:
                out.append(d0.strftime("%Y%m%d"))
                d0 += timedelta(days=1)
        elif part:
            out.append(part)
    return out


def cmd_verify(n):
    euro = json.load(open(EURO, encoding="utf-8"))
    sids = list(euro)[:n]
    for sid in sids:
        old = euro[sid]
        new = parse_js(fetch("http://1x2d.titan007.com/%s.js" % sid))
        print("=" * 40, sid)
        for k in ("n_euro", "odds_open", "odds_close", "p_open", "p_close",
                  "p_std_close", "rebate_close"):
            print("  %-12s old=%-22s new=%s" % (k, old.get(k), new.get(k) if new else None))


def cmd_collect(dates, workers, shard=0, nshard=1, out=None):
    listings = json.load(open(LISTINGS, encoding="utf-8"))
    base = json.load(open(EURO, encoding="utf-8")) if os.path.exists(EURO) else {}
    todo = []
    for sid, r in listings.items():
        if r.get("date") in dates and r.get("hcp_listed") is not None and sid not in base:
            todo.append((sid, r["date"]))
    if nshard > 1:
        todo = todo[shard::nshard]
    target = out or EURO
    euro = {}
    if out:
        if os.path.exists(out):
            euro = json.load(open(out, encoding="utf-8"))
        todo = [it for it in todo if it[0] not in euro]
    else:
        euro = base
    print("待采 %d 场 (已有 %d)%s"
          % (len(todo), len(base), "" if nshard == 1 else " 分片 %d/%d" % (shard, nshard)))

    ok = fail = 0
    t0 = time.time()

    def work(item):
        sid, d = item
        rec = parse_js(fetch("http://1x2d.titan007.com/%s.js" % sid))
        if rec is None:
            raise ValueError("no game array")
        rec["id"] = sid
        rec["date"] = d
        return sid, rec

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, it): it for it in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            sid, d = futs[fut]
            try:
                s, rec = fut.result()
                with _lock:
                    euro[s] = rec
                    ok += 1
            except Exception as e:
                fail += 1
                if fail <= 5:
                    print("  失败 %s: %s" % (sid, e))
            if i % 200 == 0:
                with _lock:
                    json.dump(euro, open(target + ".tmp", "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1)
                    os.replace(target + ".tmp", target)
                el = time.time() - t0
                print("[%d/%d] ok=%d fail=%d %.2fs/场 剩余%.1f分"
                      % (i, len(todo), ok, fail, el / i, (len(todo) - i) * el / i / 60))

    json.dump(euro, open(target + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(target + ".tmp", target)
    print("完成 ok=%d fail=%d 总计 %d 场, 用时 %.1f 分"
          % (ok, fail, len(euro), (time.time() - t0) / 60))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--shard", type=int, default=0, help="分片序号, 从 0 开始")
    ap.add_argument("--nshard", type=int, default=1, help="分片总数")
    ap.add_argument("--out", help="分片输出文件, 不填则写 titan_data/euro.json")
    ap.add_argument("--verify", type=int, default=0)
    a = ap.parse_args()
    if a.verify:
        cmd_verify(a.verify)
    elif a.dates:
        cmd_collect(set(expand_dates(a.dates)), a.workers, a.shard, a.nshard, a.out)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
