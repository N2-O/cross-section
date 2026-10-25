"""本地只读 API v1 —— 供外部工具（AI harness / Claude Code / Cursor / 自建脚本）查询。

设计原则
--------
1. 只读：绝不改数据库（唯一例外是 `/api/v1/...` 之外的写接口，那些不属于本模块）
2. 版本化：所有端点挂在 /api/v1/ 下，以后改结构不影响老调用方
3. 统一信封：{"ok": true, "data": ...} / {"ok": false, "error": "..."}
4. 提供 SQL 逃生舱：AI 可以写 SELECT 直接查，不用背端点

沙箱规则（safe_sql）
--------------------
- 只允许 SELECT / WITH 开头
- 禁止分号（多语句）
- 禁止写操作关键词
- 强制套一层 LIMIT
"""
from __future__ import annotations

import re
import sqlite3
import time

VERSION = "1"
MAX_ROWS = 5000

_FORBIDDEN = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex", "trigger",
)


def _ok(data):
    return 200, {"ok": True, "api": VERSION, "data": data}


def _err(msg, status=400):
    return status, {"ok": False, "error": msg}


def safe_sql(sql: str, limit: int = 1000) -> str:
    """校验并包装用户 SQL。只允许单条只读查询。"""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise ValueError("sql 参数为空")
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise ValueError("只允许 SELECT / WITH 查询")
    if ";" in s:
        raise ValueError("不允许多条语句")
    # 去掉字符串字面量后再查关键词，避免误伤 'delete' 这样的普通文本
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "''", low)
    for kw in _FORBIDDEN:
        if re.search(rf"\b{kw}\b", stripped):
            raise ValueError(f"禁止使用 {kw.upper()}")
    n = max(1, min(int(limit or 1000), MAX_ROWS))
    return f"SELECT * FROM ({s}) LIMIT {n}"


def _rows(conn: sqlite3.Connection, sql: str, args=()):
    cur = conn.execute(sql, args)
    cols = [d[0] for d in (cur.description or [])]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------------------------------------------------------------- schema

TABLES_DOC = {
    "matches": "每场对局一行（地图、时间、服务器、时长）",
    "demos": "扫描到的 demo 文件及其分析状态",
    "players": "每场每个玩家一行（名字、初始阵营、是否本人）",
    "kills": "每次击杀（击杀者/死亡者/助攻者/武器/爆头/各类标记）",
    "damage": "每次伤害事件（含武器、命中部位、伤害值）",
    "rounds": "每回合结果（胜方、结束原因、a_side 我方阵营、a_win 我方是否赢）",
    "economy": "每回合每阵营经济（5 人合计）。pre_bal=回合开始现金合计、post_bal=冻结结束现金合计、"
                "end_bal=回合判定前 1 秒现金合计，三者同量纲、可直接相减；"
                "start_eq=回合初装备合计、end_eq=买完后装备合计（装备价值，与现金不是一回事）",
    "pms": "每场每人的统计（ADR/KAST/Rating/首杀/多杀/残局/急停率等）。"
           "stop_shots=开火瞬间速度≤34 units/s 的次数，imprecise_shots 是它的补数；"
           "gun_fire_count=枪械开火数（分母只算枪，不含投掷与挥刀）；"
           "t_fk/t_fd=作为 T 方时的首杀/首死，ct_fk/ct_fd 为 CT 方，"
           "四者之和应等于 fk/fd",
    "snapshots": "每场每人的能力快照（用于趋势与退步预警）",
    "purchases": "购买/退款/掉落/捡起事件（item、cost、action、side）。"
                 "含退款类事件（action=sell/refund/item_sell/return），"
                 "算花费请用 round_end.spend（钱包法，含护甲与拆弹钳）",
    "blinds": "每次致盲事件（致盲者/受害者/时长）",
    "round_end": "回合结束时每人是否存活与装备价值（end_tick-64 采样）",
    "weapon_stat": "每场每人每武器的开火/命中/击杀/未急停计数（未急停=开火瞬间速度>34 units/s）",
    "grenade_throw": "每场按类型的投掷总数（全场合计，旧口径，仅供对照）",
    "grenade_use": "每场每人每类型的投出数（来自引爆事件的投掷者，可精确到人）",
    "spend_cat": "花费构成：每场每阵营各类别花费（步枪/狙击/冲锋/霰弹机枪/手枪/道具/甲/钳子）",
}


