"""
足球比赛通用数据模型与胜率分析
数据源: titan007.com 比赛详情页 + 分析页 + 球队历年成绩页
比赛: 法兰克福 vs 科隆 (德甲 2026-2027 第6轮, 2026-10-17)

数据模型为通用设计，可复用于任意 titan007 比赛。
胜率分析融合: 本赛季排名、上赛季排名、近期状态、交锋往绩、盘口隐含概率、
              主客场、攻防能力、相同盘口赢盘率、半场能力 等维度。
"""

from dataclasses import dataclass, field
from typing import List, Optional
import math


# ============================================================
# 一、通用数据模型层
# ============================================================

@dataclass
class MatchInfo:
    """比赛基本信息"""
    home_team: str
    away_team: str
    league: str
    round_no: str
    match_time: str
    venue: str
    weather: str
    temperature: str


@dataclass
class EuropeanOdds:
    """欧赔(胜平负)"""
    home_win: float       # 主胜赔率
    draw: float           # 平局赔率
    away_win: float       # 客胜赔率
    handicap_home: float  # 让球(-1)主胜
    handicap_draw: float  # 让球(-1)平
    handicap_away: float  # 让球(-1)客胜


@dataclass
class AsianHandicap:
    """亚盘(让球) 半场/全场 开盘/即时"""
    half_open_handicap: str   # 如 "平/半"
    half_open_handicap_num: float  # 盘口数值 -0.25
    half_open_home_water: float
    half_open_away_water: float
    half_live_home_water: float
    half_live_handicap: str
    half_live_away_water: float
    full_open_home_water: float
    full_open_handicap: str
    full_open_away_water: float
    full_live_home_water: float
    full_live_handicap: str
    full_live_away_water: float


@dataclass
class TotalGoals:
    """大小球"""
    half_open_line: float
    half_open_home_water: float
    half_open_away_water: float
    half_live_line: float
    half_live_home_water: float
    half_live_away_water: float
    full_open_line: float
    full_open_home_water: float
    full_open_away_water: float
    full_live_line: float
    full_live_home_water: float
    full_live_away_water: float


@dataclass
class CornerOdds:
    """角球盘"""
    handicap_home_water: float
    handicap_line: float
    handicap_away_water: float
    total_line: float
    total_home_water: float
    total_away_water: float


@dataclass
class OddsSet:
    european: EuropeanOdds
    asian: AsianHandicap
    total_goals: TotalGoals
    corners: CornerOdds


@dataclass
class StandingRecord:
    """单维度战绩(总/主/客)"""
    played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int
    goal_diff: int
    points: int
    rank: Optional[int] = None
    win_rate: Optional[float] = None


@dataclass
class TeamStanding:
    """球队联赛排名(全场+半场)"""
    overall: StandingRecord
    home: StandingRecord
    away: StandingRecord
    # 半场统计
    half_overall: Optional[StandingRecord] = None
    half_home: Optional[StandingRecord] = None
    half_away: Optional[StandingRecord] = None


@dataclass
class SeasonRecord:
    """历史赛季战绩(用于参考上赛季等)"""
    season: str          # 如 "2025-2026"
    league: str          # 如 "德甲"
    overall: StandingRecord
    home: StandingRecord
    away: StandingRecord


@dataclass
class TeamStats:
    """技统数据 近3场/近10场"""
    goals_scored_3: float
    goals_scored_10: float
    goals_conceded_3: float
    goals_conceded_10: float
    shots_against_3: float
    shots_against_10: float
    corners_3: float
    corners_10: float
    yellow_cards_3: float
    yellow_cards_10: float
    fouls_3: float
    fouls_10: float
    possession_3: float
    possession_10: float


@dataclass
class GoalProbPeriod:
    """单时间段进失球概率"""
    period: str
    goal_pct: float
    concede_pct: float


@dataclass
class H2HRecord:
    """交锋记录"""
    date: str
    competition: str
    home_team: str
    score: str
    half_score: str
    corners: str
    away_team: str
    handicap: str
    result: str       # 胜/平/负 (从主队视角)
    handicap_result: str  # 赢/输/走
    goals_result: str     # 大/小/走


@dataclass
class FormRecord:
    """近期战绩"""
    date: str
    competition: str
    home_team: str
    score: str
    half_score: str
    away_team: str
    handicap: str
    result: str
    handicap_result: str
    goals_result: str


@dataclass
class HandicapTrend:
    """盘路走势"""
    played: int
    win: int
    draw: int
    loss: int
    win_rate: float
    over_goals: int
    over_rate: float
    under_goals: int
    under_rate: float


@dataclass
class SameHandicapRecord:
    """相同盘口历史"""
    handicap: str
    total_win: int
    total_draw: int
    total_loss: int
    total_win_rate: float
    home_win: int
    home_loss: int
    home_win_rate: float
    away_win: int
    away_loss: int
    away_win_rate: float


@dataclass
class Player:
    number: str
    name: str
    position: str
    rating: Optional[float] = None


@dataclass
class Injury:
    name: str
    position: str
    reason: str


@dataclass
class TeamLineup:
    formation: str
    coach: str
    starters: List[Player] = field(default_factory=list)
    injuries: List[Injury] = field(default_factory=list)
    avg_rating_last: Optional[float] = None


@dataclass
class TeamData:
    """单支球队的全部数据"""
    name: str
    standing: TeamStanding
    stats: TeamStats
    goal_probs: List[GoalProbPeriod]
    form: List[FormRecord]
    handicap_trend_full: HandicapTrend
    handicap_trend_half: HandicapTrend
    same_handicap: SameHandicapRecord
    lineup: TeamLineup
    recent_ratings: List[float] = field(default_factory=list)
    historical_seasons: List[SeasonRecord] = field(default_factory=list)


