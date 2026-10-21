"""
批量亚盘预测与验证脚本
从 titan007 oldIndexall.aspx 获取的已完赛主流联赛比赛列表
对每场比赛抓取分析页，提取欧赔+亚盘(初盘/终盘)+相同盘口赢盘率
用模型预测亚盘方向，再用实际比分验证赢盘/输盘
"""
import urllib.request
import re
import json
import time
import ssl

# 已完赛主流联赛比赛列表 (id, 联赛, 主队, 客队, 全场比分, 半场比分)
MATCHES = [
    ("3041373", "澳超", "悉尼FC", "西悉尼流浪者", "0-0", "0-0"),
    ("3012536", "乌克超", "奥博隆", "维勒斯", "2-0", "1-0"),
    ("2944823", "中超", "河南队", "天津津门虎", "0-1", "0-1"),
    ("3047009", "沙特联", "卡达西亚", "艾卜哈", "2-1", "1-0"),
    ("3010445", "罗甲", "加拉茨钢铁", "FK米耶尔库雷亚丘克", "1-1", "1-0"),
    ("2998980", "塞尔超", "苏杜利察", "瑞德尼基", "3-0", "1-0"),
    ("3003176", "波兰超", "KS莫摩斯", "琴斯托霍瓦", "1-2", "0-0"),
    ("2997540", "克亚甲", "鲁达士", "里耶卡", "1-2", "0-1"),
    ("3019156", "德乙", "科特布斯", "纽伦堡", "1-1", "0-0"),
    ("3019159", "德乙", "荷尔斯泰因", "柏林赫塔", "0-0", "0-0"),
    ("3026753", "土超", "科鲁姆", "里泽体育", "2-1", "1-1"),
    ("2912292", "瑞典超", "布洛马波卡纳", "尤尔加登", "0-2", "0-1"),
    ("3010651", "奥甲", "维也纳快速", "哈特堡格", "3-1", "2-0"),
    ("2996170", "荷甲", "海伦芬", "SBV精英", "4-0", "1-0"),
    ("2997744", "法乙", "阿纳西", "南锡", "1-2", "0-1"),
    ("2997745", "法乙", "格勒诺布尔", "布洛涅", "0-2", "0-0"),
    ("2997746", "法乙", "甘冈", "波城", "1-2", "0-2"),
    ("2997747", "法乙", "拉瓦勒", "克莱蒙", "3-3", "0-2"),
    ("2997751", "法乙", "兰斯", "第戎", "4-2", "3-1"),
    ("3010442", "罗甲", "布加勒斯特迪纳摩", "博托沙尼", "2-0", "0-0"),
    ("2996504", "荷乙", "邓伯什", "奥斯", "2-1", "2-0"),
    ("2996505", "荷乙", "FC埃因霍温", "维特斯", "0-1", "0-1"),
    ("2996506", "荷乙", "赫尔蒙德", "布雷达", "0-2", "0-1"),
    ("2996507", "荷乙", "芬洛", "阿尔克马尔青年队", "4-4", "1-2"),
    ("3018834", "德甲", "法兰克福", "科隆", "1-0", "0-0"),
    ("3040774", "意乙", "维罗纳", "卡坦萨罗", "2-2", "1-1"),
    ("3014126", "西乙", "莱加内斯", "科尔多瓦", "0-1", "0-0"),
    ("3003175", "波兰超", "维德祖罗兹", "克拉科夫", "0-0", "0-0"),
    ("2993818", "意甲", "弗洛西诺尼", "萨索洛", "4-2", "3-2"),
    ("2995364", "法甲", "勒芒", "图卢兹", "0-3", "0-0"),
    ("3013724", "西甲", "拉科鲁尼亚", "莱万特", "1-1", "0-0"),
    ("3008274", "英冠", "伯恩利", "狼队", "1-2", "1-1"),
]

HANDICAP_MAP = {
    "平手": 0, "平/半": -0.25, "半球": -0.5, "半/一": -0.75,
    "一球": -1, "一/球半": -1.25, "球半": -1.5, "球半/两": -1.75,
    "两球": -2, "两/两球半": -2.25, "两球半": -2.5, "两球半/三": -2.75,
    "三球": -3,
}


def handicap_to_num(h):
    if not h:
        return None
    h = h.strip()
    if h.startswith("*"):
        h = h[1:]
    if h in HANDICAP_MAP:
        return HANDICAP_MAP[h]
    # 尝试解析如 "1.5" 或 "1/1.5"
    if "/" in h:
        parts = h.split("/")
        try:
            return -(float(parts[0]) + float(parts[1])) / 2
        except:
            return None
    try:
        return -float(h)
    except:
        return None