def api_schema(conn: sqlite3.Connection):
    out = {"tables": [], "notes": []}
    for name, desc in TABLES_DOC.items():
        try:
            cols = [dict(r) for r in conn.execute(f"PRAGMA table_info({name})")]
            n = conn.execute(f"SELECT COUNT(*) c FROM {name}").fetchone()["c"]
        except sqlite3.OperationalError:
            continue
        out["tables"].append({
            "name": name,
            "description": desc,
            "rows": n,
            "columns": [{"name": c["name"], "type": c["type"]} for c in cols],
        })
    out["notes"] = [
        "pms 与 players 通过 (match_id, steamid) 关联",
        "rounds.a_side 是 A 队在该回合的阵营（'T'/'CT'），换边后变化",
        "economy 的金额是 5 人队伍合计，不是个人",
        "matches.my_steamid 是本场记录到的「你」",
        "kills / damage 表只存 steamid，要显示名字需 JOIN players",
        "kills 的盲狙是 noscope，被闪开枪是 attackerblind，混烟是 thrusmoke",
        "economy.buy_type 已预计算为 手枪/ECO/强起/全买",
        "players.left_round > 0 表示该玩家在第 N 回合之后离开（0=全程在场）；统计仍按实际出场回合计算",
        "players.left_reason: quit=主动退出 kicked=被踢(投票/自动) lost=网络掉线 banned=封禁；kick 不享受少人经济补偿",
        "players.reconnect_round > 0 表示离开后在第 N 回合连回",
        "CS2 少人补偿：队伍连续 >=3 回合人数劣势且该回合失利时，每人 +$1000（cash_team_bonus_shorthanded）；economy 是 5 人合计，因此该回合队伍会多出约 $5000",
        "所有时间字段为本地时间字符串，可直接做 >= 比较",
        "急停判据：开火瞬间速度 ≤34 units/s 记为已急停（pms.stop_shots）。"
        "不用 awpy 的 shots.inaccuracy —— 那是武器实体的 m_fAccuracyPenalty（连发累积惩罚），"
        "官方注释写明 CS2 不把完整 inaccuracy 写进网络流，实测与移动速度无关",
        "kills.noscope 由引擎在击杀结算时填写，可靠。不要用 shots.scoped 反推："
        "CS2 的 AWP 开火后会立即自动退镜，按开火那一 tick 读到的永远是未开镜",
    ]
    return _ok(out)


# ---------------------------------------------------------------- matches

def api_matches(conn, qs):
    limit = int((qs.get("limit") or ["100"])[0])
    mapf = (qs.get("map") or [""])[0]
    sql = """SELECT m.id, m.map, m.played_at, m.duration_s, m.server, m.platform,
                    (SELECT COUNT(*) FROM rounds r WHERE r.match_id=m.id) rounds,
                    (SELECT COUNT(*) FROM kills k WHERE k.match_id=m.id) kills
             FROM matches m"""
    args = []
    if mapf:
        sql += " WHERE m.map=?"
        args.append(mapf)
    sql += " ORDER BY m.played_at DESC, m.id DESC LIMIT ?"
    args.append(max(1, min(limit, 500)))
    return _ok(_rows(conn, sql, args))


def api_match(conn, mid):
    m = conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
    if not m:
        return _err("match 不存在", 404)
    matches = _rows(conn, "SELECT * FROM matches WHERE id=?", (mid,))
    rounds = _rows(conn, """SELECT round, winner, reason, a_side, paused_sec FROM rounds
                            WHERE match_id=? ORDER BY round""", (mid,))
    players = _rows(conn, """SELECT p.steamid, p.name, p.first_side, p.is_me,
                                    p.left_round,
                                    x.rounds, x.kills, x.deaths, x.assists, x.adr,
                                    x.kast, x.rating, x.impact, x.fk, x.fd, x.hs
                             FROM players p
                             LEFT JOIN pms x ON x.match_id=p.match_id AND x.steamid=p.steamid
                             WHERE p.match_id=?""", (mid,))
    return _ok({"match": matches[0], "rounds": rounds, "players": players,
                "player_count": len(players), "round_count": len(rounds)})


def api_match_rounds(conn, mid):
    rows = _rows(conn, """SELECT round, winner, reason, a_side, paused_sec
                          FROM rounds WHERE match_id=? ORDER BY round""", (mid,))
    if not rows:
        return _err("match 不存在或没有回合数据", 404)
    return _ok(rows)


def api_match_kills(conn, mid, qs):
    limit = int((qs.get("limit") or ["2000"])[0])
    rows = _rows(conn, """SELECT k.round, k.tick,
                                 pa.name attacker_name, pv.name victim_name,
                                 ps.name assister_name,
                                 k.weapon, k.victim_weapon, k.headshot, k.noscope,
                                 k.thrusmoke, k.penetrated, k.attackerblind,
                                 k.dmg_health, k.distance, k.hitgroup
                          FROM kills k
                          LEFT JOIN players pa ON pa.match_id=k.match_id AND pa.steamid=k.attacker_steamid
                          LEFT JOIN players pv ON pv.match_id=k.match_id AND pv.steamid=k.victim_steamid
                          LEFT JOIN players ps ON ps.match_id=k.match_id AND ps.steamid=k.assister_steamid
                          WHERE k.match_id=? ORDER BY k.round, k.tick
                          LIMIT ?""", (mid, max(1, min(limit, 10000))))
    return _ok(rows)


def api_match_replay(conn, mid):
    """回放原始数据（体积大，几 MB）。用于自建可视化。"""
    rows = _rows(conn, "SELECT id FROM matches WHERE id=?", (mid,))
    if not rows:
        return _err("match 不存在", 404)
    return _ok({"note": "回放数据请用 /api/replay?match=<id>（非 v1，体积 5-6MB）"})


# ---------------------------------------------------------------- players