@dataclass
class MatchData:
    """聚合所有维度的顶层通用模型"""
    match: MatchInfo
    odds: OddsSet
    home_team: TeamData
    away_team: TeamData
    h2h: List[H2HRecord]
    pre_match_brief: str = ""


# ============================================================
# 二、数据填充层 —— 本场比赛 (法兰克福 vs 科隆)
# ============================================================

def build_match_data() -> MatchData:
    match = MatchInfo(
        home_team="法兰克福",
        away_team="科隆",
        league="德甲",
        round_no="第6轮",
        match_time="2026-10-17 02:30",
        venue="德意志银行公园球场",
        weather="间中有云",
        temperature="14℃～15℃",
    )

    # --- 赔率 ---
    odds = OddsSet(
        european=EuropeanOdds(
            home_win=1.7, draw=3.9, away_win=3.52,
            handicap_home=2.97, handicap_draw=3.75, handicap_away=1.9,
        ),
        asian=AsianHandicap(
            half_open_home_water=1.07, half_open_handicap="平/半", half_open_handicap_num=-0.25,
            half_open_away_water=0.81,
            half_live_home_water=1.04, half_live_handicap="平/半", half_live_away_water=0.84,
            full_open_home_water=0.98, full_open_handicap="半球", full_open_away_water=0.90,
            full_live_home_water=0.93, full_live_handicap="半球", full_live_away_water=0.95,
        ),
        total_goals=TotalGoals(
            half_open_line=1.5, half_open_home_water=1.05, half_open_away_water=0.83,
            half_live_line=1.5, half_live_home_water=0.96, half_live_away_water=0.92,
            full_open_line=3.5, full_open_home_water=1.00, full_open_away_water=0.88,
            full_live_line=3.5, full_live_home_water=0.90, full_live_away_water=0.98,
        ),
        corners=CornerOdds(
            handicap_home_water=0.9, handicap_line=1, handicap_away_water=0.9,
            total_line=10, total_home_water=0.95, total_away_water=0.85,
        ),
    )

    # --- 法兰克福 本赛季排名 ---
    frankfurt_standing = TeamStanding(
        overall=StandingRecord(5, 1, 2, 2, 9, 16, -7, 5, rank=14, win_rate=0.20),
        home=StandingRecord(2, 0, 1, 1, 3, 6, -3, 1, rank=17, win_rate=0.0),
        away=StandingRecord(3, 1, 1, 1, 6, 10, -4, 4, rank=7, win_rate=0.333),
        half_overall=StandingRecord(5, 4, 0, 1, 7, 6, 1, 12, rank=1, win_rate=0.80),
        half_home=StandingRecord(2, 2, 0, 0, 3, 1, 2, 6, rank=7, win_rate=1.0),
        half_away=StandingRecord(3, 2, 0, 1, 4, 5, -1, 6, rank=2, win_rate=0.667),
    )

    # --- 法兰克福 上赛季 (2025-2026 德甲) ---
    frankfurt_hist = [
        SeasonRecord("2025-2026", "德甲",
            StandingRecord(34, 11, 11, 12, 61, 65, -4, 44, rank=8, win_rate=0.324),
            StandingRecord(17, 7, 4, 6, 29, 27, 2, 25, rank=9, win_rate=0.412),
            StandingRecord(17, 4, 7, 6, 32, 38, -6, 19, rank=8, win_rate=0.235),
        ),
        SeasonRecord("2024-2025", "德甲",
            StandingRecord(34, 17, 9, 8, 68, 46, 22, 60, rank=3, win_rate=0.50),
            StandingRecord(17, 10, 4, 3, 41, 22, 19, 34, rank=3, win_rate=0.588),
            StandingRecord(17, 7, 5, 5, 27, 24, 3, 26, rank=6, win_rate=0.412),
        ),
    ]

    frankfurt_stats = TeamStats(
        goals_scored_3=2, goals_scored_10=3.1,
        goals_conceded_3=2.7, goals_conceded_10=2.4,
        shots_against_3=14.7, shots_against_10=13.2,
        corners_3=5.7, corners_10=6.8,
        yellow_cards_3=2.3, yellow_cards_10=2,
        fouls_3=12.5, fouls_10=9.8,
        possession_3=50.3, possession_10=55.5,
    )

    frankfurt_goal_probs = [
        GoalProbPeriod("1~15", 13, 14), GoalProbPeriod("16~30", 14, 7),
        GoalProbPeriod("31~45", 21, 16), GoalProbPeriod("46~60", 16, 18),
        GoalProbPeriod("61~75", 16, 16), GoalProbPeriod("76~90", 16, 20),
        GoalProbPeriod("90+", 1, 5),
    ]

    frankfurt_form = [
        FormRecord("26-10-11", "德甲", "RB莱比锡", "6-0", "4-0", "法兰克福", "一球", "负", "输", "大"),
        FormRecord("26-09-19", "德甲", "法兰克福", "2-2", "2-1", "弗赖堡", "平手", "平", "走", "大"),
        FormRecord("26-09-12", "德甲", "美因茨05", "1-3", "0-2", "法兰克福", "半/一", "胜", "赢", "大"),
        FormRecord("26-09-06", "德甲", "法兰克福", "1-4", "1-0", "奥斯堡", "半球", "负", "输", "大"),
        FormRecord("26-08-29", "德甲", "柏林联", "3-3", "1-2", "法兰克福", "平手", "平", "走", "大"),
        FormRecord("26-08-22", "德国杯", "通尼斯", "0-11", "0-10", "法兰克福", "*六球", "胜", "赢", "大"),
    ]

    frankfurt_trend_full = HandicapTrend(5, 2, 0, 3, 0.40, 5, 1.0, 0, 0.0)
    frankfurt_trend_half = HandicapTrend(5, 4, 0, 1, 0.80, 4, 0.80, 1, 0.20)
    frankfurt_same_hc = SameHandicapRecord("半球", 61, 0, 73, 0.455, 49, 54, 0.476, 12, 19, 0.387)

    frankfurt_lineup = TeamLineup(
        formation="4-4-2", coach="阿道夫.赫特",
        starters=[
            Player("1", "阿图博卢", "守门员", 5.4), Player("34", "纳曼迪柯林斯", "中卫", 6.0),
            Player("4", "科赫", "中卫", 5.6), Player("3", "布拉西尔", "中卫", 6.5),
            Player("7", "卡纳福", "右边锋", 6.5), Player("25", "奥涅迪卡", "后腰", 5.2),
            Player("15", "阿塞科", "后腰", 6.1), Player("26", "小杉启太", "左后卫", 6.5),
            Player("20", "堂安律", "右边锋", 6.7), Player("42", "乌尊", "前腰", 8.0),
            Player("9", "伯卡特", "中锋", 6.9),
        ],
        injuries=[
            Injury("杰斯克·恩卡姆", "中锋", "腿筋受伤"),
            Injury("马利克·平蓬", "中锋", "撞伤"),
        ],
        avg_rating_last=6.36,
    )

    frankfurt = TeamData(
        name="法兰克福",
        standing=frankfurt_standing,
        stats=frankfurt_stats,
        goal_probs=frankfurt_goal_probs,
        form=frankfurt_form,
        handicap_trend_full=frankfurt_trend_full,
        handicap_trend_half=frankfurt_trend_half,
        same_handicap=frankfurt_same_hc,
        lineup=frankfurt_lineup,
        recent_ratings=[6.36, 6.83, 7.35, 6.37, 6.79, 8.19, 6.01, 6.47, 6.49, 6.35],
        historical_seasons=frankfurt_hist,
    )

    # --- 科隆 本赛季排名 ---
    koln_standing = TeamStanding(
        overall=StandingRecord(5, 2, 1, 2, 8, 10, -2, 7, rank=10, win_rate=0.40),
        home=StandingRecord(3, 2, 1, 0, 6, 4, 2, 7, rank=4, win_rate=0.667),
        away=StandingRecord(2, 0, 0, 2, 2, 6, -4, 0, rank=15, win_rate=0.0),
        half_overall=StandingRecord(5, 1, 1, 3, 2, 4, -2, 4, rank=14, win_rate=0.20),
        half_home=StandingRecord(3, 1, 1, 1, 2, 2, 0, 4, rank=10, win_rate=0.333),
        half_away=StandingRecord(2, 0, 0, 2, 0, 2, -2, 0, rank=17, win_rate=0.0),
    )

    # --- 科隆 上赛季 (2025-2026 德甲) ---
    koln_hist = [
        SeasonRecord("2025-2026", "德甲",
            StandingRecord(34, 7, 11, 16, 49, 63, -14, 32, rank=14, win_rate=0.206),
            StandingRecord(17, 5, 4, 8, 30, 30, 0, 19, rank=13, win_rate=0.294),
            StandingRecord(17, 2, 7, 8, 19, 33, -14, 13, rank=16, win_rate=0.118),
        ),
        SeasonRecord("2024-2025", "德乙",
            StandingRecord(34, 18, 7, 9, 53, 38, 15, 61, rank=1, win_rate=0.529),
            StandingRecord(17, 9, 4, 4, 33, 18, 15, 31, rank=2, win_rate=0.529),
            StandingRecord(17, 9, 3, 5, 20, 20, 0, 30, rank=8, win_rate=0.529),
        ),
    ]

    koln_stats = TeamStats(
        goals_scored_3=1.7, goals_scored_10=2.4,
        goals_conceded_3=1.7, goals_conceded_10=1.6,
        shots_against_3=12.7, shots_against_10=11.9,
        corners_3=6.3, corners_10=6,
        yellow_cards_3=2, yellow_cards_10=1.6,
        fouls_3=11, fouls_10=9.7,
        possession_3=57.3, possession_10=52.8,
    )

    koln_goal_probs = [
        GoalProbPeriod("1~15", 20, 14), GoalProbPeriod("16~30", 9, 15),
        GoalProbPeriod("31~45", 7, 17), GoalProbPeriod("46~60", 15, 15),
        GoalProbPeriod("61~75", 16, 17), GoalProbPeriod("76~90", 26, 12),
        GoalProbPeriod("90+", 3, 7),
    ]

    koln_form = [
        FormRecord("26-10-11", "德甲", "科隆", "2-1", "1-1", "门兴格拉德巴赫", "半球", "胜", "赢", "小"),
        FormRecord("26-09-19", "德甲", "汉堡", "2-1", "1-0", "科隆", "平手", "负", "输", "走"),
        FormRecord("26-09-13", "德甲", "科隆", "1-1", "1-0", "云达不莱梅", "平/半", "平", "输", "小"),
        FormRecord("26-09-05", "德甲", "斯图加特", "4-1", "1-0", "科隆", "一/球半", "负", "输", "大"),
        FormRecord("26-08-29", "德甲", "科隆", "3-2", "0-1", "霍芬海姆", "*平/半", "胜", "赢", "大"),
        FormRecord("26-08-25", "德国杯", "维尔茨堡踢球者", "1-2", "1-0", "科隆", "*球半", "胜", "输", "小"),
    ]

    koln_trend_full = HandicapTrend(5, 2, 0, 3, 0.40, 2, 0.40, 1, 0.20)
    koln_trend_half = HandicapTrend(5, 1, 0, 4, 0.20, 1, 0.20, 4, 0.80)
    koln_same_hc = SameHandicapRecord("半球", 45, 0, 31, 0.592, 18, 6, 0.75, 27, 25, 0.519)

    koln_lineup = TeamLineup(
        formation="4-2-3-1", coach="雷内·瓦格纳",
        starters=[
            Player("1", "M·施瓦贝", "守门员", 7.7), Player("3", "苏沙", "左后卫", 8.0),
            Player("24", "L.罗乔什维利", "中卫", 6.8), Player("22", "普西", "中卫", 6.6),
            Player("28", "塞巴斯蒂安·索拉斯", "右后卫", 5.9), Player("37", "L·马伊纳", "右边锋", 7.8),
            Player("8", "约翰内松", "中前卫", 7.9), Player("6", "斯希里", "后腰", 7.0),
            Player("47", "M.摩尔", "右边锋", 7.1), Player("10", "埃尔马拉", "左边锋", 8.3),
            Player("30", "巴特勒", "左边锋", 6.3),
        ],
        injuries=[
            Injury("里克·范登贝格", "中卫", "肌肉损伤"),
            Injury("埃利亚斯.斯希里", "后腰", "下胫腓韧带撕裂"),
            Injury("蒂莫·许伯斯", "中卫", "膝关节损伤"),
            Injury("卡斯特罗·蒙特斯", "右后卫", "肌肉损伤"),
            Injury("朗纳阿赫", "中锋", "肌肉损伤"),
            Injury("蒂斯·达林加", "中锋", "十字韧带损伤"),
        ],
        avg_rating_last=7.12,
    )

    koln = TeamData(
        name="科隆",
        standing=koln_standing,
        stats=koln_stats,
        goal_probs=koln_goal_probs,
        form=koln_form,
        handicap_trend_full=koln_trend_full,
        handicap_trend_half=koln_trend_half,
        same_handicap=koln_same_hc,
        lineup=koln_lineup,
        recent_ratings=[7.12, 6.63, 6.51, 6.23, 6.74, 7.06, 5.96, 6.28, 6.55, 6.44],
        historical_seasons=koln_hist,
    )

    # --- 交锋往绩 (近10场) ---
    h2h = [
        H2HRecord("26-04-05", "德甲", "法兰克福", "2-2", "0-0", "8-0", "科隆", "半球", "平", "输", "大"),
        H2HRecord("25-11-23", "德甲", "科隆", "3-4", "1-2", "3-3", "法兰克福", "平手", "胜", "赢", "大"),
        H2HRecord("24-02-04", "德甲", "科隆", "2-0", "0-0", "7-7", "法兰克福", "平手", "负", "输", "小"),
        H2HRecord("23-09-03", "德甲", "法兰克福", "1-1", "0-1", "8-1", "科隆", "平/半", "平", "输", "小"),
        H2HRecord("23-02-13", "德甲", "科隆", "3-0", "0-0", "3-9", "法兰克福", "平手", "负", "输", "大"),
        H2HRecord("22-08-21", "德甲", "法兰克福", "1-1", "0-0", "5-9", "科隆", "平/半", "平", "输", "小"),
        H2HRecord("22-02-20", "德甲", "科隆", "1-0", "0-0", "5-6", "法兰克福", "平/半", "负", "输", "小"),
        H2HRecord("21-09-25", "德甲", "法兰克福", "1-1", "1-1", "7-6", "科隆", "平/半", "平", "输", "小"),
        H2HRecord("21-02-14", "德甲", "法兰克福", "2-0", "0-0", "7-2", "科隆", "一球", "胜", "赢", "小"),
        H2HRecord("20-10-18", "德甲", "科隆", "1-1", "0-1", "2-8", "法兰克福", "*平/半", "平", "输", "小"),
    ]

    brief = ("法兰克福与科隆本赛季开局差距主要体现在稳定性和士气上。法兰克福仅一胜且刚遭大败，"
             "积分榜落后于科隆，保级压力更大；科隆上轮取胜，状态和信心占优，近七次交手也胜率更高。"
             "战术上，法兰克福偏控球短传与右路下底，边路进攻和定位球防守出色，但争顶与防反击是短板；"
             "科隆擅用宽度、传中和左路下底，争顶与反击恰能针对其弱点。伤停方面，法兰克福锋线缺人，"
             "科隆中后场及锋线减员更广。心理层面，法兰克福急需止颓，科隆则更从容，整体趋势客队好于主队。")

    return MatchData(match=match, odds=odds, home_team=frankfurt,
                     away_team=koln, h2h=h2h, pre_match_brief=brief)


