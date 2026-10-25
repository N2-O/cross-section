"""Leetify 七维能力评分（后端计算）。

算法来源
--------
Leetify 前端 main.js 里的实现（反混淆后的核心）：

    getZScore(value, mean, stddev, scale, invert) {
        let z = (value - mean) / stddev;
        if (invert) z *= -1;
        return z * Math.sqrt(scale);   // scale 是可选缩放因子，默认 1
    }

注意最后一个参数**不是回合数**：调用方 `transform(R, k=1)` 里的 R 默认取 1
（只有 `isScaledForMatch` 的那几个指标才传别的值），sqrt(1) = 1。所以这里是
**裸 z-score**，不乘 sqrt(rounds)。早期按 sqrt(回合数) 放大过，结果把「每回合
死亡 0.859 vs 全体 0.743」算成 z=-2.9（全场最差 0.2%），偏差离谱，已废弃。

分级阈值（前端 zScoreDeviationStep）：z < -1.28155 → -2，< -0.524 → -1，
< 0.524 → 0（平均），< 1.28155 → 1，否则 2。百分位用正态 CDF 转。

口径
----
- 基准 = 库里**所有玩家-场次**（pms 的每一行）各自的该指标分布，不是玩家个人历史。
- 每个细项独立算 mean / pstdev，目标玩家的值代入求 z。
- 反向指标（死亡类、被伤害）在 z 上 invert，而不是在 value 上取倒数。
- 分布只算一次：进程内 `_BASE_CACHE` 按（库路径 + 数据指纹）缓存；数据变了自动重算。

数据边界（没有就跳过，不伪造）
------------------------------
- 表里**没有炸弹安放 tick**，所以「安放后存活%」整项跳过（见 SKIPPED）。
- 表里**没有逐 tick 坐标**，「换人机会」的距离条件（< 2000 单位）无法验证，
  退化为「队友倒下时我仍存活」；距离项在 desc 里不承诺。
- 老库的 damage 表可能没有 `valid` 列（新库有）。有就用 valid=1，没有就自己按
  「敌我阵营 + 非自杀」过滤，保证两个库都能跑。

对外只有一个入口：`compute(conn, steamid, match_id=None)`。
"""
from __future__ import annotations

import sqlite3
import statistics
import math
from collections import defaultdict
from statistics import NormalDist
from typing import Any

__all__ = ["compute", "reset_cache", "DIMENSIONS", "SKIPPED"]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
TICKRATE = 64
TRADE_TICKS = 5 * TICKRATE          # 换人 / 被换窗口：5 秒
SNIPER_WEAPONS = {"awp", "ssg08", "scar20", "g3sg1"}
AWP_WEAPONS = {"awp"}

Z_NEG2, Z_NEG1, Z_POS1, Z_POS2 = -1.28155, -0.524, 0.524, 1.28155
Z_CLAMP = 4.0                       # 小库样本少时分布很窄，z 容易爆表，先夹住
MIN_BASE = 3                        # 分布样本少于这个数就不认（z 记 0）

try:  # 换边规则跟 ingest 保持一致；awpy 没装时用本地同规则实现（见下）
    from awpy_ingest import _side_of as _side_of_ingest  # type: ignore
except Exception:  # pragma: no cover - 取决于运行环境
    _side_of_ingest = None