def api_players(conn, qs):
    # 不传 min_matches 时跟随设置（默认 3）；传了就按传的来
    _m = qs.get("min_matches")
    if _m:
        minm = int(_m[0])
    else:
        try:
            import settings as _st
            minm = int(_st.get("player_min_matches", 1))
        except Exception:
            minm = 3
    minm = max(0, minm)
    rows = _rows(conn, """SELECT p.steamid,
                                 (SELECT p2.name FROM players p2
                                   WHERE p2.steamid=p.steamid AND p2.name<>''
                                   ORDER BY p2.match_id DESC LIMIT 1) name,
                                 MAX(p.is_me) is_me,
                                 COUNT(DISTINCT p.match_id) matches
                          FROM players p JOIN matches m ON m.id=p.match_id
                          WHERE (m.excluded IS NULL OR m.excluded=0)
                          GROUP BY p.steamid
                          HAVING matches >= ?
                          ORDER BY matches DESC, p.steamid""", (minm,))
    return _ok(rows)


def api_player(conn, sid, qs):
    mapf = (qs.get("map") or [""])[0]
    since = (qs.get("since") or [""])[0]
    sql = """SELECT x.match_id, m.map, m.played_at, x.rounds, x.kills, x.deaths,
                    x.assists, x.adr, x.kast, x.rating, x.impact, x.kpr, x.dpr,
                    x.hs, x.fk, x.fd
             FROM pms x JOIN matches m ON m.id=x.match_id
             WHERE x.steamid=?"""
    args = [sid]
    if mapf:
        sql += " AND m.map=?"
        args.append(mapf)
    if since:
        sql += " AND m.played_at >= ?"
        args.append(since)
    sql += " ORDER BY m.played_at, m.id"
    rows = _rows(conn, sql, args)
    if not rows:
        return _err("该玩家没有数据（steamid 是否正确？）", 404)

    def avg(k):
        v = [r[k] for r in rows if r[k] is not None]
        return round(sum(v) / len(v), 2) if v else None

    summary = {k: avg(k) for k in ("adr", "kast", "rating", "impact", "kpr", "dpr")}
    summary["matches"] = len(rows)
    summary["rounds"] = sum(r["rounds"] or 0 for r in rows)
    summary["kills"] = sum(r["kills"] or 0 for r in rows)
    summary["deaths"] = sum(r["deaths"] or 0 for r in rows)
    return _ok({"steamid": sid, "summary": summary, "matches": rows})


def api_player_trend(conn, sid, qs):
    window = int((qs.get("window") or ["5"])[0])
    rows = _rows(conn, """SELECT s.* FROM snapshots s
                          JOIN matches m ON m.id=s.match_id
                          WHERE s.steamid=? AND (m.excluded IS NULL OR m.excluded=0)
                          ORDER BY s.played_at, s.match_id""", (sid,))
    return _ok({"steamid": sid, "window": window, "count": len(rows), "snapshots": rows})


# ---------------------------------------------------------------- sql / meta

def api_query(conn, qs):
    sql = (qs.get("sql") or [""])[0]
    limit = int((qs.get("limit") or ["1000"])[0])
    try:
        wrapped = safe_sql(sql, limit)
    except ValueError as e:
        return _err(str(e))
    t0 = time.time()
    try:
        rows = _rows(conn, wrapped)
    except sqlite3.Error as e:
        return _err(f"SQL 错误: {e}")
    return _ok({"rows": rows, "count": len(rows),
                "ms": round((time.time() - t0) * 1000, 1)})


def api_health(conn):
    stats = {}
    for t in ("matches", "players", "kills", "rounds", "pms", "snapshots"):
        try:
            stats[t] = conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
        except sqlite3.OperationalError:
            stats[t] = None
    return _ok({"api": VERSION, "status": "ok", "counts": stats})