def fetch_page(url):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://live.titan007.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return ""


def extract_european_odds(html):
    """提取全场欧赔 主胜/平/客胜"""
    # 欧赔表格: 全场  1.7  3.9  3.52
    m = re.search(r'全场\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)', html)
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3))
    return None


def extract_asian_handicap(html):
    """提取亚盘 Crow* 初盘和终盘 (盘口, 主水, 客水)"""
    # 查找 Crow* 行的让球数据
    # 结构: Crow*  初 主水 盘口 客水  终 主水 盘口 客水
    # 从分析页中提取让球表格
    result = {}
    # 匹配让球盘数据行: 数字 盘口文字 数字 ... 数字 盘口文字 数字
    # 更稳妥: 找 "Crow*" 后面的数字和盘口
    lines = html.split("\n")
    for i, line in enumerate(lines):
        if "Crow*" in line or "Crow" in line:
            # 提取该行及附近的数字和盘口文字
            block = " ".join(lines[max(0,i-1):i+3])
            # 找所有盘口文字
            hcps = re.findall(r'(平手|平/半|半球|半/一|一球|一/球半|球半|球半/两|两球|两/两球半|两球半|两球半/三|三球)', block)
            nums = re.findall(r'\b([01]\.\d{2})\b', block)
            if len(hcps) >= 1 and len(nums) >= 4:
                result["open_handicap"] = hcps[0]
                result["open_home_water"] = float(nums[0])
                result["open_away_water"] = float(nums[1]) if len(nums) > 1 else None
                if len(hcps) >= 2:
                    result["live_handicap"] = hcps[1]
                    # 终盘水位在后面
                    if len(nums) >= 4:
                        result["live_home_water"] = float(nums[2])
                        result["live_away_water"] = float(nums[3])
                break
    return result if result else None


def extract_same_handicap(html):
    """提取相同盘口赢盘率"""
    # 相同盘路 亚让: 主队 赢/走/输 赢盘率  客队 赢/走/输 赢盘率
    # 查找 "相同盘路" 后的表格数据
    result = {}
    idx = html.find("相同盘路")
    if idx < 0:
        return None
    block = html[idx:idx+2000]
    # 提取赢盘率百分比
    rates = re.findall(r'(\d+\.?\d*)%', block)
    nums = re.findall(r'>(\d+)<', block)
    if len(rates) >= 4:
        result["home_total_wr"] = float(rates[0]) / 100
        result["home_home_wr"] = float(rates[1]) / 100 if len(rates) > 1 else None
        result["away_total_wr"] = float(rates[2]) / 100 if len(rates) > 2 else None
        result["away_away_wr"] = float(rates[3]) / 100 if len(rates) > 3 else None
    return result if result else None


def calc_handicap_result(home_goals, away_goals, handicap_num):
    """
    计算亚盘结果
    handicap_num: 主队让球数(负数), 如半球=-0.5
    返回: "主赢盘" / "客赢盘" / "走水"
    """
    if handicap_num is None:
        return None
    # 让球后比分
    adjusted_home = home_goals + handicap_num  # handicap_num 是负数
    diff = adjusted_home - away_goals
    if diff > 0:
        return "主赢盘"
    elif diff < 0:
        return "客赢盘"
    else:
        return "走水"


def predict_asian(odds, ah, same_hc):
    """
    亚盘预测
    返回: "主" (上盘) / "客" (下盘) / "中"
    """
    score = 0
    reasons = []

    # 1. 水位变化
    if ah and "live_home_water" in ah and "open_home_water" in ah:
        dh = ah["live_home_water"] - ah["open_home_water"]
        if dh < -0.03:
            score += 1
            reasons.append("主水大降")
        elif dh < 0:
            score += 0.5
            reasons.append("主水小降")
        elif dh > 0.03:
            score -= 1
            reasons.append("主水大升")
        elif dh > 0:
            score -= 0.5
            reasons.append("主水小升")

    # 2. 盘口升降
    if ah and "live_handicap" in ah and "open_handicap" in ah:
        lo = handicap_to_num(ah["open_handicap"])
        ll = handicap_to_num(ah["live_handicap"])
        if lo is not None and ll is not None:
            if ll < lo:  # 升盘(对主队更有信心)
                score += 1
                reasons.append("升盘")
            elif ll > lo:
                score -= 1
                reasons.append("降盘")

    # 3. 欧赔隐含概率
    if odds:
        ph = 1 / odds[0]
        pd = 1 / odds[1]
        pa = 1 / odds[2]
        tot = ph + pd + pa
        ph /= tot
        pa /= tot
        if ph - pa > 0.15:
            score += 1
            reasons.append(f"欧赔主胜({ph*100:.0f}%)")
        elif pa - ph > 0.15:
            score -= 1
            reasons.append(f"欧赔客胜({pa*100:.0f}%)")

    # 4. 相同盘口赢盘率
    if same_hc and "home_home_wr" in same_hc and "away_away_wr" in same_hc:
        hw = same_hc["home_home_wr"]
        aw = same_hc["away_away_wr"]
        if hw - aw > 0.1:
            score += 0.5
            reasons.append(f"同盘主优({hw*100:.0f}%>{aw*100:.0f}%)")
        elif aw - hw > 0.1:
            score -= 0.5
            reasons.append(f"同盘客优({aw*100:.0f}%>{hw*100:.0f}%)")

    if score >= 1:
        return "主", score, reasons
    elif score <= -1:
        return "客", score, reasons
    else:
        return "中", score, reasons


