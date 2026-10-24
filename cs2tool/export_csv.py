"""导出完整对局数据 CSV —— 给 AI / Excel 直接读。

设计
----
1. 每行 = 一场比赛里的一个人（默认导出全部玩家，便于对手分析）
2. 文件头用 `#` 注释写清列的含义与统计口径（pandas: comment='#'；Excel 会显示成几行说明）
3. 只导出**已经按当前口径算好**的字段，不在导出时二次计算，保证与页面一致
4. 缺失值留空，不写 0 —— 与规范「样本不足显示 —」一致
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime

import store2

# 列定义：(字段名, 中文说明, 口径)
COLUMNS = [
    ("scope", "行类型", "avg_all=全期平均 avg_lastN=近N局平均 match=逐场明细 "
                        "map=按地图 weapon=按武器 utility=按道具 buytype=按购买类型 "
                        "clutch=按残局局面 spendcat=按花费类别 duel=按对枪档位"),
    ("dim", "维度", "该行描述哪个维度的明细（map/weapon/utility/buytype/clutch/spendcat/duel）"),
    ("dim_value", "维度值", "具体取值，如 de_dust2 / ak47 / flashbang / 1v3 / rifle / CT"),
    ("weapon_category", "武器类别", "gun=枪械 / melee=近战 / util=投掷物（仅 weapon 段）。"
                                "枪械才是「射击」，命中率与急停率只对 gun 有值"),
    ("match_id", "比赛编号", "数据库内部编号"),
    ("played_at", "对局时间", "demo 录制时间"),
    ("map", "地图", "match 行为 de_ 开头的官方地图名；avg_lastN 行为「近N场」标签"),
    ("window_requested", "请求窗口", "avg_lastN 行的 N（请求看最近多少场）；其他行为空"),
    ("window_actual", "实际窗口", "avg_lastN 行实际取到的场次；不足 N 时小于 window_requested"),
    ("window_status", "窗口状态", "ok=足量 / short=不足（样本少于请求）/ all=全期"),
    ("match_rounds", "总回合数", "该场比赛的完整回合数"),
    ("my_side", "我方阵营", "T 或 CT；未识别身份时为空"),
    ("win", "是否获胜", "1=赢 0=输；未识别身份时为空"),

    ("name", "玩家名", "游戏内显示名"),
    ("steamid", "SteamID", "64 位数字 ID"),
    ("is_me", "是否本人", "1=本人"),
    ("side", "阵营", "仅 match 行：该场我方阵营（T/CT）。汇总行与维度行留空——"
                     "阵营拆分请看 t_kills/ct_kills/t_dmg/ct_dmg 等独立列，不要把字典塞进这一列"),

    ("rounds", "个人计入回合", "正式行动开始时已在本方阵容的回合数，所有每回合指标的默认分母"),
    ("kills", "击杀", "有效敌方击杀事件求和"),
    ("deaths", "死亡", "含自杀与队友击杀"),
    ("assists", "助攻", "按固定助攻规则去重计数"),
    ("hs", "爆头击杀", "命中部位为头部的击杀"),
    ("dmg", "总伤害", "按剩余血量截断后的有效敌方伤害"),
    ("adr", "ADR", "总有效伤害 ÷ 个人计入回合数"),
    ("kast", "KAST", "满足击杀/助攻/存活/被换人任一条件的回合占比 ×100"),
    ("rating", "Rating 2.0", "0.0073*KAST+0.3591*KPR-0.5329*DPR+0.2372*Impact+0.0032*ADR+0.1587"),
    ("impact", "Impact", "2.13*KPR+0.42*APR-0.41"),
    ("kpr", "KPR", "击杀 ÷ 个人计入回合"),
    ("dpr", "DPR", "死亡 ÷ 个人计入回合"),
    ("apr", "APR", "助攻 ÷ 个人计入回合"),

    ("fk", "首杀", "回合首个击杀"),
    ("fd", "首死", "回合首个死亡"),
    ("t_fk", "T 方首杀", "作为 T 方时拿到的首杀数"),
    ("t_fd", "T 方首死", "作为 T 方时成为首个被杀者的次数"),
    ("ct_fk", "CT 方首杀", "作为 CT 方时拿到的首杀数"),
    ("ct_fd", "CT 方首死", "作为 CT 方时成为首个被杀者的次数"),
    ("mk2", "双杀回合", "单回合 2 杀的回合数"),
    ("mk3", "三杀回合", "单回合 3 杀的回合数"),
    ("mk4", "四杀及以上回合", "单回合 4 杀及以上的回合数"),

    ("trade_kills", "换人击杀", "队友刚死即被自己补掉的击杀"),
    ("traded_deaths", "被换人死亡", "自己死后队友立刻补掉凶手的次数"),

    ("clutch_played", "残局机会", "成为己方唯一存活者且对方仍有人的事件数"),
    ("clutch_won", "残局获胜", "残局机会中赢下的回合数"),
    ("clutch_win_rate", "残局成功率", "残局获胜 ÷ 残局机会 ×100"),

    ("fire_count", "开火次数", "weapon_fire 事件计数（一次扳机=一次开火）"),
    ("hit_count", "开火命中次数", "该次开火在 ±2 tick 内产生了伤害事件；按开火去重，非命中发数"),
    ("hit_rate", "开火命中率", "开火命中次数 ÷ 开火次数 ×100"),
    ("stop_shots", "阈值内低速开火", "枪械开火中速度 ≤34 units/s 的次数（急停的代理指标，不含投掷/挥刀）"),
    ("stop_rate", "阈值内低速开火率", "阈值内低速开火 ÷ 枪械开火数 ×100。分母只算枪械——weapon_fire 含投掷和挥刀，移动投掷是常态，混进去会污染指标"),
    ("gun_fire_count", "枪械开火数", "排除投掷物与近战后的开火数，是急停率的分母"),
    ("imprecise_shots", "超阈值速度开火", "开火瞬间速度 >34 units/s 的次数（还在滑步/跑动中开火）"),
    ("imprecise_rate", "超阈值速度开火率", "超阈值开火 ÷ 开火次数 ×100，等于 100-阈值内低速开火率"),

    ("penetrated_kills", "穿墙击杀", "击杀发生时子弹穿透了几何体"),
    ("thrusmoke_kills", "穿烟击杀", "击杀发生时视线穿过烟雾"),
    ("noscope_kills", "盲狙击杀", "狙击枪未开镜状态下完成的击杀数"),

    ("spent", "个人总支出", "item_events 中 purchase 的 cost 求和（含投掷物与装备）"),
    ("equip_value", "回合末装备价值", "回合结束时（结算前 -64 tick）该玩家身上的装备价值；"
                                   "本回合阵亡则为 0。不是「购买结束时」的快照——"
                                   "那个值 demo 里没现成字段，需要按 freeze time 末的 tick 另取"),
    ("equip_round_start", "场初继承装备", "回合开始时从上一回合保留的装备价值均值（团队 start_eq ÷ 5）"),
    ("round_number", "回合序号", "该场比赛内的回合编号，可与事件表直接关联（仅 econ_round 段）"),
    ("player_buy_type", "个人购买档", "按个人本回合实际花费分档："
                                     "eco<1000 / force<3200 / half<4500 / full≥4500"),
    ("team_buy_type", "团队购买档", "队伍层面的购买类别（pistol/eco/force/half/full），"
                                  "取自 economy 表同一阵营那一行"),

    ("plants", "安包次数", "finish_plant 事件计数"),
    ("defuses", "拆包次数", "defuse 事件计数"),
    ("survive_rounds", "存活回合", "回合结束时仍存活的回合数"),

    ("t_rounds", "T 方回合", "个人在 T 方的计入回合数"),
    ("ct_rounds", "CT 方回合", "个人在 CT 方的计入回合数"),
    ("t_kills", "T 方击杀", "T 方期间的击杀。不含自杀/环境死亡"),
    ("ct_kills", "CT 方击杀", "CT 方期间的击杀。不含自杀/环境死亡。注：极少数行 t_kills+ct_kills 会比 kills 多 1，源于 awpy 统计层与逐条事件在回合边界上的差异，累计分析请以 kills 为准"),
    ("t_dmg", "T 方伤害", "T 方期间的有效伤害"),
    ("ct_dmg", "CT 方伤害", "CT 方期间的有效伤害"),

    ("flash_assists", "闪光助攻", "致盲敌人后由队友完成的击杀"),
    ("flashes_thrown", "投出闪光", "闪光弹投出次数"),
    ("enemies_flashed", "致盲敌人", "被自己闪光致盲的敌方次数"),
    ("flash_duration", "致盲时长合计", "对敌方造成的致盲秒数总和"),
    ("utility_damage", "道具伤害", "手雷/燃烧弹造成的伤害"),
    ("flashed_count", "被闪次数", "被闪光弹致盲的次数（仅 received 段）"),
    ("flashed_duration", "被闪时长", "被致盲累计秒数（仅 received 段）"),
    ("flash_deaths", "闪白阵亡", "在致盲窗口内死亡的次数（仅 received 段）"),
    ("flash_by_enemy", "敌方闪", "被敌人闪的次数"),
    ("flash_by_teammate", "队友闪", "被队友闪的次数（含自己丢呲）"),
    ("util_taken", "吃到道具伤害", "作为受害方承受的手雷+燃烧伤害"),

    ("matches", "地图场次", "该地图打了几场（仅 map 段）"),
    ("win_rate", "胜率", "0-100（仅 map 段与汇总行）"),
    ("acc", "命中率", "命中÷开火×100（仅 weapon 段）"),
    ("buy", "购买数", "购买次数（仅 utility 段）"),
    ("pickup", "捡起数", "捡起次数（仅 utility 段）"),
    ("throw", "投出数", "真正投出去的次数（仅 utility 段）"),
    ("eff_pct", "闪光效率", "仅闪光弹有值。分子=至少致盲 1 名敌人的闪光弹数"
                            "（按投掷 tick 去重，同一颗闪致盲多人只算 1 颗，且剔除只闪到队友的）；"
                            "分母=该玩家投出的闪光弹总数（grenade_use）。"
                            "不用「致盲人次 ÷ 投出数」——一颗闪可以闪多人，那样会算出 90%+ 的虚高值"),
    ("damage_per_round", "局均伤害", "该类别每回合伤害（仅 weapon/utility 段）"),
    ("save_count", "保枪次数", "该局面下保枪次数（仅 clutch 段）"),
    ("cost", "花费金额", "该类别花掉的钱（仅 spendcat 段）"),
    ("pct", "占比", "0-100（仅 spendcat/duel 段）"),

    ("parser_version", "解析器版本", "产出该行数据的 demo 解析器版本（awpy / demoparser2）"),
    ("metric_schema_version", "指标版本", "统计口径与公式版本；公式变更时递增，旧数据不可直接混用"),
    ("export_schema_version", "导出结构版本", "CSV 字段结构版本；增删列时递增"),
]


# 回合结束原因 → 中文（与数据页 07 分节一致）
REASON_CN = {
    "terrorists_win": "全歼 CT",
    "ct_win": "全歼 T",
    "target_bombed": "炸弹爆炸",
    "bomb_defused": "拆包成功",
    "target_saved": "时间耗尽",
}


def _pct(a, b):
    if not b:
        return ""
    return round(100.0 * (a or 0) / b, 2)


def build_csv(db_path: str, only_me: bool = False, match_ids: list[int] | None = None,
              windows: tuple[int, ...] = (10, 20, 50),
              exporter: str = "") -> str:
    """生成 CSV：汇总行（全期 + 近 N 局平均）+ 逐场明细。

    结构
    ----
    scope 列区分两类行：
      avg_all / avg_last10 / avg_last20 / avg_last50  → 目标玩家的聚合（比率按总分子除总分母重算）
      match                                           → 逐场明细，含该场全部玩家

    明细只保留最近 max(windows) 场，避免文件无限膨胀；汇总行覆盖全期。
    """
    import clutch
    import stats_api
    import settings as _S

    # 三个版本各管一件事，别混成一个字段：
    # parser = 读 demo 的库；metric = 统计口径与公式；export = 这份 CSV 的列结构
    PARSER_VERSION = "awpy-3.1.1+demoparser2-0.42.0"
    METRIC_SCHEMA_VERSION = "m2"      # 2026-10 修过 a_side 换边、装备人均、平局语义
    EXPORT_SCHEMA_VERSION = "e4"      # 2026-10 加 scope 列、汇总行、窗口切片、只读标识
    conn = store2.connect(db_path)

    # ---- 目标玩家：优先 settings 里的 my_steamid，其次库里的 is_me
    me_sid = None
    try:
        v = _S.get("my_steamid")
        me_sid = int(v) if v else None
    except Exception:
        me_sid = None
    if not me_sid:
        r = conn.execute("SELECT steamid FROM players WHERE is_me=1 ORDER BY match_id DESC LIMIT 1").fetchone()
        me_sid = int(r["steamid"]) if r else None
    me_name = ""
    if me_sid:
        r = conn.execute("SELECT name FROM players WHERE steamid=? ORDER BY match_id DESC LIMIT 1",
                         (me_sid,)).fetchone()
        me_name = (r["name"] if r else "") or ""
    if not me_name:
        me_name = exporter or "目标玩家"

    # ---- 汇总行（只有目标玩家）
    avg_lines: list[dict] = []
    recent_ids: list[int] = []
    if me_sid:
        me_rows = stats_api.player_rows(conn, me_sid)
        if match_ids:
            keep = set(match_ids)
            me_rows = [r for r in me_rows if r["match_id"] in keep]
        if me_rows:
            # player_rows 已按 played_at 升序，切片即「最近 N 场」
            n_total = len(me_rows)
            for scope, sub, want in [("avg_all", me_rows, n_total)] + [
                    (f"avg_last{n}", me_rows[-n:], n) for n in windows]:
                if not sub:
                    continue
                a = stats_api._agg(sub)
                # 数据不足时如实标注，避免 10/20/50 三行长得一模一样被误读成三个不同区间
                if scope == "avg_all":
                    lbl = f"全期{n_total}场"
                    w_req = w_act = ""
                    w_st = "all"
                else:
                    lbl = (f"近{len(sub)}场（不足{want}）" if n_total < want
                           else f"近{len(sub)}场")
                    w_req, w_act = want, len(sub)
                    w_st = "short" if n_total < want else "ok"
                row = {"scope": scope, "name": me_name, "steamid": me_sid, "is_me": 1,
                       "map": lbl,
                       "window_requested": w_req, "window_actual": w_act,
                       "window_status": w_st,
                       "match_id": "", "played_at": "", "match_rounds": "",
                       "my_side": "", "win": "", "side": ""}
                row.update(a)
                # _agg 把阵营拆分放在 side 字典里（{'T': {...}, 'CT': {...}}）。
                # 不能整坨塞进 CSV 的 side 列——那一列是「阵营」，不是数据容器。
                # 拆到标准的 t_* / ct_* 列，side 列保持空。
                _sd = a.get("side") or {}
                row["side"] = ""
                if isinstance(_sd, dict):
                    for _k in ("T", "CT"):
                        _p = _sd.get(_k) or {}
                        _pre = "t_" if _k == "T" else "ct_"
                        for _f in ("rounds", "kills", "deaths", "dmg"):
                            _src = "rounds" if _f == "rounds" else _f
                            if _p.get(_src) is not None:
                                row[_pre + _f] = _p[_src]
                # 残局：每一行都按「该行对应的场次」用同一个函数重算。
                # 之前只有 avg_all 换了口径、窗口行还在用 pms 的 awpy 值，
                # 结果全期 7 次、近 10/20/50 都是 10 次，同口径却给出两个答案。
                try:
                    _cb = clutch.build(conn, me_sid, [r["match_id"] for r in sub])
                    _cc = _cb.get("clutch") or {}
                    row["clutch_played"] = _cc.get("played")
                    row["clutch_won"] = _cc.get("won")
                except Exception:
                    pass
                # _agg 不产出的派生列，汇总行要自己补，否则这四列在汇总行是空的
                row["t_kills"] = a.get("tkills")
                row["clutch_win_rate"] = _pct(a.get("clutch_won"), a.get("clutch_played"))
                row["hit_rate"] = _pct(a.get("hit_count"), a.get("fire_count"))
                row["imprecise_rate"] = _pct(a.get("imprecise_shots"), a.get("gun_fire_count"))
                row["stop_rate"] = _pct(a.get("stop_shots"), a.get("gun_fire_count"))
                # 道具：这四列原来只有明细行有值、汇总行是空的，看起来像
                # 「汇总全 0、明细非零」的数据矛盾。现在 utility() 支持按场次切片，
                # 每一行都按它自己的 sub 重新数，不是拿全期数除场次。
                try:
                    _ut = stats_api.utility(conn, me_sid, [x["match_id"] for x in sub])
                    _fl = _ut.get("flash") or {}
                    _he = _ut.get("he") or {}
                    _fi = _ut.get("fire") or {}
                    row["flashes_thrown"] = _fl.get("throw")
                    row["enemies_flashed"] = _fl.get("enemies_flashed")
                    row["flash_duration"] = _fl.get("duration")
                    row["utility_damage"] = ((_he.get("damage") or 0)
                                             + (_fi.get("damage") or 0))
                except Exception:
                    pass
                row["parser_version"] = PARSER_VERSION
                row["metric_schema_version"] = METRIC_SCHEMA_VERSION
                row["export_schema_version"] = EXPORT_SCHEMA_VERSION
                avg_lines.append(row)
            window_ids = [r["match_id"] for r in me_rows[-max(windows):]]
            recent_ids = window_ids

    # ---- 明细段：把数据页上「按地图/武器/道具/购买类型/花费类别/残局/多杀/结束原因」
    # 展开的统计也搬进来，全部按目标玩家、全期口径（与页面一致，不随窗口变化）
    dim_lines: list[dict] = []
    if me_sid:
        base = {"name": me_name, "steamid": me_sid, "is_me": 1,
                "match_id": "", "played_at": "", "my_side": "", "win": "", "side": ""}
        try:
            ov = stats_api.overview(conn, me_sid)
        except Exception:
            ov = {}
        for m in (ov.get("by_map") or []):
            r = dict(base)
            r.update(m)
            r.update(scope="map", dim="map", dim_value=m.get("map"),
                     matches=m.get("matches"))
            # by_map 的行同样来自 _agg：阵营拆分在 side 字典里、T 方击杀键名是 tkills。
            # 不映射的话 t_kills 整列为空，side 列还会塞进一坨 Python 字典字符串。
            _sd = r.get("side") or {}
            r["side"] = ""
            r["t_kills"] = m.get("tkills")
            try:
                _mm = [x["id"] for x in conn.execute(
                    "SELECT id FROM matches WHERE map=?", (m.get("map"),))]
                _cc2 = (clutch.build(conn, me_sid, _mm).get("clutch") or {})
                r["clutch_played"] = _cc2.get("played")
                r["clutch_won"] = _cc2.get("won")
                r["clutch_win_rate"] = _pct(_cc2.get("won"), _cc2.get("played"))
            except Exception:
                pass
            if isinstance(_sd, dict):
                for _k in ("T", "CT"):
                    _p = _sd.get(_k) or {}
                    _pre = "t_" if _k == "T" else "ct_"
                    for _f in ("rounds", "kills", "deaths", "dmg"):
                        if _p.get(_f) is not None:
                            r[_pre + _f] = _p[_f]
            dim_lines.append(r)
        cl = ((ov.get("clutch") or {}).get("clutch") or {})
        for size, d in (cl.get("by_size") or {}).items():
            pl = d.get("played") or 0
            wn = d.get("won") or 0
            # 列名要和汇总行一致（clutch_played / clutch_won / clutch_win_rate），
            # 否则 1vN 这五行在表里只有个 rounds/win_rate，看不出「打几次赢几次」。
            dim_lines.append({**base, "scope": "clutch", "dim": "clutch_size",
                              "dim_value": size,
                              "rounds": pl,
                              "clutch_played": pl, "clutch_won": wn,
                              "clutch_win_rate": (round(wn / pl * 100, 1) if pl else None),
                              "win_rate": (round(wn / pl * 100, 1) if pl else None),
                              "kills": d.get("kills"), "save_count": d.get("saves"),
                              "cost": d.get("save_eq")})
        try:
            det = stats_api.detail(conn, me_sid)
        except Exception:
            det = {}
        for w in (det.get("weapons") or []):
            _g = (w.get("cat") == "gun")
            dim_lines.append({**base, "scope": "weapon", "dim": "weapon",
                              "dim_value": w.get("w"),
                              "weapon_category": w.get("cat"),
                              "kills": w.get("n"), "hs": w.get("hs"),
                              "fire_count": w.get("fires"), "hit_count": w.get("hits"),
                              # 命中率/急停只对枪械有意义：投掷物和刀也触发 weapon_fire，
                              # 但那不是「射击」，给数字只会误导
                              "acc": w.get("acc") if _g else None,
                              "dmg": w.get("dmg"),
                              "damage_per_round": w.get("dmg_per_round"),
                              "imprecise_shots": w.get("imp") if _g else None,
                              "stop_shots": (((w.get("fires") or 0) - (w.get("imp") or 0))
                                             if (_g and w.get("fires")) else None),
                              "penetrated_kills": w.get("pen"),
                              "thrusmoke_kills": w.get("smoke"),
                              "noscope_kills": w.get("noscope")})
        # 差额事件标成「未归属」，不静默丢弃——
        # 命中用 awpy 的统计口径、武器明细用 tick 配对口径，天然差几十次；
        # 不写出来，读表的人会以为武器段合计就该等于总览。
        try:
            _tw = stats_api.overview(conn, me_sid).get("total") or {}
            _wh = sum((w.get("hits") or 0) for w in (det.get("weapons") or []))
            _miss = (_tw.get("hit_count") or 0) - _wh
            if _miss > 0:
                dim_lines.append({**base, "scope": "weapon", "dim": "weapon",
                                  "dim_value": "(未归属)", "weapon_category": "unknown",
                                  "hit_count": _miss,
                                  "acc": None, "stop_shots": None})
        except Exception:
            pass
        for k, n in (det.get("multi") or {}).items():
            dim_lines.append({**base, "scope": "multi", "dim": "multi",
                              "dim_value": f"{k}K", "rounds": n})
        try:
            ut = stats_api.utility(conn, me_sid)
        except Exception:
            ut = {}
        for k, d in ut.items():
            if not isinstance(d, dict):
                continue
            dim_lines.append({**base, "scope": "utility", "dim": "utility",
                              "dim_value": d.get("name") or k,
                              "buy": d.get("buy"), "pickup": d.get("pickup"),
                              "throw": d.get("throw"), "eff_pct": d.get("eff_pct"),
                              "flash_duration": d.get("duration"),
                              "utility_damage": d.get("damage"),
                              "damage_per_round": d.get("dmg_per_round"),
                              "enemies_flashed": d.get("enemies_flashed")})
        try:
            ec = stats_api.econ_stats(conn, me_sid)
        except Exception:
            ec = {}
        for b in (ec.get("buy") or []):
            dim_lines.append({**base, "scope": "buytype", "dim": "buytype",
                              "dim_value": b.get("type"), "rounds": b.get("n"),
                              "win_rate": b.get("wr"), "equip_value": b.get("eq")})
        for sd, items in (ec.get("spend_mix") or {}).items():
            for x in (items or []):
                dim_lines.append({**base, "scope": "spendcat", "dim": "spendcat",
                                  "dim_value": f"{sd}/{x.get('cat')}",
                                  "cost": x.get("cost"), "pct": x.get("pct")})
        for x in (ec.get("reasons") or []):
            dim_lines.append({**base, "scope": "reason", "dim": "reason",
                              "dim_value": REASON_CN.get(x.get("r"), x.get("r")),
                              "rounds": x.get("n")})

        # 受闪 / 吃道具伤害：全部 / T / CT 三行
        # 方向与 utility 段相反——那是「我投出去的」，这里是「我吃到的」
        rv = (ov.get("received") or {})
        for key in ("all", "T", "CT"):
            f = (rv.get("flash") or {}).get(key) or {}
            u = (rv.get("util_taken") or {}).get(key) or {}
            if not f and not u:
                continue
            dim_lines.append({
                **base, "scope": "received", "dim": "received",
                "dim_value": ("全部" if key == "all" else key),
                "my_side": ("" if key == "all" else key),
                "rounds": (rv.get("rounds") or {}).get(key),
                "flashed_count": f.get("count"),
                "flashed_duration": f.get("duration"),
                "flash_deaths": f.get("deaths"),
                "flash_by_enemy": f.get("by_enemy"),
                "flash_by_teammate": f.get("by_teammate"),
                "util_taken": u.get("total"),
                "damage_per_round": u.get("per_round"),
            })

        # 逐回合经济：统一走 stats_api.econ_rounds()。
        # 之前这段只存在于导出器里，接口一行都拿不到；现在两边同一个实现。
        try:
            for x in stats_api.econ_rounds(conn, me_sid, match_ids or None):
                dim_lines.append({
                    **base, "scope": "econ_round", "dim": "econ_round",
                    "dim_value": f"{x['map']} R{x['round_number']}",
                    "match_id": x["match_id"], "played_at": x["played_at"],
                    "map": x["map"], "my_side": x["my_side"],
                    "round_number": x["round_number"],
                    "win": 1 if x["win"] else 0,
                    "rounds": 1,
                    # 个人口径
                    "spent": x["player_spend"],
                    "player_buy_type": x["player_buy_type"],
                    "equip_value": x["player_equipment_value_end"],
                    "equip_round_start": x["player_equipment_value_round_start"],
                    "save_count": 1 if x["saved"] else 0,
                    # 团队口径
                    "team_buy_type": x["team_buy_type"],
                    "cost": x["team_spend"],
                })
        except Exception:
            pass

    where, args = ["(m.excluded IS NULL OR m.excluded=0)"], []
    if only_me:
        where.append("p.is_me=1")
    if match_ids:
        where.append("x.match_id IN (%s)" % ",".join("?" * len(match_ids)))
        args.extend(match_ids)
    if recent_ids:
        where.append("x.match_id IN (%s)" % ",".join("?" * len(recent_ids)))
        args.extend(recent_ids)
    wsql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = conn.execute(f"""
        SELECT x.*, m.map, m.played_at, p.name, p.is_me, p.first_side AS side,
               (SELECT COUNT(*) FROM rounds r WHERE r.match_id=x.match_id) AS match_rounds
        FROM pms x
        JOIN matches m ON m.id = x.match_id
        JOIN players p ON p.steamid = x.steamid AND p.match_id = x.match_id
        {wsql}
        ORDER BY x.match_id DESC, p.is_me DESC, x.adr DESC
    """, args).fetchall()

    # 每场的我方胜负：直接用 a_win 求和。
    # 不能写 WHERE a_side=my_side —— a_side 本身已经是「每回合我方阵营」，
    # 换边后会翻，那样只统计到上半场（曾经把 13:9 的胜场记成负场）。
    side_win: dict[int, tuple[str, int | None]] = {}
    for mid in {r["match_id"] for r in rows}:
        m = conn.execute("""SELECT first_side AS side FROM players
                             WHERE match_id=? AND is_me=1 LIMIT 1""", (mid,)).fetchone()
        my_side = m["side"] if m else None
        win = None
        tot = conn.execute("SELECT COUNT(*) FROM rounds WHERE match_id=?", (mid,)).fetchone()[0]
        w = conn.execute("SELECT COALESCE(SUM(a_win),0) FROM rounds WHERE match_id=?",
                         (mid,)).fetchone()[0]
        if tot:
            if w * 2 > tot:
                win = 1
            elif w * 2 < tot:
                win = 0
            else:
                win = -1          # 平局：12:12 打满常规时间，或加时后平分
        side_win[mid] = (my_side or "", win)

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 头部：先声明这份文件是什么、给谁、能不能改
    buf.write("# ============================================================\n")
    buf.write("# Cross-Section —— 玩家技术综合分析数据导出\n")
    buf.write("# ============================================================\n")
    buf.write(f"# 目标玩家 : {me_name} ({me_sid or '未识别'})\n")
    buf.write("# 用途     : 该玩家的长期技术水平综合分析（趋势、地图/阵营表现、武器与道具效率、\n")
    buf.write("#            经济决策、残局处理）。本文件供人阅读或供 AI 作分析输入。\n")
    buf.write("#\n")
    buf.write("# ------------------------------------------------------------\n")
    buf.write("# 【给 AI 的指令】以下分析只用本文件内的数据，不要引入外部信息。\n")
    buf.write("#   1. 水平定位：结合 ADR / KAST / Rating / Impact 判断档次与稳定性\n")
    buf.write("#   2. 强项与短板：哪些指标明显突出、哪些明显偏低，短板可能的成因\n")
    buf.write("#   3. 阵营差异：T 与 CT 哪一侧更强，差距具体落在哪些指标上\n")
    buf.write("#   4. 地图特征：哪些图明显打得好、哪些该回避；样本量够不够支撑这个结论\n")
    buf.write("#   5. 对枪与经济：对枪胜率和武器选择是否匹配，经济局的决策是否合理\n")
    buf.write("#   6. 改进建议：按优先级排列，每一条都必须指向文件里的具体数字\n")
    buf.write("# 硬性要求：\n")
    buf.write("#   · 引用任何数字之前先读下面的「字段口径」，避免误读\n")
    buf.write("#     （例如经济数值是全队 5 人合计，不是个人）\n")
    buf.write("#   · 场次不足 5 场时不要下强结论，直接写「样本不足，无法判断」\n")
    buf.write("#   · 不要编造文件里没有的信息；缺失就写「数据中未提供」\n")
    buf.write("# ------------------------------------------------------------\n")
    buf.write(f"# 数据范围 : 汇总={len(avg_lines)} 行（全期 + 近 {'/'.join(str(n) for n in windows)} 局平均）\n")
    buf.write(f"#            维度明细={len(dim_lines)} 行（地图/武器/道具/购买类型/花费类别/残局/多杀/结束原因，全期口径）\n")
    buf.write(f"#            逐场明细={len(rows)} 行（近 {max(windows)} 局内每场每名玩家一行，含对手与队友）\n")
    buf.write("#\n")
    buf.write("# 说明     : 本文档覆盖数据页上的全部统计区块。维度明细与页面口径一致（全期），\n")
    buf.write("#            不受「近 N 局」窗口影响；需要随时间对比请看 avg_* 汇总行。\n")
    buf.write("#\n")
    buf.write("# ---------- 文件属性 ----------\n")
    buf.write("# 生成器   : Cross-Section v6.2.4（本地 CS2 demo 分析工具）\n")
    buf.write(f"# 导出时间 : {now}\n")
    buf.write(f"# 导出者   : {exporter or me_name}\n")
    buf.write(f"# 解析器   : {PARSER_VERSION}\n")
    buf.write(f"# 指标版本 : {METRIC_SCHEMA_VERSION}（口径与公式）\n")
    buf.write(f"# 结构版本 : {EXPORT_SCHEMA_VERSION}（列结构）\n")
    buf.write("# 访问权限 : READ-ONLY —— 本文件是某一时刻的静态快照，不随对局更新。\n")
    buf.write("#            如需最新数据请重新导出；如需逐回合/逐事件明细请用本地 API\n")
    buf.write("#            (/api/v1/schema 查看表结构，/api/v1/query?sql= 执行只读查询)。\n")
    buf.write("#\n")
    buf.write("# ---------- 行类型（scope 列）----------\n")
    buf.write("#   avg_all     目标玩家全期平均（比率按总分子÷总分母重算，不是逐场平均）\n")
    buf.write("#   avg_lastN   目标玩家最近 N 局平均（数据不足 N 场时 dim 标注「不足N」）\n")
    buf.write("#   map         按地图：场次/胜率/各类场均指标\n")
    buf.write("#   weapon      按武器：击杀/爆头/开火/命中/命中率/穿墙/穿烟/盲狙\n")
    buf.write("#   utility     按道具：购买/捡起/投出/伤害/致盲/闪光效率\n")
    buf.write("#   buytype     按购买类型：回合数/胜率/人均装备\n")
    buf.write("#   spendcat    按花费类别：dim_value 形如 CT/rifle、T/util\n")
    buf.write("#   clutch      按残局局面：1v1~1v5 的机会数/胜率/击杀/保枪\n")
    buf.write("#   multi       按多杀：2K/3K/4K/5K 的回合数\n")
    buf.write("#   reason      按回合结束原因：全歼/炸弹爆炸/拆包/时间耗尽\n")
    buf.write("#   econ_round  逐回合经济：个人本回合花费/装备/是否保经济 与 团队购买档位/团队花费 并列\n")
    buf.write("#   received    受闪与受道具伤害：全部/T/CT 三行（方向与 utility 相反，这里是我吃到的）\n")
    buf.write("#   match       逐场明细，该场全部玩家各一行\n")
    buf.write("#\n")
    buf.write("# ---------- 重要口径 ----------\n")
    buf.write("#   1. 伤害按剩余血量截断：满血 100 被爆头记 100 而不是 120，直接对 dmg_health 求和会虚高约 40%\n")
    buf.write("#   2. 比率类字段均为「总分子 ÷ 总分母」，不是逐场百分比取平均\n")
    buf.write("#   3. 空值表示无样本或不可计算，不等同于 0；0 才表示确实为零\n")
    buf.write("#   4. 开火命中率按「开火次数」为分母：一次开火即使命中多颗弹丸也只算一次命中；\n")
    buf.write("#      霰弹枪单次开火可产生多颗弹丸的伤害事件，其命中率天然偏高，与步枪不可直接横比\n")
    buf.write("#   5. 急停判定用开火瞬间的速度（≤34 units/s 算停住），速度是绝对量，跨场可比。\n")
    buf.write("#      不使用 awpy 的 shots.inaccuracy —— 那是武器实体的 m_fAccuracyPenalty\n")
    buf.write("#      （连发累积的精度惩罚），官方注释写明 CS2 不把完整 inaccuracy 写进网络流，\n")
    buf.write("#      实测也与移动速度无关（速度 0-5 与 120+ 的开火，该值中位数几乎相同）。\n")
    buf.write("#   6. Rating 2.0 / Impact 使用 HLTV 公开公式，与 HLTV 官方数值可能存在小数差异\n")
    buf.write("#   7. noscope_kills 来自 player_death 事件的 noscope 字段（引擎在击杀结算时判定），\n")
    buf.write("#      不是从开火瞬间的开镜状态推导。本数据集全部为 0，即这几局确实没有盲狙击杀。\n")
    buf.write("#      注意：不能改用 shots.scoped 去推 —— CS2 的 AWP 开火后会立即自动退镜，\n")
    buf.write("#      按开火那一 tick 读到的永远是未开镜状态（实测 41 次 AWP 开火全为 False）。\n")
    buf.write("#   8. win 列：1=胜 0=负 -1=平局（12:12 打满常规时间或加时后平分）\n")
    buf.write("#\n")
    buf.write("# ---------- 列说明 ----------\n")
    for f, cn, note in COLUMNS:
        buf.write(f"# {f:<24s} {cn}｜{note}\n")
    buf.write("\n")

    w.writerow([c[0] for c in COLUMNS])

    for r in avg_lines:
        w.writerow(["" if r.get(f) is None else r.get(f) for f, _c, _n in COLUMNS])

    for r in dim_lines:
        w.writerow(["" if r.get(f) is None else r.get(f) for f, _c, _n in COLUMNS])

    for r in rows:
        my_side, win = side_win.get(r["match_id"], ("", None))
        rec = dict(r)
        rec["scope"] = "match"
        rec["my_side"] = my_side
        rec["win"] = "" if win is None else win
        rec["clutch_win_rate"] = _pct(r["clutch_won"], r["clutch_played"])
        rec["hit_rate"] = _pct(r["hit_count"], r["fire_count"])
        rec["imprecise_rate"] = _pct(r["imprecise_shots"], rec.get("gun_fire_count"))
        rec["stop_rate"] = _pct(rec.get("stop_shots"), rec.get("gun_fire_count"))
        # 列名不一致的历史遗留：pms 表里 T 方击杀叫 tkills（无下划线），
        # 导出字段叫 t_kills。不映射的话整列永远取空。
        rec["t_kills"] = r["tkills"]
        rec["parser_version"] = PARSER_VERSION
        rec["metric_schema_version"] = METRIC_SCHEMA_VERSION
        rec["export_schema_version"] = EXPORT_SCHEMA_VERSION
        w.writerow(["" if rec.get(f) is None else rec.get(f) for f, _c, _n in COLUMNS])

    return buf.getvalue()


def write_csv(db_path: str, out_path: str, only_me: bool = False,
              match_ids: list[int] | None = None, exporter: str = "") -> str:
    text = build_csv(db_path, only_me=only_me, match_ids=match_ids, exporter=exporter)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(text)
    return out_path


# ---------------- 图池统计 ----------------
def map_pool(db_path: str) -> list[dict]:
    """每张地图的游玩次数与胜率（只统计本人参与的比赛）。"""
    conn = store2.connect(db_path)
    rows = conn.execute("""
        SELECT m.id, m.map, m.played_at,
               (SELECT COUNT(*) FROM rounds r WHERE r.match_id=m.id) AS rounds,
               (SELECT first_side FROM players WHERE match_id=m.id AND is_me=1 LIMIT 1) AS my_side
        FROM matches m
        ORDER BY m.played_at
    """).fetchall()

    by_map: dict[str, dict] = {}
    for r in rows:
        mp = r["map"] or "unknown"
        e = by_map.setdefault(mp, {"map": mp, "played": 0, "win": 0, "loss": 0,
                                   "rounds": 0, "history": []})
        e["played"] += 1
        e["rounds"] += r["rounds"] or 0
        win = None
        # 我方赢了几回合：a_win 记的是「A 队（上半场打 T 的那队）赢没赢」，
        # 所以我在 A 队（首回合 T）就直接取 a_win，在 B 队（首回合 CT）要取反。
        # 旧写法是拿 my_side 去匹配 a_side，在 B 队的场次会命中的是下半场、
        # 而且胜负是反的 —— 5 场里 3 场会算错。
        if r["my_side"]:
            row = conn.execute(
                "SELECT SUM(a_win) AS aw, COUNT(*) AS tot FROM rounds WHERE match_id=?",
                (r["id"],)).fetchone()
            aw, tot = (row["aw"] or 0), (row["tot"] or 0)
            if tot:
                my_wins = aw if r["my_side"] == "T" else tot - aw
                if my_wins * 2 > tot:
                    win = 1
                elif my_wins * 2 == tot:
                    win = None        # 平局不计入胜率（和 Demo 页一致）
                else:
                    win = 0
        if win == 1:
            e["win"] += 1
        elif win == 0:
            e["loss"] += 1
        e["history"].append({"match_id": r["id"], "played_at": r["played_at"],
                             "rounds": r["rounds"], "win": win})

    out = []
    for e in by_map.values():
        decided = e["win"] + e["loss"]
        e["decided"] = decided
        e["win_rate"] = round(100.0 * e["win"] / decided, 1) if decided else None
        e["avg_rounds"] = round(e["rounds"] / e["played"], 1) if e["played"] else None

        # 环比：按时间顺序把该图的对局分成「前段 / 近段」，各至少 2 场才给结论
        hist = [h for h in e["history"] if h["win"] is not None]
        e["recent_wr"] = e["prev_wr"] = e["delta"] = None
        if len(hist) >= 4:
            half = len(hist) // 2
            prev, recent = hist[:half], hist[half:]
            pw = round(100.0 * sum(h["win"] for h in prev) / len(prev), 1)
            rw = round(100.0 * sum(h["win"] for h in recent) / len(recent), 1)
            e["prev_wr"], e["recent_wr"] = pw, rw
            e["delta"] = round(rw - pw, 1)
        out.append(e)
    out.sort(key=lambda x: (-x["played"], x["map"]))
    return out