# ============================================================
# 三、多维度胜率分析引擎
# ============================================================

def odds_to_prob(o: EuropeanOdds):
    """欧赔转概率(扣除水位)"""
    p_home = 1 / o.home_win
    p_draw = 1 / o.draw
    p_away = 1 / o.away_win
    total = p_home + p_draw + p_away
    return p_home / total, p_draw / total, p_away / total


def rank_to_strength(rank: int, n_teams: int = 18) -> float:
    """排名转换为实力分 (0~1), 排名越高分越高"""
    return (n_teams - rank + 1) / n_teams


def analyze(m: MatchData):
    results = {}

    # ---- 维度1: 本赛季联赛排名胜率 ----
    home_str = rank_to_strength(m.home_team.standing.overall.rank)
    away_str = rank_to_strength(m.away_team.standing.overall.rank)
    s = home_str + away_str
    p_home_rank = home_str / s
    p_away_rank = away_str / s
    # 平局概率用本赛季双方平局率加权
    home_draw_rate = m.home_team.standing.overall.draws / m.home_team.standing.overall.played
    away_draw_rate = m.away_team.standing.overall.draws / m.away_team.standing.overall.played
    p_draw_rank = (home_draw_rate + away_draw_rate) / 2
    # 归一化
    tot = p_home_rank + p_draw_rank + p_away_rank
    results["本赛季排名"] = (p_home_rank / tot, p_draw_rank / tot, p_away_rank / tot)

    # ---- 维度2: 上赛季排名胜率 (增加样本) ----
    h_last = m.home_team.historical_seasons[0].overall
    a_last = m.away_team.historical_seasons[0].overall
    h_str = rank_to_strength(h_last.rank)
    a_str = rank_to_strength(a_last.rank)
    s2 = h_str + a_str
    p_home_last = h_str / s2
    p_away_last = a_str / s2
    p_draw_last = (h_last.draws / h_last.played + a_last.draws / a_last.played) / 2
    tot2 = p_home_last + p_draw_last + p_away_last
    results["上赛季排名"] = (p_home_last / tot2, p_draw_last / tot2, p_away_last / tot2)

    # ---- 维度3: 近期状态胜率 (近6场正式比赛) ----
    def form_winrate(form):
        w = sum(1 for r in form if r.result == "胜")
        d = sum(1 for r in form if r.result == "平")
        l = sum(1 for r in form if r.result == "负")
        n = len(form)
        return w / n, d / n, l / n

    hw, hd, hl = form_winrate(m.home_team.form)
    aw, ad, al = form_winrate(m.away_team.form)
    # 主队状态 vs 客队状态
    p_home_form = hw * (1 - aw * 0.5)
    p_draw_form = (hd + ad) / 2
    p_away_form = aw * (1 - hw * 0.5)
    tot3 = p_home_form + p_draw_form + p_away_form
    results["近期状态"] = (p_home_form / tot3, p_draw_form / tot3, p_away_form / tot3)

    # ---- 维度4: 交锋往绩胜率 (H2H近10场) ----
    # result 是从该场主队视角，需要转换为法兰克福视角
    h2h_home_w = 0
    h2h_draw = 0
    h2h_away_w = 0
    for r in m.h2h:
        if r.home_team == m.match.home_team:
            res = r.result
        else:
            # 翻转: 科隆主视角的胜=法兰克福负
            res = {"胜": "负", "平": "平", "负": "胜"}[r.result]
        if res == "胜":
            h2h_home_w += 1
        elif res == "平":
            h2h_draw += 1
        else:
            h2h_away_w += 1
    n_h2h = len(m.h2h)
    results["交锋往绩"] = (h2h_home_w / n_h2h, h2h_draw / n_h2h, h2h_away_w / n_h2h)

    # ---- 维度5: 盘口隐含胜率 (欧赔) ----
    p_h, p_d, p_a = odds_to_prob(m.odds.european)
    results["盘口隐含"] = (p_h, p_d, p_a)

    # ---- 维度6: 主客场因素 (混合本赛季+上赛季, 避免小样本退化) ----
    # 主队主场战绩 (本赛季 + 上赛季加权)
    h_home = m.home_team.standing.home
    h_last_home = m.home_team.historical_seasons[0].home
    hh_w = (h_home.wins + h_last_home.wins) / (h_home.played + h_last_home.played)
    hh_d = (h_home.draws + h_last_home.draws) / (h_home.played + h_last_home.played)
    # 客队客场战绩 (本赛季 + 上赛季加权)
    a_away = m.away_team.standing.away
    a_last_away = m.away_team.historical_seasons[0].away
    aa_w = (a_away.wins + a_last_away.wins) / (a_away.played + a_last_away.played)
    aa_d = (a_away.draws + a_last_away.draws) / (a_away.played + a_last_away.played)
    p_home_ha = hh_w * (1 - aa_w * 0.5)
    p_draw_ha = (hh_d + aa_d) / 2
    p_away_ha = aa_w * (1 - hh_w * 0.5)
    tot6 = p_home_ha + p_draw_ha + p_away_ha
    results["主客场"] = (p_home_ha / tot6, p_draw_ha / tot6, p_away_ha / tot6)

    # ---- 维度7: 攻防能力 (场均进球/失球) ----
    h_gf = m.home_team.stats.goals_scored_10
    h_ga = m.home_team.stats.goals_conceded_10
    a_gf = m.away_team.stats.goals_scored_10
    a_ga = m.away_team.stats.goals_conceded_10
    # 期望进球: 主队进攻 vs 客队防守
    exp_home_goals = (h_gf + a_ga) / 2
    exp_away_goals = (a_gf + h_ga) / 2
    # 用泊松分布近似转换为胜平负概率
    def poisson_prob(lam, k):
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    p_home_atk = 0
    p_draw_atk = 0
    p_away_atk = 0
    for i in range(8):
        for j in range(8):
            p = poisson_prob(exp_home_goals, i) * poisson_prob(exp_away_goals, j)
            if i > j:
                p_home_atk += p
            elif i == j:
                p_draw_atk += p
            else:
                p_away_atk += p
    tot7 = p_home_atk + p_draw_atk + p_away_atk
    results["攻防能力"] = (p_home_atk / tot7, p_draw_atk / tot7, p_away_atk / tot7)

    # ---- 维度8: 相同盘口赢盘率 (半球盘) ----
    h_hc_wr = m.home_team.same_handicap.home_win_rate  # 主队主场半球盘赢盘率
    a_hc_wr = m.away_team.same_handicap.away_win_rate  # 客队客场半球盘赢盘率
    # 赢盘率高 => 该方向打出概率高
    s8 = h_hc_wr + a_hc_wr
    p_home_hc = h_hc_wr / s8 * 0.7   # 赢盘不全等于赢球, 乘系数
    p_away_hc = a_hc_wr / s8 * 0.7
    p_draw_hc = 1 - p_home_hc - p_away_hc
    tot8 = p_home_hc + p_draw_hc + p_away_hc
    results["相同盘口"] = (p_home_hc / tot8, p_draw_hc / tot8, p_away_hc / tot8)

    # ---- 维度9: 半场能力 ----
    h_half_wr = m.home_team.standing.half_overall.wins / m.home_team.standing.half_overall.played
    a_half_wr = m.away_team.standing.half_overall.wins / m.away_team.standing.half_overall.played
    s9 = h_half_wr + a_half_wr
    p_home_half = h_half_wr / s9 * 0.6
    p_away_half = a_half_wr / s9 * 0.6
    p_draw_half = 1 - p_home_half - p_away_half
    tot9 = p_home_half + p_draw_half + p_away_half
    results["半场能力"] = (p_home_half / tot9, p_draw_half / tot9, p_away_half / tot9)

    # ---- 维度10: 上赛季主客场战绩 (补充样本) ----
    h_last_home = m.home_team.historical_seasons[0].home
    a_last_away = m.away_team.historical_seasons[0].away
    hlh_wr = h_last_home.wins / h_last_home.played
    ala_wr = a_last_away.wins / a_last_away.played
    hlh_dr = h_last_home.draws / h_last_home.played
    ala_dr = a_last_away.draws / a_last_away.played
    p_home_10 = hlh_wr * (1 - ala_wr * 0.5)
    p_draw_10 = (hlh_dr + ala_dr) / 2
    p_away_10 = ala_wr * (1 - hlh_wr * 0.5)
    tot10 = p_home_10 + p_draw_10 + p_away_10
    results["上赛季主客"] = (p_home_10 / tot10, p_draw_10 / tot10, p_away_10 / tot10)

    return results