def api_index(conn):
    """端点清单，给 AI 或人看的入口。"""
    return _ok({
        "api": VERSION,
        "base": "/api/v1",
        "endpoints": [
            {"method": "GET", "path": "/api/v1/health", "desc": "存活检查 + 各表行数"},
            {"method": "GET", "path": "/api/v1/schema", "desc": "所有表结构、行数、字段含义"},
            {"method": "GET", "path": "/api/v1/query?sql=...", "desc": "只读 SQL（SELECT/WITH），AI 首选"},
            {"method": "GET", "path": "/api/v1/matches", "desc": "对局列表 ?limit= ?map="},
            {"method": "GET", "path": "/api/v1/matches/{id}", "desc": "单场：概览+回合+玩家"},
            {"method": "GET", "path": "/api/v1/matches/{id}/rounds", "desc": "该场每回合结果"},
            {"method": "GET", "path": "/api/v1/matches/{id}/kills", "desc": "该场全部击杀明细"},
            {"method": "GET", "path": "/api/v1/players?min_matches=3", "desc": "玩家列表"},
            {"method": "GET", "path": "/api/v1/players/{steamid}", "desc": "某玩家逐场数据+均值 ?map= ?since="},
            {"method": "GET", "path": "/api/v1/players/{steamid}/stats", "desc": "长期统计（时间窗/地图筛选，聚合+分地图+分阵营）"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/detail", "desc": "明细：多杀分布/武器击杀/伤害构成"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/econ", "desc": "经济：购买类型胜率/装备保留率"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/duel", "desc": "对枪：分档胜率/被劣势武器击杀率"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/ability", "desc": "能力画像五维 + 趋势/退步预警"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/audit", "desc": "数据自洽校验：汇总与明细比对"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/summary", "desc": "player_summary：个人汇总 + 10/20/50 窗口"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/maps", "desc": "map_stats：地图维度 + 阵营拆分"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/weapons", "desc": "weapon_stats：武器使用/击杀/伤害/射击"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/utility", "desc": "utility_stats：投掷物使用与效果"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/economy", "desc": "economy_stats：购买/装备/保经济"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/clutch", "desc": "clutch_stats：1vX 残局机会与结果"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/match-stats", "desc": "match_player_stats：逐场逐玩家数据"},
            {"method": "GET", "path": "/api/v1/players/{steamid}/trend", "desc": "能力快照序列"},
            {"method": "GET", "path": "/api/v1/matches/{id}/detail", "desc": "单场完整明细：每回合经济/玩家/全部击杀"},
        ],
        "examples": [
            "curl http://127.0.0.1:8790/api/v1/schema",
            "curl 'http://127.0.0.1:8790/api/v1/query?sql=SELECT map,COUNT(*) n FROM matches GROUP BY map'",
            "curl 'http://127.0.0.1:8790/api/v1/players/76561198985595967'",
        ],
    })


# ---------------------------------------------------------------- 长期统计 / 明细

def _load_stats_api():
    import stats_api
    return stats_api


def _load_ability():
    import ability
    return ability


def _filter_rows(rows, since="", until="", mapf=""):
    out = []
    for r in rows:
        if mapf and (r["map"] or "") != mapf:
            continue
        p = r["played_at"] or ""
        if since and p < since:
            continue
        if until and p > until:
            continue
        out.append(r)
    return out


def api_player_stats(conn, sid, qs):
    """长期统计：支持时间窗和地图筛选，返回聚合 + 分地图 + 分阵营 + 逐场。"""
    sa = _load_stats_api()
    since = (qs.get("since") or [""])[0]
    until = (qs.get("until") or [""])[0]
    mapf = (qs.get("map") or [""])[0]

    all_rows = sa.player_rows(conn, sid)
    if not all_rows:
        return _err("该玩家没有数据（steamid 是否正确？）", 404)
    rows = _filter_rows(all_rows, since, until, mapf)
    if not rows:
        return _err("该筛选条件下没有对局", 404)

    total = sa._agg(rows)
    by_map = {}
    for r in rows:
        by_map.setdefault(r["map"] or "未知", []).append(r)
    maps = [dict(map=k, **sa._agg(v)) for k, v in
            sorted(by_map.items(), key=lambda kv: -len(kv[1]))]

    # 分阵营（T / CT）
    # 注意：_agg 的字段名不对称 —— T 方是 tkills / t_deaths，CT 方是 ct_kills / ct_deaths
    sides = {}
    for side, keys in (
        ("T", ("t_rounds", "tkills", "t_deaths", "t_dmg")),
        ("CT", ("ct_rounds", "ct_kills", "ct_deaths", "ct_dmg")),
    ):
        rd_k, k_k, d_k, dmg_k = keys
        s = {"rounds": total.get(rd_k, 0) or 0,
             "kills": total.get(k_k, 0) or 0,
             "deaths": total.get(d_k, 0) or 0,
             "dmg": total.get(dmg_k, 0) or 0}
        rd = s["rounds"]
        s["adr"] = round(s["dmg"] / rd, 1) if rd else None
        s["kd"] = round(s["kills"] / s["deaths"], 2) if s["deaths"] else None
        sides[side] = s

    matches = [{"match_id": r["match_id"], "map": r["map"], "played_at": r["played_at"],
                "rounds": r["rounds"], "kills": r["kills"], "deaths": r["deaths"],
                "assists": r["assists"], "adr": r["adr"], "kast": r["kast"],
                "rating": r["rating"], "impact": r["impact"], "hs": r["hs"],
                "fk": r["fk"], "fd": r["fd"]} for r in rows]

    return _ok({
        "steamid": sid,
        "filter": {"since": since or None, "until": until or None, "map": mapf or None},
        "total": total,
        "by_side": sides,
        "by_map": maps,
        "matches": matches,
        "available_maps": sorted({r["map"] for r in all_rows if r["map"]}),
        "available_range": {
            "first": min((r["played_at"] or "") for r in all_rows),
            "last": max((r["played_at"] or "") for r in all_rows),
        },
    })


def api_player_detail(conn, sid, qs):
    """明细：多杀分布 / 武器击杀 / 伤害构成 / 首杀首死。"""
    sa = _load_stats_api()
    try:
        d = sa.detail(conn, sid)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)
    return _ok({"steamid": sid, "detail": d})


def api_player_econ(conn, sid, qs):
    """经济：购买类型胜率 / 装备保留率 / 花费。"""
    sa = _load_stats_api()
    try:
        d = sa.econ_stats(conn, sid)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)
    return _ok({"steamid": sid, "econ": d})