def main():
    print("=" * 90)
    print(f"  亚盘批量预测验证  共 {len(MATCHES)} 场主流联赛完赛比赛")
    print("=" * 90)
    print(f"{'联赛':<8}{'主队':<14}{'客队':<14}{'比分':<8}{'盘口':<8}{'预测':<6}{'实际':<8}{'命中':<6}")
    print("-" * 90)

    total = 0
    hit = 0
    miss = 0
    push = 0
    skipped = 0
    results_detail = []

    for mid, league, home, away, score, half in MATCHES:
        url = f"https://zq.titan007.com/analysis/{mid}sb.htm"
        html = fetch_page(url)
        if not html:
            print(f"{league:<8}{home:<14}{away:<14}{score:<8}{'抓取失败':<8}")
            skipped += 1
            time.sleep(0.5)
            continue

        odds = extract_european_odds(html)
        ah = extract_asian_handicap(html)
        same_hc = extract_same_handicap(html)

        if not ah or "live_handicap" not in ah:
            print(f"{league:<8}{home:<14}{away:<14}{score:<8}{'无亚盘':<8}")
            skipped += 1
            time.sleep(0.5)
            continue

        hcp = ah.get("live_handicap", ah.get("open_handicap", ""))
        hcp_num = handicap_to_num(hcp)

        # 解析比分
        sg = score.split("-")
        hg, ag = int(sg[0]), int(sg[1])

        # 预测
        pred, score_val, reasons = predict_asian(odds, ah, same_hc)

        # 实际结果
        actual = calc_handicap_result(hg, ag, hcp_num)

        # 判断命中
        is_hit = None
        if actual == "走水":
            is_hit = "走水"
            push += 1
        elif pred == "主" and actual == "主赢盘":
            is_hit = "✓"
            hit += 1
        elif pred == "客" and actual == "客赢盘":
            is_hit = "✓"
            hit += 1
        elif pred == "中":
            is_hit = "中性"
            push += 1
        else:
            is_hit = "✗"
            miss += 1

        total += 1
        print(f"{league:<8}{home:<14}{away:<14}{score:<8}{hcp:<8}{pred:<6}{actual:<8}{is_hit:<6}")
        results_detail.append({
            "id": mid, "league": league, "home": home, "away": away,
            "score": score, "handicap": hcp, "pred": pred, "actual": actual,
            "hit": is_hit, "score_val": score_val, "reasons": reasons
        })
        time.sleep(0.5)

    # 统计
    print("-" * 90)
    valid = hit + miss
    print(f"\n  统计: 总计 {total} 场 | 命中 {hit} | 未中 {miss} | 走水/中性 {push} | 跳过 {skipped}")
    if valid > 0:
        print(f"  胜率(不含走水/中性): {hit}/{valid} = {hit/valid*100:.1f}%")
        print(f"  胜率(含走水/中性): {hit}/{total} = {hit/total*100:.1f}%")

    # 按联赛统计
    print(f"\n  按联赛统计:")
    by_league = {}
    for r in results_detail:
        lg = r["league"]
        if lg not in by_league:
            by_league[lg] = {"h": 0, "m": 0, "p": 0}
        if r["hit"] == "✓":
            by_league[lg]["h"] += 1
        elif r["hit"] == "✗":
            by_league[lg]["m"] += 1
        else:
            by_league[lg]["p"] += 1
    for lg, s in sorted(by_league.items(), key=lambda x: -(x[1]["h"]+x[1]["m"])):
        v = s["h"] + s["m"]
        wr = s["h"] / v * 100 if v else 0
        print(f"    {lg:<8} 命中{s['h']} 未中{s['m']} 走/中{s['p']}  胜率{wr:.0f}%")

    print("\n" + "=" * 90)


if __name__ == "__main__":
    main()