# ============================================================
# 四、加权融合与输出
# ============================================================

WEIGHTS = {
    "本赛季排名": 0.12,
    "上赛季排名": 0.10,
    "近期状态": 0.12,
    "交锋往绩": 0.10,
    "盘口隐含": 0.20,
    "主客场": 0.08,
    "攻防能力": 0.08,
    "相同盘口": 0.07,
    "半场能力": 0.06,
    "上赛季主客": 0.07,
}


def weighted_fusion(results):
    h = d = a = 0
    for dim, (ph, pd, pa) in results.items():
        w = WEIGHTS[dim]
        h += ph * w
        d += pd * w
        a += pa * w
    return h, d, a


# ============================================================
# 四-B、亚盘(让球)专项分析
# ============================================================

HANDICAP_MAP = {
    "平手": 0, "平/半": -0.25, "半球": -0.5, "半/一": -0.75,
    "一球": -1, "一/球半": -1.25, "球半": -1.5, "球半/两": -1.75,
    "两球": -2,
}


def handicap_to_num(h: str) -> float:
    """盘口文字转数值(主队让球为负)"""
    if h.startswith("*"):
        h = h[1:]
    return HANDICAP_MAP.get(h, 0.0)


def water_to_prob(home_water: float, away_water: float) -> tuple:
    """水位转隐含概率(扣除水位后)"""
    # 亚盘隐含概率: 主队赢盘概率 = 客水 / (主水 + 客水)
    # 因为水位越低，机构认为打出概率越高
    p_home = away_water / (home_water + away_water)
    p_away = home_water / (home_water + away_water)
    return p_home, p_away