def api_player_duel(conn, sid, qs):
    """对枪：按武器档位统计胜率、被劣势武器击杀率。"""
    sa = _load_stats_api()
    try:
        d = sa.duel_stats(conn, sid)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)
    return _ok({"steamid": sid, "duel": d})


def api_player_ability(conn, sid, qs):
    """能力画像：五维雷达 + 趋势 / 退步预警。"""
    ab = _load_ability()
    window = int((qs.get("window") or ["5"])[0])
    try:
        ab.ensure_snapshots(conn)
        t = ab.trend(conn, sid, window=window)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)
    return _ok({"steamid": sid, "ability": t})


def api_player_audit(conn, sid, qs):
    """数据自洽校验：同一指标的汇总与明细必须对得上。"""
    import stats_api
    try:
        a = stats_api.audit(conn, sid)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)
    return _ok({"steamid": sid, **a})


# ---------------------------------------------------------------- 按实体拆分的汇总
# 一次拿全量很容易把「个人」「地图」「武器」「道具」「经济」「残局」混在一个
# 大 JSON 里，下游要自己拆。这里按数据实体拆成独立端点，每个都带 meta 说明口径。

def _entity(conn, sid, name, window_note="全期"):
    """包装：统一 meta 头，便于下游区分口径与窗口。"""
    pl = conn.execute("SELECT name FROM players WHERE steamid=? LIMIT 1",
                      (sid,)).fetchone()
    return {"steamid": sid, "player": (pl["name"] if pl else None),
            "entity": name, "window": window_note}


def _window_ids(conn, sid, qs, default=None):
    """从 ?window=N 取最近 N 场的 match_id（用于按窗口切片统计）。"""
    w = (qs.get("window") or [None])[0]
    if not w:
        return default
    try:
        n = int(w)
    except (TypeError, ValueError):
        return default
    rows = conn.execute(
        """SELECT x.match_id FROM pms x JOIN matches m ON m.id=x.match_id
           WHERE x.steamid=? ORDER BY m.played_at DESC, m.id DESC LIMIT ?""",
        (sid, n)).fetchall()
    return [r["match_id"] for r in rows] or default


def api_player_summary(conn, sid, qs):
    """player_summary：个人历史汇总 + 近期窗口（avg_all / avg_lastN）。"""
    import stats_api
    try:
        ov = stats_api.overview(conn, sid)
        rows = stats_api.player_rows(conn, sid)
        wins = [10, 20, 50]
        windows = []
        for n in wins:
            sub = rows[-n:]
            if not sub:
                continue
            a = stats_api._agg(sub)
            a.update(window_requested=n, window_actual=len(sub),
                     window_status=("ok" if len(rows) >= n else "short"))
            windows.append(a)
        all_agg = stats_api._agg(rows) if rows else {}
        all_agg.update(window_requested=None, window_actual=len(rows),
                       window_status="all")
        out = _entity(conn, sid, "player_summary")
        out.update(total=ov.get("total"), windows=[all_agg] + windows,
                   timeline=ov.get("timeline"), clutch=ov.get("clutch"))
        return _ok(out)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)


def api_player_maps(conn, sid, qs):
    """map_stats：地图维度 + 各图阵营拆分。"""
    import stats_api
    try:
        ov = stats_api.overview(conn, sid)
        out = _entity(conn, sid, "map_stats")
        out["maps"] = ov.get("by_map") or []
        out["total"] = ov.get("total")
        return _ok(out)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)


def api_player_weapons(conn, sid, qs):
    """weapon_stats：武器使用 / 击杀 / 伤害 / 射击数据。

    覆盖所有开火过的武器（含没击杀的），fire_count 合计恒等于总开火数。
    """
    import stats_api
    try:
        det = stats_api.detail(conn, sid)
        ws = det.get("weapons") or []
        out = _entity(conn, sid, "weapon_stats")
        out["weapons"] = ws
        out["checks"] = {
            "fire_count_sum": sum(w.get("fires") or 0 for w in ws),
            "note": "以 weapon_stat 为主体，含无击杀武器；伤害按 damage 表原始 weapon 名归属",
        }
        return _ok(out)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)


def api_player_utility(conn, sid, qs):
    """utility_stats：投掷物的使用与效果 + 自己受到的闪光与道具伤害。"""
    import stats_api
    try:
        # ?window=N 只看最近 N 场；和 CSV 的窗口行同源
        _ids = _window_ids(conn, sid, qs)
        ut = stats_api.utility(conn, sid, _ids)
        rv = stats_api.received(conn, sid)
        out = _entity(conn, sid, "utility_stats")
        out["utility"] = ut
        out["window"] = len(_ids) if _ids else None
        out["received"] = rv
        out["direction"] = {
            "utility": "我投出去 / 我造成的",
            "received": "我吃到的 / 我被闪的（按 全部 / T / CT 拆开）",
        }
        out["formula"] = {
            "eff_pct": "至少致盲 1 名敌人的闪光弹数 ÷ 投出数 ×100"
                       "（按投掷 tick 去重；只闪到队友的不计）",
            "flash_deaths": "死亡 tick 落在致盲窗口内即计一次，只证明「死时还瞎着」",
            "note": "throw 来自 grenade_use（引爆事件归属到人），不是全场合计",
        }
        return _ok(out)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)