def _side_of(fs, rnd: int, half: int = 12) -> str:
    """某人第 rnd 回合的阵营；优先复用 awpy_ingest._side_of。

    CS2 常规 12 回合半场，加时每 3 回合换边（起点延续第二半场）。
    """
    if _side_of_ingest is not None:
        return _side_of_ingest(fs, rnd, half)
    s = fs or "T"
    o = "CT" if s == "T" else "T"
    if rnd <= half:
        return s
    if half == 12:
        if rnd <= 24:
            return o
        return o if ((rnd - 25) // 3) % 2 == 0 else s
    return o


def _wname(weapon: Any) -> str:
    """weapon 名归一（"weapon_ak47" → "ak47"）。"""
    return str(weapon or "").replace("weapon_", "").strip().lower()


def _div(a: float, b: float):
    return (a / b) if b else None


def _pct(a: float, b: float):
    return (100.0 * a / b) if b else None


def _round_win(rinfo, side: str) -> bool:
    """该回合我方（side）是否赢。优先用 a_win / a_side，退回到 winner 文本。"""
    a_side = rinfo["a_side"]
    a_win = rinfo["a_win"]
    if a_side and a_win is not None:
        return (a_side == side) == bool(a_win)
    w = str(rinfo["winner"] or "").upper()
    return bool(w) and w == side


# ---------------------------------------------------------------------------
# 正态化：z → 百分位 / 等级
# ---------------------------------------------------------------------------
def _pct_of_z(z: float) -> float:
    return NormalDist().cdf(max(-Z_CLAMP, min(Z_CLAMP, z))) * 100.0


def _step_of_z(z: float) -> int:
    if z < Z_NEG2:
        return -2
    if z < Z_NEG1:
        return -1
    if z < Z_POS1:
        return 0
    if z < Z_POS2:
        return 1
    return 2


def _combine_zs(zs: list[float], weights: list[float] | None = None) -> float:
    """把多个细项 z 合成一个维度 z（Leetify 官方公式）。

        w = 权重（现在全用 1.0）
        S    = Σ x_i·w_i
        var  = Σ w_i²                # 不是 ((w_i·√n)²)：那个 n 已在中途抵消
        z    = S / √var

    单个细项时 S = x、var = 1，结果就是裸 x。多项时按独立观测合并
    （等价于 Stouffer 法），不会把 n 当成放大倍数乘进去。
    """
    n = len(zs)
    if not n:
        return 0.0
    w = weights or [1.0] * n
    s = sum(z * wi for z, wi in zip(zs, w))
    var = sum(wi * wi for wi in w)
    return s / math.sqrt(var) if var > 0 else 0.0


# ---------------------------------------------------------------------------
# 细项定义
#   key      指标键
#   name     中文名
#   unit     单位（"" / "%" / "s"）
#   invert   True = 越低越好
#   digits   展示小数位
#   desc     悬浮说明（说清在量什么 + 高了意味着什么）
# ---------------------------------------------------------------------------
ITEMS: list[dict] = [
    # ---------------- Firepower 火力 ----------------
    {"key": "kpr_win", "name": "每胜局击杀", "unit": "", "invert": False, "digits": 2,
     "desc": "你赢下的回合里平均能拿多少击杀。高说明顺风局你不只是躺赢，而是主要收割者；"
             "如果低于 0.8，通常意味着你赢的回合多是队友打开局面。"},
    {"key": "nd_kill_pr", "name": "无伤击杀每回合", "unit": "", "invert": False, "digits": 2,
     "desc": "你带着满血（这一枪之前没掉过血）完成的击杀摊到每回合。衡量对枪质量："
             "高说明你的击杀多是干净利落的先手，而不是残血互换换来的。"},
    {"key": "kill_round_pct", "name": "有击杀回合占比", "unit": "%", "invert": False, "digits": 1,
     "desc": "回合里至少拿到一个人头的比例。这是最基础的「稳定输出」指标，"
             "长期低于 45% 说明有大量回合你完全没参与击杀。"},
    {"key": "net_kill_24", "name": "击杀每 24 回合", "unit": "", "invert": False, "digits": 1,
     "desc": "击杀数按 24 回合折算，也就是「一整场」量级你能拿多少人头。"
             "按 HLTV 的火力口径只奖励产出、不扣死亡代价 —— 死得多由 Closing 和换命去扣。"},
    {"key": "win_contrib", "name": "回合胜利贡献", "unit": "%", "invert": False, "digits": 1,
     "desc": "赢下的回合里，你的击杀+助攻占全队击杀+助攻的份额（存活到最后再额外加权）。"
             "接近 20% 是均分，30% 以上说明赢的局很大程度是你扛的。"},
    {"key": "prevent_trade_pr", "name": "阻止换人每回合", "unit": "", "invert": False, "digits": 2,
     "desc": "你拿到击杀后 5 秒内队友一个都没死的比例（按你的击杀数摊到每回合）。"
             "高说明你开火之后能压住对面，不让队友被反打换掉。"},
    {"key": "multi_round_pct", "name": "多杀回合占比", "unit": "%", "invert": False, "digits": 1,
     "desc": "同一回合拿到 2 个及以上击杀的比例。衡量爆发力：能连续处理多个目标的玩家，"
             "在残局和被打崩的回合里更容易救场。"},
    {"key": "net_dmg_pr", "name": "伤害每回合", "unit": "", "invert": False, "digits": 1,
     "desc": "每回合打出的有效伤害（已剔除过量击杀、死后补枪和友伤）。"
             "HLTV 的火力口径不扣「挨打」那部分 —— 高产出就是高产出，代价不计。"},

    # ---------------- Entrying 换命 ----------------
    {"key": "tradeable_death_pr", "name": "可换死亡每回合", "unit": "", "invert": True, "digits": 2,
     "desc": "你死的时候队友还活着（本来能被换回来）的次数摊到每回合。这是反向指标："
             "数值低说明你很少死在孤立无援的位置（单摸、脱节、被单抓）。"},
    {"key": "death_traded_pct", "name": "死亡被换%", "unit": "%", "invert": False, "digits": 1,
     "desc": "你阵亡后 5 秒内队友杀掉凶手（把你的命换回来）的比例。高说明你死的位置"
             "队友跟得上，你的死能换来人数互换而不是白给。"},
    {"key": "bait_assist_pr", "name": "诱饵助攻每回合", "unit": "", "invert": False, "digits": 2,
     "desc": "你死后立刻被队友换掉凶手的次数摊到每回合 —— 也就是你「吸火力」的效率。"
             "高说明你冲进去虽然死了，但把对面的枪线和子弹都吃掉了，队友能顺势收人。"},
    {"key": "fd_traded_pct", "name": "首死被换%", "unit": "%", "invert": False, "digits": 1,
     "desc": "你拿到全场首个死亡时，队友在 5 秒内换掉凶手的比例。开局面死亡不可怕，"
             "可怕的是白死：这项低说明你的开局尝试经常送掉一个人头还换不回来。"},

    # ---------------- Trading 补枪 ----------------
    {"key": "trade_opp_pr", "name": "换人机会每回合", "unit": "", "invert": False, "digits": 2,
     "desc": "队友倒下时你还活着（处在能补枪的位置）的次数摊到每回合。这是「补枪意愿」的"
             "分母：数值高说明你打团时站位靠得住，不是总在别处。"},
    {"key": "trade_success_pct", "name": "换人成功%", "unit": "%", "invert": False, "digits": 1,
     "desc": "有换人机会时，你真的在 5 秒内杀掉凶手的比例。高说明队友一倒你就能立刻还手，"
             "对面拿不到「先倒一人」的便宜。"},
    {"key": "bait_kill_pct", "name": "诱饵击杀%", "unit": "%", "invert": False, "digits": 1,
     "desc": "你的击杀里有多少是「队友刚死 5 秒内」完成的复仇击杀。高说明你专门吃"
             "对面换人后的空档，是队伍里最会在混战里捡人头的人。"},
    {"key": "assist_kill_pct", "name": "助攻击杀%", "unit": "%", "invert": False, "digits": 1,
     "desc": "你自己拿一个人头的同时，参与了多少个由队友收掉的击杀（记助攻或被你打伤后由队友补掉）。"
             "比 100% 高说明你的输出溢出到了队友的战绩里，是典型的高团队贡献型。"},

    # ---------------- Opening 开局 ----------------
    {"key": "fe_pct", "name": "首杀尝试%", "unit": "%", "invert": False, "digits": 1,
     "desc": "本回合第一个交火（无论谁死）里有你的比例。高说明你是主动找第一枪的人，"
             "开局节奏由你定；过低则说明你长期在等队友先动。"},
    {"key": "fk_order", "name": "队内首杀顺位", "unit": "", "invert": True, "digits": 2,
     "desc": "在有击杀的回合里，你队内第几个开张（1 = 你通常是第一个拿到人头的人）。"
             "反向指标：接近 1 说明你是队里的第一枪，数值大说明你更多在收尾。"},
    {"key": "fk_time_s", "name": "首杀时间", "unit": "s", "invert": False, "digits": 1,
     "desc": "你参与的那次全场首杀平均发生在回合第几秒（从冻结结束算）。"
             "数值小说明你打得很激进、开局就交火；大说明你们习惯慢打、靠中期找机会。"},
    {"key": "fires_pr", "name": "每回合开火数", "unit": "", "invert": False, "digits": 2,
     "desc": "每回合平均扣了多少次扳机（枪械开火，不含刀和投掷物）。这是「参与度」的物理证据："
             "太低说明你在架枪等，太高往往意味着你在乱扫或被压制着打。"},

    # ---------------- Closing 残局 ----------------
    {"key": "survive_s", "name": "每回合存活秒数", "unit": "s", "invert": False, "digits": 1,
     "desc": "每回合平均活到第几秒（死了算死亡时刻，活着算到回合结束）。高说明你活得久、"
             "能在回合后段还在场；过低说明你常在开局 30 秒内就没了。"},
    {"key": "last_alive_pct", "name": "最后存活%", "unit": "%", "invert": False, "digits": 1,
     "desc": "你是本队最后一个倒下（或者干脆活到最后）的回合比例。高说明你经常是队伍的最后"
             "一道防线，也是残局的主要承担者。"},
    {"key": "clutch_24", "name": "残局每 24 回合", "unit": "", "invert": False, "digits": 2,
     "desc": "1v1~1v5 残局里赢下来的次数按 24 回合折算。这是纯结果指标："
             "残局赢得多，说明你在人数劣势下的判断和枪法都撑得住。"},
    {"key": "postplant_alive_pct", "name": "炸弹安放后存活%", "unit": "%", "invert": False, "digits": 1,
     "desc": "包被安下的那一刻你还活着的回合比例（只在真有安包的回合里统计）。低说明你常在安包前"
             "就倒了——进攻时进不到点、防守时守不住包点，两种情况都会反映在这一项上。"},

    # ---------------- Sniping 狙击 ----------------
    {"key": "sniper_round_pct", "name": "有狙击枪回合%", "unit": "%", "invert": False, "digits": 1,
     "desc": "你在该回合用狙击类武器（AWP/SSG08/SCAR-20/G3SG1）造成过伤害或击杀的比例。"
             "衡量你是不是队里的狙击位；按可用回合折算，不会因为半场换边失真。"},
    {"key": "sniper_kill_pct", "name": "狙击击杀%", "unit": "%", "invert": False, "digits": 1,
     "desc": "你的击杀里由狙击枪完成的比例。高说明你的输出高度依赖狙击枪，"
             "换步枪的回合杀伤会明显下降。"},
    {"key": "awp_round_pct", "name": "有 AWP 回合%", "unit": "%", "invert": False, "digits": 1,
     "desc": "拿着 AWP 实际打出东西的回合占比。这是「主力狙」的直接证据："
             "数值高说明队伍把大狙经济长期交给你。"},
    {"key": "awp_kill_pct", "name": "AWP 击杀%", "unit": "%", "invert": False, "digits": 1,
     "desc": "你的击杀里 AWP 占多少。超过 40% 基本可以认定你是个专职狙击手，"
             "而不是偶尔捡把狙用用。"},

    # ---------------- Utility 道具 ----------------
    {"key": "smoke_pr", "name": "烟雾每回合", "unit": "", "invert": False, "digits": 2,
     "desc": "每回合丢出的烟雾弹数量。高说明你在主动做视野封锁（进点隔断、拆点拖延），"
             "而不是把烟留到最后交不出来。"},
    {"key": "flash_pr", "name": "闪光每回合", "unit": "", "invert": False, "digits": 2,
     "desc": "每回合丢出的闪光弹数量。高说明你在给队友创造对枪优势；"
             "但要配合队友的闪光助攻看，光丢不中的闪光只是浪费经济。"},
    {"key": "fire_pr", "name": "燃烧瓶每回合", "unit": "", "invert": False, "digits": 2,
     "desc": "每回合丢出的燃烧瓶/燃烧弹数量。高说明你会用火清点、封路、逼走位，"
             "尤其是防守方用来拖延进点节奏。"},
    {"key": "he_pr", "name": "手雷每回合", "unit": "", "invert": False, "digits": 2,
     "desc": "每回合丢出的高爆手雷数量。高说明你会用雷磨血、清常见站位，"
             "为队友的对枪提前削掉血量优势。"},
]

# 维度 → 细项键（顺序即前端展示顺序）
DIMENSIONS: list[tuple[str, str, list[str]]] = [
    ("firepower", "火力", ["kpr_win", "nd_kill_pr", "kill_round_pct", "net_kill_24",
                          "win_contrib", "prevent_trade_pr", "multi_round_pct", "net_dmg_pr"]),
    ("entrying", "换命", ["tradeable_death_pr", "death_traded_pct", "bait_assist_pr",
                         "fd_traded_pct"]),
    ("trading", "补枪", ["trade_opp_pr", "trade_success_pct", "bait_kill_pct",
                        "assist_kill_pct"]),
    ("opening", "开局", ["fe_pct", "fk_order", "fk_time_s", "fires_pr"]),
    ("closing", "残局", ["survive_s", "postplant_alive_pct", "last_alive_pct", "clutch_24"]),
    ("sniping", "狙击", ["sniper_round_pct", "sniper_kill_pct", "awp_round_pct",
                        "awp_kill_pct"]),
    ("utility", "道具", ["smoke_pr", "flash_pr", "fire_pr", "he_pr"]),
]

ITEM_BY_KEY = {it["key"]: it for it in ITEMS}

# 因数据缺失而没有实现的细项（报告里要说明，前端可用灰色占位）
SKIPPED: list[dict] = []     # 目前没有因为数据缺失而放弃的细项


# ---------------------------------------------------------------------------
# 每场事件聚合
# ---------------------------------------------------------------------------
def _new_acc() -> dict:
    return defaultdict(float)


def _damage_valid_usable(conn: sqlite3.Connection, match_id: int) -> bool:
    """damage.valid 这一场能不能用（按场判断）。

    `valid` 是**有效伤害点数**（0~100 的整数），不是 0/1 标记 ——
    用户真实库 18,903 行里 valid 平均 26.27、0 个 NULL、只有 73 行是 0
    （死后补枪 / 友伤归零）。所以判据只能是「这列存不存在、有没有非空值」，
    绝不能拿 `valid=1` 当过滤条件（那会把 97% 的伤害丢掉）。
    老库（未重解析）没有这一列，才回退到 _legacy_damage 手工归一。
    """
    key = f"dmg_valid:{_db_file(conn)}:{match_id}"
    if key not in _COL_CACHE:
        ok = False
        try:
            r = conn.execute(
                "SELECT COUNT(*) n, SUM(CASE WHEN valid IS NULL THEN 1 ELSE 0 END) nul "
                "FROM damage WHERE match_id=?", (match_id,)).fetchone()
            n = int(r["n"] or 0) if r else 0
            nul = int(r["nul"] or 0) if r else 0
            ok = n > 0 and nul < n          # 有行、且不是全 NULL 就能用
        except sqlite3.Error:               # 没有 valid 列
            ok = False
        _COL_CACHE[key] = ok
    return bool(_COL_CACHE[key])


def _legacy_damage(rows: list[dict], kills: list[dict],
                   side_of: dict[int, str]) -> list[dict]:
    """老库的伤害归一：去友伤、去死后补枪、按剩余 100 血截断。

    与 ingest 里 valid 的口径对齐（拿不到精确血量，就用该回合累计伤害上限）。
    """
    death_tick: dict[int, int] = {}
    for k in kills:
        if k["vic"] and k["vic"] not in death_tick:
            death_tick[k["vic"]] = k["tick"]
    seen: dict[int, float] = defaultdict(float)
    out: list[dict] = []
    for d in rows:
        vic = d["vic"]
        if not vic or side_of.get(d["att"]) == side_of.get(vic):
            continue                       # 友伤 / 自伤 / 阵营不明
        dt = death_tick.get(vic)
        if dt is not None and d["tick"] > dt:
            continue                       # 死后补枪
        remain = 100.0 - seen[vic]
        if remain <= 0:
            continue
        v = min(float(d["d"]), remain)
        if v <= 0:
            continue
        seen[vic] += v
        out.append({**d, "d": v})
    return out


def _analyze_match(conn: sqlite3.Connection, match_id: int,
                   only_side: str | None = None) -> dict[int, dict]:
    """把一场比赛的事件流算成「每个玩家一份计数器」。

    返回 {steamid: acc}，acc 里全是原始计数 / 累加量，比值留到最后统一算
    （跨场合并时先加计数再相除，不能平均一堆比率）。
    """
    # bomb_tick 是新加的列（老库没有），单独 try 一次做兼容
    try:
        rows = conn.execute(
            "SELECT round, t_start, t_freeze, t_end, winner, a_side, a_win, bomb_tick "
            "FROM rounds WHERE match_id=? ORDER BY round", (match_id,)).fetchall()
    except sqlite3.Error:
        rows = conn.execute(
            "SELECT round, t_start, t_freeze, t_end, winner, a_side, a_win "
            "FROM rounds WHERE match_id=? ORDER BY round", (match_id,)).fetchall()
    rounds = {int(r["round"]): r for r in rows}
    if not rounds:
        return {}

    players: dict[int, dict] = {}
    for r in conn.execute(
            "SELECT steamid, first_side, COALESCE(joined_round,0) jr, "
            "COALESCE(left_round,0) lr FROM players WHERE match_id=?", (match_id,)):
        players[int(r["steamid"])] = {"fs": r["first_side"], "jr": int(r["jr"] or 0),
                                      "lr": int(r["lr"] or 0)}
    if not players:
        return {}

    accs: dict[int, dict] = {sid: _new_acc() for sid in players}

    # ---- 每回合阵营（一次算好，后面判同队全靠它）----
    side_map: dict[int, dict[int, str]] = {}
    for rnd in rounds:
        side_map[rnd] = {sid: _side_of(p["fs"], rnd) for sid, p in players.items()}

    # ---- 击杀事件 ----
    kills_by_round: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute(
            "SELECT round, tick, attacker_steamid att, victim_steamid vic, "
            "assister_steamid ast, weapon FROM kills WHERE match_id=? "
            "ORDER BY round, tick", (match_id,)):
        kills_by_round[int(r["round"])].append({
            "tick": int(r["tick"] or 0),
            # 自杀 / world 死亡：仍算一次死亡，但不算任何人的击杀
            "att": int(r["att"]) if r["att"] and int(r["att"]) != int(r["vic"] or 0) else None,
            "vic": int(r["vic"]) if r["vic"] else None,
            "ast": int(r["ast"]) if r["ast"] else None,
            "w": _wname(r["weapon"]),
        })

    # ---- 伤害事件（按回合→受害者，用于「无伤击杀」和「打伤助攻」）----
    # 新库直接用 valid 列的值（已按剩余血截断、剔友伤/死后补枪）；
    # valid 是**点数**不是标记位，绝不能写成 WHERE valid=1 当过滤条件。
    valid_ok = _damage_valid_usable(conn, match_id)
    dcol = "COALESCE(valid,0)" if valid_ok else "COALESCE(dmg_health,0)"
    dmg_by_round: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute(
            f"SELECT round, tick, attacker_steamid att, victim_steamid vic, weapon, "
            f"{dcol} d FROM damage WHERE match_id=? "
            f"ORDER BY round, tick", (match_id,)):
        if not r["att"]:
            continue                      # 环境伤害 / 摔落：不参与队友敌方判定
        dmg_by_round[int(r["round"])].append({
            "tick": int(r["tick"] or 0), "att": int(r["att"]),
            "vic": int(r["vic"]) if r["vic"] else None,
            "w": _wname(r["weapon"]), "d": float(r["d"] or 0),
        })

    # ---- 武器开火数 / 投掷物（场级）----
    fires = defaultdict(float)
    for r in conn.execute("SELECT steamid, COALESCE(SUM(fires),0) f FROM weapon_stat "
                          "WHERE match_id=? GROUP BY steamid", (match_id,)):
        fires[int(r["steamid"])] = float(r["f"] or 0)
    nades: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in conn.execute("SELECT steamid, type, COALESCE(n,0) n FROM grenade_use "
                          "WHERE match_id=?", (match_id,)):
        nades[int(r["steamid"])][str(r["type"] or "").lower()] += float(r["n"] or 0)

    for rnd, rinfo in rounds.items():
        smap = side_map[rnd]
        kl = kills_by_round.get(rnd, [])
        dmg = dmg_by_round.get(rnd, [])
        if not valid_ok:
            dmg = _legacy_damage(dmg, kl, smap)
        t_freeze = rinfo["t_freeze"]
        t_end = rinfo["t_end"]

        # 两队名单
        teams: dict[str, set[int]] = defaultdict(set)
        for sid, sd in smap.items():
            teams[sd].add(sid)

        # 本回合按受害者 / 攻击者索引
        d_by_vic: dict[int, list[dict]] = defaultdict(list)
        for d in dmg:
            if d["vic"]:
                d_by_vic[d["vic"]].append(d)
        k_by_att: dict[int, list[dict]] = defaultdict(list)
        for k in kl:
            if k["att"]:
                k_by_att[k["att"]].append(k)

        first = kl[0] if kl else None
        fe_people = {first["att"], first["vic"], first["ast"]} if first else set()

        for sid, p in players.items():
            acc = accs[sid]
            # 中途加入 / 提前退出的回合不算
            if rnd < p["jr"] or (p["lr"] and rnd > p["lr"]):
                continue
            # 分边统计：只算我在指定阵营的回合。smap 是按回合实时算的阵营，
            # 所以换边后会自动切到另一半，不会把整场混在一起。
            if only_side and smap.get(sid) != only_side:
                continue
            # 一场比赛里完全没出现在事件流里的玩家（挂机）仍然算回合，
            # 但为了避免把「没数据」当「没表现」，只要有一方完全无事件就照常记 0。
            side = smap.get(sid)
            if not side:
                continue
            mates = teams[side] - {sid}
            enemy_side = "CT" if side == "T" else "T"
            enemies = teams.get(enemy_side, set())

            acc["rounds"] += 1
            won = _round_win(rinfo, side)
            if won:
                acc["win_rounds"] += 1

            # 只把「敌人的命」算作击杀（队伤 / self-kill 已经从 att 侧清掉）
            my_kills = [k for k in k_by_att.get(sid, []) if k["vic"] in enemies]
            my_death = next((k for k in kl if k["vic"] == sid), None)
            my_death_tick = my_death["tick"] if my_death else None

            # --- 击杀侧 ---
            if my_kills:
                acc["kills"] += len(my_kills)
                if won:
                    acc["kills_win"] += len(my_kills)
                acc["kill_rounds"] += 1
                if len(my_kills) >= 2:
                    acc["multi_rounds"] += 1
                for k in my_kills:
                    w = k["w"]
                    if w in SNIPER_WEAPONS:
                        acc["kills_sniper"] += 1
                    if w in AWP_WEAPONS:
                        acc["kills_awp"] += 1
                    # 无伤击杀：这一枪之前我没被敌人打掉过血
                    before = [d for d in d_by_vic.get(sid, [])
                              if d["tick"] < k["tick"] and d["att"] != sid
                              and d["d"] > 0]
                    if not before:
                        acc["nd_kills"] += 1
                    # 阻止换人：我击杀后 5 秒内没有队友倒下
                    mate_deaths_after = [k2 for k2 in kl
                                         if k2["vic"] in mates
                                         and k["tick"] < k2["tick"] <= k["tick"] + TRADE_TICKS]
                    if not mate_deaths_after:
                        acc["prevent_kills"] += 1
                    # 诱饵击杀 / 复仇：队友刚死 5 秒内我杀掉凶手
                    for k2 in kl:
                        if (k2["vic"] in mates and k2["att"]
                                and k["tick"] - TRADE_TICKS <= k2["tick"] < k["tick"]
                                and k["vic"] == k2["att"]):
                            acc["bait_kills"] += 1
                            break
                # 队内首杀顺位：本回合队友里谁先开张
                my_first = min(k["tick"] for k in my_kills)
                rank = 1
                for m in mates:
                    mk = k_by_att.get(m, [])
                    if mk and min(k["tick"] for k in mk) < my_first:
                        rank += 1
                acc["fork_sum"] += rank
                acc["fork_n"] += 1

            # 狙击 / AWP 回合（本回合用该枪打过人或打出伤害）
            if any(k["w"] in SNIPER_WEAPONS for k in my_kills) or any(
                    d["w"] in SNIPER_WEAPONS for d in dmg if d["att"] == sid):
                acc["sniper_rounds"] += 1
            if any(k["w"] in AWP_WEAPONS for k in my_kills) or any(
                    d["w"] in AWP_WEAPONS for d in dmg if d["att"] == sid):
                acc["awp_rounds"] += 1

            # --- 死亡侧 ---
            if my_death:
                acc["deaths"] += 1
                dt = my_death["tick"]
                killer = my_death["att"]
                # 队友此时还活着吗
                mate_dead_alive = [m for m in mates
                                   if not any(k["vic"] == m and k["tick"] <= dt for k in kl)]
                if mate_dead_alive:
                    acc["tradeable_deaths"] += 1
                if killer:
                    traded = any(k["att"] in mates and k["vic"] == killer
                                 and dt < k["tick"] <= dt + TRADE_TICKS for k in kl)
                    if traded:
                        acc["death_traded"] += 1
                        acc["bait_assist"] += 1
                # 首死
                if first and first["vic"] == sid:
                    acc["first_deaths"] += 1
                    if killer and any(k["att"] in mates and k["vic"] == killer
                                      and dt < k["tick"] <= dt + TRADE_TICKS for k in kl):
                        acc["fd_traded"] += 1

            # --- 补枪侧 ---
            for k in kl:
                if k["vic"] in mates and k["att"] and k["att"] not in mates:
                    t = k["tick"]
                    if my_death_tick is None or t < my_death_tick:
                        acc["trade_opps"] += 1
                        if any(k2["att"] == sid and k2["vic"] == k["att"]
                               and t < k2["tick"] <= t + TRADE_TICKS for k2 in kl):
                            acc["trade_success"] += 1

            # --- 助攻击杀：队友的击杀里我给了助攻 / 打过伤害 ---
            for k in kl:
                if k["att"] and k["att"] in mates and k["vic"] in enemies:
                    if k["ast"] == sid or any(
                            d["att"] == sid and d["tick"] < k["tick"]
                            for d in d_by_vic.get(k["vic"], [])):
                        acc["assist_kills"] += 1

            # --- 首杀参与 / 首杀时间 ---
            if first and sid in fe_people:
                acc["fe_rounds"] += 1
                if t_freeze is not None:
                    acc["fk_time_sum"] += max(0.0, (first["tick"] - t_freeze) / TICKRATE)
                    acc["fk_time_n"] += 1

            # --- 存活时长 / 最后存活 ---
            if t_freeze is not None and t_end is not None:
                end_s = max(0.0, (t_end - t_freeze) / TICKRATE)
                if my_death_tick is not None:
                    s = max(0.0, min((my_death_tick - t_freeze) / TICKRATE, end_s))
                else:
                    s = end_s
                acc["survive_sec"] += s
                # 最后存活：我活着，或我是队里最后一个倒下的
                mate_deaths = [k["tick"] for k in kl if k["vic"] in mates]
                if my_death_tick is None or not mate_deaths or my_death_tick >= max(mate_deaths):
                    acc["last_alive"] += 1

            # --- 安放后存活：这回合有人安了包，我在安放那一刻是否还活着 ---
            bt = rinfo["bomb_tick"] if "bomb_tick" in rinfo.keys() else None
            if bt:
                acc["postplant_rounds"] += 1
                if my_death_tick is None or my_death_tick > bt:
                    acc["postplant_alive"] += 1

            # --- 残局：队友全倒、我还在、对面还有人 ---
            if mates:
                mate_deaths_t = [k["tick"] for k in kl if k["vic"] in mates]
                if len(mate_deaths_t) >= len(mates):        # 队友全灭
                    last_mate_t = max(mate_deaths_t)
                    i_was_there = my_death_tick is None or my_death_tick > last_mate_t
                    enemy_left = sum(1 for e in enemies if e not in
                                     {k["vic"] for k in kl if k["tick"] <= last_mate_t})
                    if i_was_there and enemy_left > 0:
                        acc["clutch_play"] += 1
                        # 残局胜 = 我是最后一个活着的人且本队赢下（我死了就不算我赢）
                        if won and my_death_tick is None:
                            acc["clutch_won"] += 1

            # --- 伤害：净伤害 + 胜利贡献 ---
            dmg_dealt = sum(d["d"] for d in dmg if d["att"] == sid and d["vic"] in enemies)
            dmg_taken = sum(d["d"] for d in dmg if d["vic"] == sid and d["att"] in enemies)
            acc["dmg_dealt"] += dmg_dealt
            acc["dmg_taken"] += dmg_taken

            if won:
                team_k = sum(1 for k in kl if k["att"] in teams[side])
                team_a = sum(1 for k in kl if k["ast"] and k["ast"] in teams[side]
                             and k["att"] in teams[side])
                mine = len(my_kills) + sum(1 for k in kl if k["ast"] == sid)
                if team_k + team_a:
                    w = 1.25 if my_death_tick is None else 1.0
                    acc["win_contrib_sum"] += mine / (team_k + team_a) * w
                    acc["win_contrib_w"] += w

            # --- 场级量摊到回合（fires / 投掷物）---
            # 这些在场结束后统一加，避免每回合重复累加

    # 场级数据：按玩家一次性灌进 acc
    for sid, acc in accs.items():
        acc["fires"] = fires.get(sid, 0.0)
        for t, n in nades.get(sid, {}).items():
            acc[f"nade_{t}"] = acc.get(f"nade_{t}", 0.0) + float(n)
    return {sid: dict(acc) for sid, acc in accs.items()}


def _add_acc(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        dst[k] = dst.get(k, 0.0) + v
    return dst


def _merge_accs(accs: list[dict]) -> dict:
    out: dict = defaultdict(float)
    for a in accs:
        _add_acc(out, a)
    return dict(out)


# ---------------------------------------------------------------------------
# 计数器 → 指标值
# ---------------------------------------------------------------------------
def _metrics(acc: dict) -> dict[str, float | None]:
    """把计数器转成每个细项的原始值（None = 该项没有可用样本）。"""
    g = lambda k: float(acc.get(k, 0.0) or 0.0)          # noqa: E731
    r = g("rounds")
    kills, deaths = g("kills"), g("deaths")

    m: dict[str, float | None] = {}
    m["kpr_win"] = _div(g("kills_win"), g("win_rounds"))
    m["nd_kill_pr"] = _div(g("nd_kills"), r)
    m["kill_round_pct"] = _pct(g("kill_rounds"), r)
    # HLTV 口径：只奖励产出，不扣代价（死亡由 Closing / 换命 承担）
    m["net_kill_24"] = (24.0 * kills / r) if r else None
    m["win_contrib"] = _pct(g("win_contrib_sum"), g("win_contrib_w"))
    m["prevent_trade_pr"] = _div(g("prevent_kills"), r)
    m["multi_round_pct"] = _pct(g("multi_rounds"), r)
    # HLTV 口径：same as above — 挨打不扣分
    m["net_dmg_pr"] = (g("dmg_dealt") / r) if r else None

    m["tradeable_death_pr"] = _div(g("tradeable_deaths"), r)
    m["death_traded_pct"] = _pct(g("death_traded"), deaths)
    m["bait_assist_pr"] = _div(g("bait_assist"), r)
    m["fd_traded_pct"] = _pct(g("fd_traded"), g("first_deaths"))

    m["trade_opp_pr"] = _div(g("trade_opps"), r)
    m["trade_success_pct"] = _pct(g("trade_success"), g("trade_opps"))
    m["bait_kill_pct"] = _pct(g("bait_kills"), kills)
    m["assist_kill_pct"] = _pct(g("assist_kills"), kills)

    m["fe_pct"] = _pct(g("fe_rounds"), r)
    m["fk_order"] = _div(g("fork_sum"), g("fork_n"))
    m["fk_time_s"] = _div(g("fk_time_sum"), g("fk_time_n"))
    m["fires_pr"] = _div(g("fires"), r)

    m["survive_s"] = _div(g("survive_sec"), r)
    m["last_alive_pct"] = _pct(g("last_alive"), r)
    m["clutch_24"] = (24.0 * g("clutch_won") / r) if r else None
    # 安放后存活：只在真有安包的回合里算，没安过包返回 None（界面显示 —）
    m["postplant_alive_pct"] = _pct(g("postplant_alive"), g("postplant_rounds"))

    m["sniper_round_pct"] = _pct(g("sniper_rounds"), r)
    m["sniper_kill_pct"] = _pct(g("kills_sniper"), kills)
    m["awp_round_pct"] = _pct(g("awp_rounds"), r)
    m["awp_kill_pct"] = _pct(g("kills_awp"), kills)

    m["smoke_pr"] = _div(g("nade_smoke"), r)
    m["flash_pr"] = _div(g("nade_flash"), r)
    m["fire_pr"] = _div(g("nade_fire") + g("nade_molotov") + g("nade_incgrenade")
                        + g("nade_incendiary"), r)
    m["he_pr"] = _div(g("nade_he"), r)
    return m


# ---------------------------------------------------------------------------
# 分布缓存
# ---------------------------------------------------------------------------
_BASE_CACHE: dict[Any, dict] = {}
_COL_CACHE: dict[str, bool] = {}       # 表结构探测（有没有某列 / 列能不能用）


def reset_cache() -> None:
    """清空分布缓存（换库 / 测试用）。"""
    _BASE_CACHE.clear()
    _COL_CACHE.clear()


def _db_file(conn: sqlite3.Connection) -> str:
    """库文件路径（换库时缓存自然失效）。"""
    if "self" not in _COL_CACHE:
        try:
            rows = conn.execute("PRAGMA database_list").fetchall()
            _COL_CACHE["self"] = str(rows[0]["file"] or ":memory:") if rows else ":memory:"
        except sqlite3.Error:
            _COL_CACHE["self"] = ":memory:"
    return str(_COL_CACHE["self"])


def _db_key(conn: sqlite3.Connection) -> str:
    return _db_file(conn)


def _fingerprint(conn: sqlite3.Connection) -> tuple:
    """数据指纹：场数 / 人场数 / 击杀数。任何一个变了就重算分布。"""
    def one(sql: str) -> int:
        r = conn.execute(sql).fetchone()
        return int(r[0] or 0) if r else 0
    return (one("SELECT COUNT(*) FROM matches"),
            one("SELECT COUNT(DISTINCT match_id || '-' || steamid) FROM pms"),
            one("SELECT COUNT(*) FROM kills"))


def baseline(conn: sqlite3.Connection, side: str | None = None) -> dict:
    """全体玩家-场次的每个细项分布：{key: {"mean", "std", "n"}}。

    side 给了就只统计各玩家在该阵营的回合（分边基准，跟分边统计口径一致）。
    只算一次，缓存在模块级 dict 里（键 = 库路径 + 数据指纹 + 阵营）。
    """
    key = (_db_key(conn), _fingerprint(conn), side or "")
    hit = _BASE_CACHE.get(key)
    if hit:
        return hit

    per: dict[str, list[float]] = defaultdict(list)
    sample = {"players": 0, "person_rounds": 0, "rounds": 0}
    try:
        # 基准只算「勾选（未排除）」的对局 —— 用户在界面取消勾选的 demo 不参与参照
        _ok = "JOIN matches m ON m.id={t}.match_id WHERE (m.excluded IS NULL OR m.excluded=0)"
        sample["players"] = int(conn.execute(
            "SELECT COUNT(DISTINCT p.steamid) FROM pms p "
            + _ok.format(t="p")).fetchone()[0] or 0)
        sample["person_rounds"] = int(conn.execute(
            "SELECT COUNT(*) FROM pms p " + _ok.format(t="p")).fetchone()[0] or 0)
        sample["rounds"] = int(conn.execute(
            "SELECT COUNT(*) FROM rounds r " + _ok.format(t="r")).fetchone()[0] or 0)
    except sqlite3.Error:
        pass
    # 官方基准按 Premier 分段分档（20k-25k / 25k+ 各一套，均值归一到 50）。
    # 我们只有一个库的几百名玩家，只能算一套基准 —— 在返回里说清楚，别冒充官方分档。
    sample["benchmark"] = (f"本库 {sample['players']} 名玩家（同分段，非官方分档基准）")

    # 逐场算，一场只解析一次（本场所有玩家共用）
    match_accs: dict[int, dict[int, dict]] = {}
    for r in conn.execute(
            "SELECT DISTINCT p.match_id FROM pms p JOIN matches m ON m.id=p.match_id "
            "WHERE (m.excluded IS NULL OR m.excluded=0) ORDER BY p.match_id"):
        mid = int(r[0])
        match_accs[mid] = _analyze_match(conn, mid, side)

    for row in conn.execute(
            "SELECT p.match_id, p.steamid, COALESCE(p.rounds,0) r FROM pms p "
            "JOIN matches m ON m.id=p.match_id "
            "WHERE m.excluded IS NULL OR m.excluded=0"):
        mid, sid = int(row["match_id"]), int(row["steamid"])
        acc = dict(match_accs.get(mid, {}).get(sid) or {})
        if not acc:
            continue
        if not acc.get("rounds") and row["r"]:
            acc["rounds"] = float(row["r"])       # 事件流缺失时退回 pms 回合数
        for k, v in _metrics(acc).items():
            if v is not None:
                per[k].append(float(v))

    stats = {}
    for k, vals in per.items():
        if len(vals) >= 2:
            stats[k] = {"mean": statistics.fmean(vals),
                        "std": statistics.pstdev(vals), "n": len(vals)}
        elif vals:
            stats[k] = {"mean": vals[0], "std": 0.0, "n": 1}
    out = {"stats": stats, "sample": sample, "matches": len(match_accs),
           "per_match": match_accs}
    _BASE_CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def _fmt(v: float | None, digits: int):
    if v is None:
        return None
    return round(float(v), digits)


def compute(conn: sqlite3.Connection, steamid: int, match_id: int | None = None,
            side: str | None = None) -> dict:
    """算某玩家的 Leetify 七维评分。

    match_id 给了就只算那一场；否则把该玩家所有（未被 exclude 的）场次合并 ——
    合并方式是先加计数器再相除，不是把各场比率平均。
    """
    where = "AND x.match_id=?" if match_id is not None else ""
    params: tuple = (steamid, match_id) if match_id is not None else (steamid,)
    rows = conn.execute(
        f"""SELECT x.match_id, COALESCE(x.rounds,0) rounds
            FROM pms x JOIN matches m ON m.id=x.match_id
            WHERE x.steamid=? AND (m.excluded IS NULL OR m.excluded=0) {where}
            ORDER BY m.played_at, x.match_id""", params).fetchall()

    base = baseline(conn, side)
    stats = base["stats"]
    # 火力不分边 —— HLTV 原文：分边比较的是 entrying / trading / opening / closing /
    # sniping / utility 六项，「Firepower is not part of it」。所以分边模式下另外备一份
    # 「全部回合」的基准与累加器，专给 firepower 维度用，其余六维照常用分边数据。
    base_all = baseline(conn, None) if side else base
    stats_all = base_all["stats"]

    target: dict = defaultdict(float)
    target_all: dict = defaultdict(float)
    used: list[int] = []
    for row in rows:
        mid = int(row["match_id"])
        acc = dict(base["per_match"].get(mid, {}).get(int(steamid)) or {})
        if not acc:                       # 该场没有事件（可能只有 pms 行）
            acc = {"rounds": float(row["rounds"] or 0)}
        elif not acc.get("rounds") and row["rounds"]:
            acc["rounds"] = float(row["rounds"])
        _add_acc(target, acc)
        if side:
            acc_all = dict(base_all["per_match"].get(mid, {}).get(int(steamid)) or {})
            if not acc_all:
                acc_all = {"rounds": float(row["rounds"] or 0)}
            elif not acc_all.get("rounds") and row["rounds"]:
                acc_all["rounds"] = float(row["rounds"])
            _add_acc(target_all, acc_all)
        used.append(mid)

    if match_id is not None and not used:
        return {"error": "该玩家在这场没有记录", "match_id": match_id,
                "steamid": steamid, "dimensions": [], "sample": base["sample"]}

    vals = _metrics(dict(target))
    vals_all = _metrics(dict(target_all)) if side else vals
    dims_out = []
    for dkey, dname, keys in DIMENSIONS:
        _fp = (dkey == "firepower" and bool(side))     # 火力在分边模式下走全量数据
        _v = vals_all if _fp else vals
        _st = stats_all if _fp else stats
        items, zs = [], []
        for k in keys:
            spec = ITEM_BY_KEY[k]
            v = _v.get(k)
            st = _st.get(k) or {}
            z = 0.0
            available = v is not None and (st.get("n") or 0) >= MIN_BASE and (st.get("std") or 0) > 1e-12
            if available:
                z = (float(v) - float(st["mean"])) / float(st["std"])
                if spec["invert"]:
                    z = -z
                z = max(-Z_CLAMP, min(Z_CLAMP, z))
                zs.append(z)
            items.append({
                "key": k, "name": spec["name"],
                "value": _fmt(v, spec["digits"]), "unit": spec["unit"],
                "z": round(z, 2) if available else None,
                "pct": round(_pct_of_z(z)) if available else None,
                "step": _step_of_z(z) if available else 0,
                "invert": spec["invert"],
                "base": ({"mean": round(st["mean"], 3), "std": round(st["std"], 3),
                          "n": st.get("n", 0)} if st else None),
                "desc": spec["desc"],
            })
        if zs:
            zc = _combine_zs(zs)                 # 官方合并公式（w 全 1.0）
            score = round(_pct_of_z(zc), 1)
        else:
            zc, score = 0.0, None

        dim = {"key": dkey, "name": dname, "score": score,
               "z": round(zc, 2), "pct": round(_pct_of_z(zc)) if zs else None,
               "items": items}

        # 道具维度不取普通平均：数量轨 × 质量轨的几何平均（官方口径）
        if dkey == "utility":
            qty, qual = _utility_tracks(target, score)
            dim["qty"] = round(qty, 1)
            dim["qual"] = qual
            dim["score"] = round(math.sqrt(max(qty, 0.0) * (qual or 0.0)), 1) if qual else None
            dim["pct"] = round(dim["score"]) if dim["score"] is not None else None
            dim["note"] = "数量轨 = min(每回合投掷数/3,1)^(2/3)×100；质量轨 = 细项 z 合并后转百分位；总分取两者几何平均"
        dims_out.append(dim)

    rr = int(target.get("rounds") or 0)
    return {
        "sample": dict(base["sample"], target_rounds=rr, target_matches=len(used),
                       benchmark=base["sample"].get("benchmark")),
        "steamid": int(steamid), "match_id": match_id, "matches": used,
        "dimensions": dims_out,
        "skipped": SKIPPED,
        # 原始值一并给出，方便前端做对照 / 排查
        "raw": {k: _fmt(v, 3) for k, v in vals.items()},
        "zscore": {"method": "bare",
                   "note": "细项 z=(v-mean)/std，反向指标取负，不按回合数缩放；"
                           "维度 z=Σ(w·z_i)/√Σw²（w=1.0），再转正态百分位"},
    }


def _utility_tracks(target: dict, qual: float | None) -> tuple[float, float | None]:
    """道具双轨：数量轨（每回合投掷数/3 的 2/3 次幂）+ 质量轨（细项 z 合并分）。

    数量轨把「每回合 3 颗」当作满值 1.0，再取 x^(2/3) 做凹曲线重映射：
    投得少的不会直接归零，投得多也不会线性吃满。这样 55 数量 + 60 质量
    得 57，而 100 数量 + 5 质量只有 22 —— 光会囤货没用，得投在点上。
    """
    r = float(target.get("rounds") or 0)
    if not r:
        return 0.0, qual
    g = lambda k: float(target.get(k, 0.0) or 0.0)        # noqa: E731
    thrown = (g("nade_smoke") + g("nade_flash") + g("nade_fire") + g("nade_molotov")
              + g("nade_incgrenade") + g("nade_incendiary") + g("nade_he"))
    frac = thrown / r / 3.0                                # 每回合 3 颗 = 1.0
    frac = max(0.0, min(1.0, frac))
    return frac ** (2.0 / 3.0) * 100.0, qual