def analyze_asian_handicap(m: MatchData) -> dict:
    """亚盘专项分析，返回各维度结论"""
    a = m.odds.asian

    # 1. 盘口数值
    full_open_hcp = handicap_to_num(a.full_open_handicap)
    full_live_hcp = handicap_to_num(a.full_live_handicap)
    half_open_hcp = handicap_to_num(a.half_open_handicap)
    half_live_hcp = handicap_to_num(a.half_live_handicap)

    # 2. 水位变化 (全场)
    full_home_water_change = a.full_live_home_water - a.full_open_home_water
    full_away_water_change = a.full_live_away_water - a.full_open_away_water

    # 3. 水位隐含概率 (即时)
    p_home_live, p_away_live = water_to_prob(a.full_live_home_water, a.full_live_away_water)
    p_home_open, p_away_open = water_to_prob(a.full_open_home_water, a.full_open_away_water)

    # 4. 水位变化方向判断
    if full_home_water_change < -0.03:
        home_trend = "↓ 大幅下降(主队受热, 机构降低赔付)"
    elif full_home_water_change < 0:
        home_trend = "↓ 小幅下降(主队略受捧)"
    elif full_home_water_change < 0.03:
        home_trend = "→ 基本持平"
    else:
        home_trend = "↑ 上升(主队受热降低)"

    # 5. 盘口升降判断
    if full_live_hcp < full_open_hcp:
        hcp_trend = "升盘(对主队信心增强)"
    elif full_live_hcp > full_open_hcp:
        hcp_trend = "降盘(对主队信心减弱)"
    else:
        hcp_trend = "盘口不变"

    # 6. 相同盘口赢盘率 (半球盘)
    h_same = m.home_team.same_handicap
    a_same = m.away_team.same_handicap

    # 7. 本赛季赢盘率
    h_trend = m.home_team.handicap_trend_full
    a_trend = m.away_team.handicap_trend_full

    # 8. 综合亚盘倾向评分
    # 水位倾向: 主水下降 + 盘口不变/升盘 => 利好主队
    water_score = 0
    if full_home_water_change < 0:
        water_score += 1
    elif full_home_water_change > 0:
        water_score -= 1
    if full_live_hcp <= full_open_hcp:
        water_score += 1
    else:
        water_score -= 1

    # 相同盘口赢盘率对比 (主队主场 vs 客队客场)
    hcp_score = 0
    if h_same.home_win_rate > a_same.away_win_rate:
        hcp_score += 1
    elif h_same.home_win_rate < a_same.away_win_rate:
        hcp_score -= 1

    total_score = water_score + hcp_score

    if total_score >= 2:
        advice = "主队方向(上盘)"
    elif total_score >= 1:
        advice = "略倾向主队(上盘)"
    elif total_score <= -2:
        advice = "客队方向(下盘)"
    elif total_score <= -1:
        advice = "略倾向客队(下盘)"
    else:
        advice = "中性(盘口均衡)"

    return {
        "full_open_handicap": a.full_open_handicap,
        "full_live_handicap": a.full_live_handicap,
        "full_open_home_water": a.full_open_home_water,
        "full_open_away_water": a.full_open_away_water,
        "full_live_home_water": a.full_live_home_water,
        "full_live_away_water": a.full_live_away_water,
        "full_home_water_change": full_home_water_change,
        "full_away_water_change": full_away_water_change,
        "half_open_handicap": a.half_open_handicap,
        "half_live_handicap": a.half_live_handicap,
        "half_open_home_water": a.half_open_home_water,
        "half_open_away_water": a.half_open_away_water,
        "half_live_home_water": a.half_live_home_water,
        "half_live_away_water": a.half_live_away_water,
        "hcp_trend": hcp_trend,
        "home_water_trend": home_trend,
        "p_home_open": p_home_open,
        "p_away_open": p_away_open,
        "p_home_live": p_home_live,
        "p_away_live": p_away_live,
        "h_same_home_wr": h_same.home_win_rate,
        "a_same_away_wr": a_same.away_win_rate,
        "h_this_season_wr": h_trend.win_rate,
        "a_this_season_wr": a_trend.win_rate,
        "total_score": total_score,
        "advice": advice,
    }