def api_player_economy(conn, sid, qs):
    """economy_stats：个人购买、团队购买档、装备状态 + 逐回合明细。"""
    import stats_api
    try:
        ec = stats_api.econ_stats(conn, sid)
        out = _entity(conn, sid, "economy_stats")
        out.update(ec)
        # 逐回合：接口里原来完全没有这块（只在 CSV 里），
        # 想看「这一局我 eco 但队伍强起」必须先导出文件
        out["rounds"] = stats_api.econ_rounds(conn, sid,
                                              _window_ids(conn, sid, qs))
        out["field_map"] = {
            "player_spend": "个人本回合支出（钱包法：回合开始现金 − 冻结结束现金，"
                            "含护甲与拆弹钳，已扣退款）",
            "player_buy_type": "个人购买档（按个人买完后装备价值 equip_fz）："
                               "≥4500 全买 / 3000-4500 半买 / 1500-3000 强起 / <1500 ECO；"
                               "第 1、13 回合为手枪局",
            "player_equipment_value_round_start":
                "回合开始继承的装备（团队 start_eq ÷ 5，人均）",
            "player_equipment_value_end":
                "回合结束时（结算前 -64 tick）身上的装备，阵亡为 0。"
                "不是 freeze time 末的快照",
            "team_buy_type": "队伍层面的购买档（economy 表同阵营那一行，团队口径）",
            "team_spend": "该阵营本回合总支出（5 人合计个人钱包法花费之和）",
            "saved": "败局存活且仍有装备（保物资，不限枪）",
        }
        out["note"] = {
            "spent_avg": "团队每回合花费（5 人钱包法花费合计），人均 = 除以 5；"
                         "个人值见 player_spend",
            "inv_rate": "装备保留率 = 回合初继承装备 ÷ 回合末装备（都是人均值，取比值，与花费无关）",
            "save_economy": "败局存活且仍有装备的回合数（保物资，不限枪）",
        }
        return _ok(out)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)


def api_player_clutch(conn, sid, qs):
    """clutch_stats：按 1vX 分组的残局机会 / 结果 / 保枪价值。"""
    import stats_api
    try:
        ov = stats_api.overview(conn, sid)
        cl = (ov.get("clutch") or {}).get("clutch") or {}
        out = _entity(conn, sid, "clutch_stats")
        out["clutch"] = cl
        # 标准字段名：被 clutch 内部叫 played/won/pct，对外给一份不会误解的
        _played = cl.get("played")
        _won = cl.get("won")
        out["clutch_played"] = _played
        out["clutch_won"] = _won
        out["clutch_win_rate"] = (round(_won / _played * 100, 1)
                                  if _played else None)
        out["save_rounds"] = cl.get("save_rounds")
        out["save_value"] = cl.get("save_value")
        out["total_clutch_played"] = ov.get("total", {}).get("clutch_played")
        out["formula"] = {
            "clutch_played": "存活队友数 + 存活敌人数组成的 1vN 局面出现次数"
                             "（从逐回合存活事件流重建，不是 awpy 的 roster 推导）",
            "clutch_won": "上述局面里最终赢下回合的次数",
            "clutch_win_rate": "clutch_won ÷ clutch_played ×100；0 次机会时为 null 而非 0",
            "save_rounds": "残局里没打完就保物资的回合数（败局存活且仍有装备）",
            "save_value": "那些保下来的装备价值合计",
            "note": "awpy 的 clutch_1vN 是「赢下次数」不是机会数，"
                    "直接拿来当分母会得到 0/0；总量与 by_size 各档必须同源",
        }
        out["note"] = ("总量与 by_size 各档机会数同源；awpy 的 clutch_1vN 是"
                       "「赢下」次数，不是机会数")
        return _ok(out)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)


def api_player_match_stats(conn, sid, qs):
    """match_player_stats：每张地图、每名玩家一行的逐场数据。"""
    import stats_api
    try:
        rows = stats_api.player_rows(conn, sid)
        # 连同场对手也给出，便于横向对比
        mids = [r["match_id"] for r in rows]
        out = _entity(conn, sid, "match_player_stats")
        out["rows"] = rows
        if mids:
            ph = ",".join("?" * len(mids))
            out["match_players"] = [dict(r) for r in conn.execute(
                f"SELECT p.*, pl.name FROM pms p "
                f"LEFT JOIN players pl ON pl.match_id=p.match_id AND pl.steamid=p.steamid "
                f"WHERE p.match_id IN ({ph})", mids)]
        return _ok(out)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}", 500)


def api_match_detail(conn, mid):
    """单场完整明细：每回合经济、每人统计、全部击杀。"""
    m = conn.execute("SELECT * FROM matches WHERE id=?", (mid,)).fetchone()
    if not m:
        return _err("match 不存在", 404)

    rounds = _rows(conn, """SELECT round, winner, reason, a_side, paused_sec
                            FROM rounds WHERE match_id=? ORDER BY round""", (mid,))
    econ = _rows(conn, """SELECT round, side, pre_bal, post_bal, start_eq, end_eq
                          FROM economy WHERE match_id=? ORDER BY round,
                          CASE side WHEN 'T' THEN 1 ELSE 2 END""", (mid,))
    players = _rows(conn, """SELECT p.steamid, p.name, p.first_side, p.is_me,
                                    x.rounds, x.kills, x.deaths, x.assists, x.adr,
                                    x.kast, x.rating, x.impact, x.kpr, x.dpr,
                                    x.hs, x.fk, x.fd, x.mk2, x.mk3, x.mk4
                             FROM players p
                             LEFT JOIN pms x ON x.match_id=p.match_id AND x.steamid=p.steamid
                             WHERE p.match_id=?""", (mid,))
    kills = _rows(conn, """SELECT k.round, k.tick,
                                  pa.name attacker_name, pv.name victim_name,
                                  ps.name assister_name,
                                  k.weapon, k.victim_weapon, k.headshot, k.noscope,
                                  k.thrusmoke, k.penetrated, k.attackerblind,
                                  k.dmg_health, k.distance, k.hitgroup
                           FROM kills k
                           LEFT JOIN players pa ON pa.match_id=k.match_id AND pa.steamid=k.attacker_steamid
                           LEFT JOIN players pv ON pv.match_id=k.match_id AND pv.steamid=k.victim_steamid
                           LEFT JOIN players ps ON ps.match_id=k.match_id AND ps.steamid=k.assister_steamid
                           WHERE k.match_id=? ORDER BY k.round, k.tick""", (mid,))
    dmg = _rows(conn, """SELECT d.round, pa.name attacker_name,
                                d.valid AS dmg_health,
                                COALESCE(d.dmg_health,0) AS dmg_health_raw,
                                d.weapon
                         FROM damage d
                         LEFT JOIN players pa ON pa.match_id=d.match_id AND pa.steamid=d.attacker_steamid
                         WHERE d.match_id=?""", (mid,))

    return _ok({
        "match": dict(m),
        "rounds": rounds,
        "economy": econ,
        "players": players,
        "kills": kills,
        "damage_count": len(dmg),
        "counts": {"rounds": len(rounds), "players": len(players),
                   "kills": len(kills), "damage": len(dmg),
                   "economy_rows": len(econ)},
    })


def doc_page() -> str:
    """/api 的简易说明页（纯 HTML，无依赖）。"""
    eps = [
        ("GET", "/api/v1", "端点清单"),
        ("GET", "/api/v1/health", "存活检查 + 各表行数"),
        ("GET", "/api/v1/schema", "所有表结构、行数、字段说明"),
        ("GET", "/api/v1/query?sql=...", "只读 SQL（SELECT / WITH），AI 首选"),
        ("GET", "/api/v1/matches?limit=&map=", "对局列表"),
        ("GET", "/api/v1/matches/{id}", "单场：概览 + 回合 + 玩家"),
        ("GET", "/api/v1/matches/{id}/rounds", "该场每回合结果"),
        ("GET", "/api/v1/matches/{id}/kills", "该场全部击杀明细"),
        ("GET", "/api/v1/players?min_matches=3", "玩家列表"),
        ("GET", "/api/v1/players/{steamid}", "某玩家逐场数据 + 均值"),
        ("GET", "/api/v1/players/{steamid}/stats", "长期统计：?since= ?until= ?map= 聚合+分地图+分阵营"),
        ("GET", "/api/v1/players/{steamid}/detail", "明细：多杀分布 / 武器击杀 / 伤害构成"),
        ("GET", "/api/v1/players/{steamid}/econ", "经济：购买类型胜率 / 装备保留率"),
        ("GET", "/api/v1/players/{steamid}/audit", "数据自洽校验：汇总与明细比对"),
        ("GET", "/api/v1/players/{steamid}/summary", "player_summary：个人汇总 + 窗口"),
        ("GET", "/api/v1/players/{steamid}/maps", "map_stats：地图维度"),
        ("GET", "/api/v1/players/{steamid}/weapons", "weapon_stats：武器效率"),
        ("GET", "/api/v1/players/{steamid}/utility", "utility_stats：投掷物效果"),
        ("GET", "/api/v1/players/{steamid}/economy", "economy_stats：经济与装备"),
        ("GET", "/api/v1/players/{steamid}/clutch", "clutch_stats：残局明细"),
        ("GET", "/api/v1/players/{steamid}/match-stats", "match_player_stats：逐场数据"),
        ("GET", "/api/v1/players/{steamid}/duel", "对枪：分档胜率 / 被劣势武器击杀率"),
        ("GET", "/api/v1/players/{steamid}/ability", "能力画像五维 + 趋势退步预警"),
        ("GET", "/api/v1/players/{steamid}/trend", "能力快照序列（趋势）"),
        ("GET", "/api/v1/matches/{id}/detail", "单场全明细：每回合经济 / 玩家 / 全部击杀"),
    ]
    rows = "\n".join(
        f"<tr><td class='m'>{m}</td><td><code>{p}</code></td><td>{d}</td></tr>"
        for m, p, d in eps)
    return f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<title>Cross-Section · 本地 API</title>