def print_asian_handicap_report(m: MatchData, ah: dict):
    """打印亚盘专项分析报告"""
    print("\n" + "=" * 72)
    print("  亚盘(让球)专项分析")
    print("=" * 72)

    # 全场盘口
    print(f"\n  【全场让球盘】")
    print(f"  {'':<12}{'盘口':<10}{'主队水位':<12}{'客队水位':<12}")
    print(f"  {'开盘':<12}{ah['full_open_handicap']:<10}{ah['full_open_home_water']:<12.2f}{ah['full_open_away_water']:<12.2f}")
    print(f"  {'即时':<12}{ah['full_live_handicap']:<10}{ah['full_live_home_water']:<12.2f}{ah['full_live_away_water']:<12.2f}")
    print(f"  {'变化':<12}{ah['hcp_trend']:<10}"
          f"{'↓' if ah['full_home_water_change']<0 else '↑' if ah['full_home_water_change']>0 else '→'}"
          f" {ah['full_home_water_change']:+.2f}    "
          f"{'↓' if ah['full_away_water_change']<0 else '↑' if ah['full_away_water_change']>0 else '→'}"
          f" {ah['full_away_water_change']:+.2f}")

    # 半场盘口
    print(f"\n  【半场让球盘】")
    print(f"  {'':<12}{'盘口':<10}{'主队水位':<12}{'客队水位':<12}")
    print(f"  {'开盘':<12}{ah['half_open_handicap']:<10}{ah['half_open_home_water']:<12.2f}{ah['half_open_away_water']:<12.2f}")
    print(f"  {'即时':<12}{ah['half_live_handicap']:<10}{ah['half_live_home_water']:<12.2f}{ah['half_live_away_water']:<12.2f}")

    # 水位隐含概率
    print(f"\n  【水位隐含赢盘概率】(即时)")
    print(f"  主队({m.match.home_team})赢盘概率: {ah['p_home_live']*100:.1f}%  (开盘 {ah['p_home_open']*100:.1f}%)")
    print(f"  客队({m.match.away_team})赢盘概率: {ah['p_away_live']*100:.1f}%  (开盘 {ah['p_away_open']*100:.1f}%)")

    # 盘口解读
    print(f"\n  【盘口解读】")
    print(f"  · 全场盘口 {ah['full_live_handicap']}: {m.match.home_team} 让 {abs(handicap_to_num(ah['full_live_handicap']))} 球")
    print(f"    → 机构视 {m.match.home_team} 为实力占优方，需净胜1球及以上才赢盘")
    print(f"  · 盘口走势: {ah['hcp_trend']}")
    print(f"  · 主队水位走势: {ah['home_water_trend']}")

    if ah['full_home_water_change'] < 0:
        print(f"    → 主队水位下降，说明市场资金流向主队，机构主动降低主队赔付")
    elif ah['full_home_water_change'] > 0:
        print(f"    → 主队水位上升，说明市场资金流向客队，机构主动提高主队赔付")

    # 相同盘口赢盘率
    print(f"\n  【相同盘口(半球)历史赢盘率】")
    print(f"  {m.match.home_team} 主场半球盘赢盘率: {ah['h_same_home_wr']*100:.1f}%")
    print(f"  {m.match.away_team} 客场半球盘赢盘率: {ah['a_same_away_wr']*100:.1f}%")
    if ah['h_same_home_wr'] > ah['a_same_away_wr']:
        print(f"    → {m.match.home_team} 主场打半球盘历史表现更优")
    else:
        print(f"    → {m.match.away_team} 客场受让半球盘历史表现更优")

    # 本赛季赢盘率
    print(f"\n  【本赛季全场赢盘率】")
    print(f"  {m.match.home_team}: {ah['h_this_season_wr']*100:.1f}%")
    print(f"  {m.match.away_team}: {ah['a_this_season_wr']*100:.1f}%")

    # 综合建议
    print(f"\n  【亚盘综合建议】")
    print(f"  综合评分(水位+盘口+赢盘率): {ah['total_score']}")
    print(f"  >>> 推荐方向: {ah['advice']}")
    if ah['total_score'] >= 1:
        print(f"      (即: {m.match.home_team} -0.5 半球)")
    elif ah['total_score'] <= -1:
        print(f"      (即: {m.match.away_team} +0.5 半球)")
    else:
        print("      (盘口均衡，建议观望)")
    print("\n" + "=" * 72)
    print("  注: 亚盘分析基于盘口与水位变化，仅供参考，不构成投注建议。")
    print("=" * 72)