<style>
body{{background:#101011;color:#e9eaec;font:14px/1.65 -apple-system,Segoe UI,sans-serif;
     margin:0;padding:40px 6vw}}
h1{{font-size:20px;margin:0 0 6px;font-weight:600}}
p.sub{{color:#858585;margin:0 0 26px;font-size:13px}}
table{{border-collapse:collapse;width:100%;max-width:1080px}}
th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid #242425;vertical-align:top}}
th{{color:#858585;font-weight:500;font-size:12px;letter-spacing:.05em}}
td.m{{color:#8fb;width:52px;font-weight:600;font-size:12px}}
code{{background:#191a1b;padding:2px 7px;border-radius:4px;font-size:12.5px;
      font-family:ui-monospace,monospace;color:#cfd2d6}}
pre{{background:#191a1b;border:1px solid #242425;border-radius:8px;padding:14px 16px;
     overflow-x:auto;font-size:12.5px;line-height:1.7;color:#cfd2d6;max-width:1080px}}
.note{{color:#858585;font-size:12.5px;margin-top:24px;max-width:760px;line-height:1.7}}
.note b{{color:#e9eaec}}
</style>
<h1>Cross-Section · 本地只读 API v1</h1>
<p class="sub">给 Claude Code / Cursor / 自建 harness 查询对局数据用的。只读，不会改动你的数据库。</p>
<table><thead><tr><th>方法</th><th>路径</th><th>说明</th></tr></thead>
<tbody>{rows}</tbody></table>

<h3 style="margin:32px 0 10px;font-size:14px;color:#858585;font-weight:500">试试看</h3>
<pre># 有哪些数据
curl http://127.0.0.1:8790/api/v1/schema

# 直接写 SQL（AI 最常用）
curl "http://127.0.0.1:8790/api/v1/query?sql=SELECT map,COUNT(*) n FROM matches GROUP BY map"

# 我的能力趋势
curl "http://127.0.0.1:8790/api/v1/players/76561198985595967/trend"</pre>

<div class="note">
<b>SQL 沙箱</b>：只允许 <code>SELECT</code> / <code>WITH</code> 开头、单条语句；
出现 INSERT/UPDATE/DELETE/DROP 等关键词会被拒绝。结果默认最多 1000 行，
可用 <code>&amp;limit=</code> 调到 5000。<br><br>
<b>给 AI 的提示词</b>：把这个地址和 <code>/api/v1/schema</code> 给它，
它就知道所有表和字段，能自己写查询，不用你一条条解释。
</div>
</html>"""


# ---------------------------------------------------------------- dispatch

_ROUTES = [
    (r"^/api/v1/?$", lambda c, q, g: api_index(c)),
    (r"^/api/v1/health$", lambda c, q, g: api_health(c)),
    (r"^/api/v1/schema$", lambda c, q, g: api_schema(c)),
    (r"^/api/v1/query$", lambda c, q, g: api_query(c, q)),
    (r"^/api/v1/matches$", lambda c, q, g: api_matches(c, q)),
    (r"^/api/v1/matches/(\d+)$", lambda c, q, g: api_match(c, int(g[0]))),
    (r"^/api/v1/matches/(\d+)/rounds$", lambda c, q, g: api_match_rounds(c, int(g[0]))),
    (r"^/api/v1/matches/(\d+)/kills$", lambda c, q, g: api_match_kills(c, int(g[0]), q)),
    (r"^/api/v1/matches/(\d+)/replay$", lambda c, q, g: api_match_replay(c, int(g[0]))),
    (r"^/api/v1/players$", lambda c, q, g: api_players(c, q)),
    (r"^/api/v1/players/(\d+)/stats$", lambda c, q, g: api_player_stats(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/detail$", lambda c, q, g: api_player_detail(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/econ$", lambda c, q, g: api_player_econ(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/duel$", lambda c, q, g: api_player_duel(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/ability$", lambda c, q, g: api_player_ability(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/audit$", lambda c, q, g: api_player_audit(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/summary$", lambda c, q, g: api_player_summary(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/maps$", lambda c, q, g: api_player_maps(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/weapons$", lambda c, q, g: api_player_weapons(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/utility$", lambda c, q, g: api_player_utility(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/economy$", lambda c, q, g: api_player_economy(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/clutch$", lambda c, q, g: api_player_clutch(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/match-stats$", lambda c, q, g: api_player_match_stats(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)$", lambda c, q, g: api_player(c, int(g[0]), q)),
    (r"^/api/v1/players/(\d+)/trend$", lambda c, q, g: api_player_trend(c, int(g[0]), q)),
    (r"^/api/v1/matches/(\d+)/detail$", lambda c, q, g: api_match_detail(c, int(g[0]))),
]


def dispatch(conn, path: str, qs: dict):
    """返回 (status, obj) 或 None（未匹配，交给调用方处理）。"""
    for pat, fn in _ROUTES:
        m = re.match(pat, path)
        if m:
            return fn(conn, qs, m.groups())
    if path.startswith("/api/v1/"):
        return _err(f"未知端点: {path}（看 /api/v1 取清单）", 404)
    return None