def print_report(m: MatchData, results, final):
    print("=" * 72)
    print(f"  胜率分析报告: {m.match.home_team} VS {m.match.away_team}")
    print(f"  {m.match.league} {m.match.round_no} | {m.match.match_time}")
    print(f"  场地: {m.match.venue} | {m.match.weather} {m.match.temperature}")
    print("=" * 72)

    print(f"\n{'维度':<14}{'主胜':>10}{'平局':>10}{'客胜':>10}{'权重':>8}")
    print("-" * 56)
    for dim, (ph, pd, pa) in results.items():
        w = WEIGHTS[dim]
        print(f"{dim:<14}{ph*100:>9.1f}%{pd*100:>9.1f}%{pa*100:>9.1f}%{w*100:>7.0f}%")

    h, d, a = final
    print("-" * 56)
    print(f"{'综合胜率':<14}{h*100:>9.1f}%{d*100:>9.1f}%{a*100:>9.1f}%{'100':>7}%")
    print(f"\n  概率合计: {(h+d+a)*100:.1f}%")

    # 亚盘方向
    handicap = m.odds.asian.full_live_handicap
    home_water = m.odds.asian.full_live_home_water
    away_water = m.odds.asian.full_live_away_water
    print(f"\n  亚盘: 主队 {handicap} (主水 {home_water} / 客水 {away_water})")
    if h > a:
        print(f"  >>> 倾向: 主队 {m.match.home_team} 方向 (主胜概率 {h*100:.1f}%)")
    elif a > h:
        print(f"  >>> 倾向: 客队 {m.match.away_team} 方向 (客胜概率 {a*100:.1f}%)")
    else:
        print("  >>> 倾向: 平局方向")

    # 关键因素
    print("\n" + "-" * 72)
    print("  关键因素解读")
    print("-" * 72)
    h_pts = m.home_team.standing.overall.points
    a_pts = m.away_team.standing.overall.points
    print(f"  · 本赛季积分: {m.match.home_team} {h_pts}分(第{m.home_team.standing.overall.rank}名) "
          f"vs {m.match.away_team} {a_pts}分(第{m.away_team.standing.overall.rank}名)")

    h_last_rk = m.home_team.historical_seasons[0].overall.rank
    a_last_rk = m.away_team.historical_seasons[0].overall.rank
    print(f"  · 上赛季排名: {m.match.home_team} 第{h_last_rk}名 vs {m.match.away_team} 第{a_last_rk}名")

    h_hw = m.home_team.standing.home.wins
    h_hl = m.home_team.standing.home.losses
    a_aw = m.away_team.standing.away.wins
    a_al = m.away_team.standing.away.losses
    print(f"  · 本赛季主客场: {m.match.home_team} 主场{h_hw}胜{h_hl}负 "
          f"vs {m.match.away_team} 客场{a_aw}胜{a_al}负")

    h_inj = len(m.home_team.lineup.injuries)
    a_inj = len(m.away_team.lineup.injuries)
    print(f"  · 伤停人数: {m.match.home_team} {h_inj}人 vs {m.match.away_team} {a_inj}人")

    h_rating = m.home_team.lineup.avg_rating_last
    a_rating = m.away_team.lineup.avg_rating_last
    print(f"  · 上轮平均评分: {m.match.home_team} {h_rating} vs {m.match.away_team} {a_rating}")

    print(f"\n  赛前简报: {m.pre_match_brief[:80]}...")
    print("\n" + "=" * 72)
    print("  注: 以上为基于历史数据的概率预测, 仅供参考, 不构成投注建议。")
    print("=" * 72)


# ============================================================
# 主程序
# ============================================================

if __name__ == "__main__":
    data = build_match_data()
    results = analyze(data)
    final = weighted_fusion(results)
    print_report(data, results, final)
    ah = analyze_asian_handicap(data)
    print_asian_handicap_report(data, ah)
