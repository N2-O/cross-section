"""统计聚合：总览 / 分地图 / 分阵营 / 时间线。"""
from __future__ import annotations

import sqlite3

# 排除被标记「不算数」的局（投降 / 摆烂 / 半路不打）。
# 所有统计类查询都拼上这个条件，别让某一个出口把排除的局算进去——
# 之前 player_rows 排了、其他手写 SQL 没排，就会出现「平均 4 场、武器 5 场」。
NOT_EX = ("match_id IN (SELECT id FROM matches "
          "WHERE excluded IS NULL OR excluded = 0)")


def _agg(rows) -> dict:
    """按回合加权聚合一组 pms 行。"""
    SUMS = ("kills", "deaths", "assists", "hs", "dmg", "fk", "fd",
            "t_rounds", "ct_rounds", "tkills", "t_deaths", "t_dmg",
            "ct_kills", "ct_deaths", "ct_dmg", "t_fk", "t_fd", "ct_fk", "ct_fd",
            "mk2", "mk3", "mk4",
            # 扩展字段（awpy 解析层产出）
            "fire_count", "hit_count", "imprecise_shots", "stop_shots", "gun_fire_count",
            "spent", "plants", "defuses", "survive_rounds",
            "flash_assists", "flashes_thrown", "enemies_flashed", "flash_duration",
            "utility_damage", "trade_kills", "traded_deaths",
            "clutch_played", "clutch_won", "clutch_1v1", "clutch_1v2",
            "clutch_1v3", "clutch_1v4", "clutch_1v5",
            "penetrated_kills", "thrusmoke_kills", "noscope_kills")
    r = {k: 0 for k in SUMS}
    r.update({"matches": len(rows), "rounds": 0, "wins": 0, "draws": 0, "played": 0,
              "equip_value": 0, "equip_round_start": 0})
    kast_w = rating_w = impact_w = 0.0
    for x in rows:
        rd = x["rounds"] or 0
        r["rounds"] += rd
        for k in SUMS:
            r[k] += (x[k] if k in x.keys() else 0) or 0
        # 装备价值是「每回合均值」，要按回合数还原成总量再平均
        r["equip_value"] += (x["equip_value"] or 0) * rd
        r["equip_round_start"] += (x["equip_round_start"] or 0) * rd
        kast_w += (x["kast"] or 0) * rd
        rating_w += (x["rating"] or 0) * rd
        impact_w += (x["impact"] or 0) * rd
        r["played"] += 1
        _w = x["wins"] or 0
        _t = x["rounds_total"] or 0
        if _t > 0 and _w * 2 > _t:
            r["wins"] += 1
        elif _t > 0 and _w * 2 == _t:
            # 12:12 这种平局（MR12 先到 13 分，常规打满 24 回合），既不是胜也不是负
            r["draws"] += 1
    n = r["rounds"] or 1
    r["adr"] = round(r["dmg"] / n, 1)
    r["kast"] = round(kast_w / n, 1)
    r["rating"] = round(rating_w / n, 2)
    r["impact"] = round(impact_w / n, 2)
    r["kd"] = round(r["kills"] / max(r["deaths"], 1), 2)
    r["kpr"] = round(r["kills"] / n, 2)
    r["dpr"] = round(r["deaths"] / n, 2)
    r["apr"] = round(r["assists"] / n, 2)
    r["hs_pct"] = round(r["hs"] / max(r["kills"], 1) * 100, 0)
    r["losses"] = max(0, r["played"] - r["wins"] - r["draws"])
    # 胜率分母不含平局（CS2 惯例：13:13 不算赢也不算输）
    _decisive = r["wins"] + r["losses"]
    r["win_rate"] = round(r["wins"] / max(_decisive, 1) * 100, 0) if _decisive else None

    # 射击：开火批次命中率 + 急停率 / 未急停率
    # 急停的分母是「枪械开火数」，不是总开火数——weapon_fire 也包含投掷和挥刀，
    # 移动投掷是常态，混进来会污染指标（实测道具/刀 105 次里 86% 被判超阈值）。
    r["fire_accuracy"] = round(r["hit_count"] / r["fire_count"] * 100, 1) if r["fire_count"] else None
    _gf = r.get("gun_fire_count") or 0
    r["stop_rate"] = round(r["stop_shots"] / _gf * 100, 1) if _gf else None
    r["imprecise_rate"] = round(r["imprecise_shots"] / _gf * 100, 1) if _gf else None
    r["per_fire"] = round(r["fire_count"] / n, 1)

    # 经济（每回合均值）
    r["spent_avg"] = round(r["spent"] / n)
    r["equip_value"] = round(r["equip_value"] / n)
    r["equip_round_start"] = round(r["equip_round_start"] / n)

    # 残局
    r["clutch_pct"] = round(r["clutch_won"] / r["clutch_played"] * 100, 0) if r["clutch_played"] else None
    # 换人
    r["trade_rate"] = round(r["trade_kills"] / max(r["kills"], 1) * 100, 1)
    r["traded_death_rate"] = round(r["traded_deaths"] / max(r["deaths"], 1) * 100, 1)
    # 生存
    r["survive_pct"] = round(r["survive_rounds"] / n * 100, 0)
    # 特殊击杀
    r["penetrated_pct"] = round(r["penetrated_kills"] / max(r["kills"], 1) * 100, 1)
    r["thrusmoke_pct"] = round(r["thrusmoke_kills"] / max(r["kills"], 1) * 100, 1)
    # 道具
    r["flash_eff"] = round(r["enemies_flashed"] / max(r["flashes_thrown"], 1) * 100, 0)
    r["utility_adr"] = round(r["utility_damage"] / n, 1)

    t_rd, ct_rd = r["t_rounds"] or 1, r["ct_rounds"] or 1
    r["side"] = {
        "T": {"rounds": r["t_rounds"], "kills": r["tkills"], "deaths": r["t_deaths"],
              "adr": round(r["t_dmg"] / t_rd, 1), "kpr": round(r["tkills"] / t_rd, 2),
              "dpr": round(r["t_deaths"] / t_rd, 2)},
        "CT": {"rounds": r["ct_rounds"], "kills": r["ct_kills"], "deaths": r["ct_deaths"],
               "adr": round(r["ct_dmg"] / ct_rd, 1), "kpr": round(r["ct_kills"] / ct_rd, 2),
               "dpr": round(r["ct_deaths"] / ct_rd, 2)},
    }
    return r


def player_rows(conn: sqlite3.Connection, steamid: int,
                include_excluded: bool = False):
    """该玩家逐场数据。

    include_excluded=False 时跳过被标记排除的局（投降/摆烂那种），
    平均、走势、能力画像都走这个入口，所以一处过滤全局生效。
    """
    flt = "" if include_excluded else " AND (m.excluded IS NULL OR m.excluded=0)"
    return [dict(r) for r in conn.execute(
        """SELECT m.id AS match_id, m.map, m.played_at, m.platform, m.duration_s,
                  m.excluded, m.exclude_note,
                  p.*,
                  (SELECT COUNT(*) FROM rounds r WHERE r.match_id=m.id) rounds_total,
                  (SELECT SUM(a_win) FROM rounds r WHERE r.match_id=m.id) wins,
                  (SELECT a_side FROM rounds r WHERE r.match_id=m.id ORDER BY round LIMIT 1) first_side
           FROM pms p JOIN matches m ON m.id=p.match_id
           WHERE p.steamid=?""" + flt + """
           ORDER BY m.played_at, m.id""", (steamid,))]


def overview(conn: sqlite3.Connection, steamid: int) -> dict:
    rows = player_rows(conn, steamid)
    if not rows:
        return {"empty": True}

    total = _agg(rows)

    by_map = {}
    for r in rows:
        by_map.setdefault(r["map"] or "未知", []).append(r)
    maps = [dict(map=rk, **_agg(v)) for rk, v in
            sorted(by_map.items(), key=lambda kv: -len(kv[1]))]

    timeline = [{
        "match_id": r["match_id"], "map": r["map"], "played_at": r["played_at"],
        "platform": r["platform"], "adr": r["adr"], "kast": r["kast"],
        "rating": r["rating"], "impact": r["impact"],
        "kpr": round((r["kills"] or 0) / max(r["rounds"] or 1, 1), 2),
        "dpr": round((r["deaths"] or 0) / max(r["rounds"] or 1, 1), 2),
        "kd": round((r["kills"] or 0) / max(r["deaths"] or 1, 1), 2),
        "kills": r["kills"], "deaths": r["deaths"], "assists": r["assists"],
        "rounds": r["rounds"],
        "spent": r["spent"], "equip_value": r["equip_value"],
        "win": 1 if (r["wins"] or 0) * 2 > (r["rounds_total"] or 0) > 0 else 0,
        "draw": 1 if (r["rounds_total"] or 0) > 0 and (r["wins"] or 0) * 2 == (r["rounds_total"] or 0) else 0,
        "score": f"{r['wins'] or 0}:{(r['rounds_total'] or 0) - (r['wins'] or 0)}",
    } for r in rows]

    # 注意：pms.equip_value / equip_round_start 落库时已经是「人均」，
    # 这里再除 5 会把 2,705 变成 541。不要再除。

    name = None
    nm = conn.execute("SELECT name FROM players WHERE steamid=? ORDER BY rowid DESC LIMIT 1",
                      (steamid,)).fetchone()
    if nm:
        name = nm["name"]

    # 闪光效率重算：至少致盲 1 名敌人的闪光弹数 ÷ 投出总数
    # （不能用「致盲人次 ÷ 投出数」——一颗闪光可以致盲多人，会算出 90%+ 的虚高值）
    try:
        eff = conn.execute(
            """SELECT COUNT(DISTINCT tick) FROM blinds
               WHERE attacker_steamid=? AND duration > 0.1
                 AND attacker_side != victim_side""", (steamid,)).fetchone()[0]
        thrown = total.get("flashes_thrown") or 0
        total["flash_effective"] = eff
        total["flash_eff"] = round(eff / thrown * 100, 1) if thrown else None
    except Exception:
        pass

    # 残局 / 多杀 / 人数优势（从事件流重建）
    try:
        import clutch as clutchmod
        cl = clutchmod.build(conn, steamid)
    except Exception as e:
        cl = {"error": f"{type(e).__name__}: {e}"}

    # 用事件流重建的结果覆盖 pms 里的 awpy 值：两者在边界回合上判定不一致
    # （awpy 的 roster 推导与我们从 5v5 扣减的实现有差异），总量必须和 1vX 明细同源，
    # 否则会出现「总 10 次、明细合计 7 次」这种对不上的情况。
    _c = (cl or {}).get("clutch") or {}
    if _c and "played" in _c:
        total["clutch_played"] = _c.get("played")
        total["clutch_won"] = _c.get("won")
        total["clutch_pct"] = (round(_c["won"] / _c["played"] * 100, 1)
                               if _c.get("played") else None)

    # 受闪 / 吃道具伤害（方向与 utility 相反：那个算我投出去的，这个算我吃到的）
    try:
        recv = received(conn, steamid)
    except Exception as e:
        recv = {"error": f"{type(e).__name__}: {e}"}

    return {"player": {"steamid": steamid, "name": name},
            "total": total, "by_map": maps, "timeline": timeline,
            "clutch": cl, "received": recv}


def received(conn: sqlite3.Connection, steamid: int) -> dict:
    """受到的闪光与道具伤害（按 T/CT 拆开）。

    和 utility() 是互补的两个方向：那个算「我投出去/造成的」，这个算「我吃到/被闪的」。
    只看自己投了多少闪，判断不了「一号位是不是在吃伤害」——得有受闪侧的数据。
    """
    def _blank():
        return {"count": 0, "duration": 0.0, "deaths": 0, "by_enemy": 0,
                "by_teammate": 0}

    flash = {"all": _blank(), "T": _blank(), "CT": _blank()}
    # 我每回合的阵营，用于给伤害事件分阵营
    side_of_round = {(r["match_id"], r["round"]): (r["a_side"] or "").upper()
                     for r in conn.execute(
                         "SELECT match_id, round, a_side FROM rounds")}
    # 我的死亡 tick，用于判断「闪白期间阵亡」
    death_at = {(r["match_id"], r["round"]): r["tick"] for r in conn.execute(
        "SELECT match_id, round, tick FROM kills WHERE victim_steamid=?", (steamid,))}

    for b in conn.execute(
            f"""SELECT match_id, round, tick, duration, victim_side,
                      attacker_side FROM blinds
               WHERE victim_steamid=? AND duration > 0.05
                 AND {NOT_EX}""", (steamid,)):
        d = float(b["duration"] or 0)
        vs = (b["victim_side"] or side_of_round.get(
            (b["match_id"], b["round"]), "") or "").upper()
        enemy = (b["attacker_side"] or "").upper() != vs
        buckets = [flash["all"]]
        if vs in ("T", "CT"):
            buckets.append(flash[vs])
        # 闪白窗口内有没有我的死亡事件
        dt = death_at.get((b["match_id"], b["round"]))
        died = bool(dt is not None and b["tick"] <= dt <= b["tick"] + int(d * 64))
        for bk in buckets:
            bk["count"] += 1
            bk["duration"] += d
            bk["deaths"] += 1 if died else 0
            bk["by_enemy" if enemy else "by_teammate"] += 1

    # 我吃到的道具伤害（手雷 + 燃烧类）
    util = {"all": {"total": 0, "he": 0, "fire": 0},
            "T": {"total": 0, "he": 0, "fire": 0},
            "CT": {"total": 0, "he": 0, "fire": 0}}
    for r in conn.execute(
            f"""SELECT match_id, round, weapon, SUM(MIN(dmg_health,100)) d
               FROM damage WHERE victim_steamid=?
                 AND weapon IN ('hegrenade','inferno','molotov','incgrenade')
                 AND {NOT_EX}
               GROUP BY match_id, round, weapon""", (steamid,)):
        sd = side_of_round.get((r["match_id"], r["round"]), "")
        dmg = r["d"] or 0
        kind = "he" if "hegrenade" in str(r["weapon"]).lower() else "fire"
        for key in ("all", sd):
            if key not in util:
                continue
            util[key]["total"] += dmg
            util[key][kind] += dmg

    # 每回合数，用于算「每回合吃到多少」
    rounds = {"all": 0, "T": 0, "CT": 0}
    for r in conn.execute(
            """SELECT rd.a_side FROM rounds rd
               JOIN pms p ON p.match_id=rd.match_id AND p.steamid=?""", (steamid,)):
        sd = (r["a_side"] or "").upper()
        rounds["all"] += 1
        if sd in ("T", "CT"):
            rounds[sd] += 1

    for key in ("all", "T", "CT"):
        f = flash[key]
        f["duration"] = round(f["duration"], 2)
        f["avg_duration"] = round(f["duration"] / f["count"], 2) if f["count"] else None
        f["death_pct"] = round(f["deaths"] / f["count"] * 100, 1) if f["count"] else None
        f["per_round"] = round(f["count"] / rounds[key], 2) if rounds[key] else None
        u = util[key]
        u["per_round"] = round(u["total"] / rounds[key], 2) if rounds[key] else None

    return {"flash": flash, "util_taken": util, "rounds": rounds}


def audit(conn: sqlite3.Connection, steamid: int) -> dict:
    """数据自洽校验：同一指标的「汇总」与「明细」必须对得上。

    历史教训：多杀、残局、道具伤害都出现过汇总和明细来自不同数据源、
    数字打架却没人发现的情况。这里把可比项逐一核对，任何一项不一致都会报出来。
    """
    checks: list[dict] = []

    def add(name, summary, detail_value, note=""):
        ok = (summary is not None and detail_value is not None
              and int(summary) == int(detail_value))
        checks.append({"item": name, "summary": summary,
                       "detail": detail_value, "ok": ok, "note": note})

    ov = overview(conn, steamid)
    det = detail(conn, steamid)
    multi = det.get("multi") or {}

    # 1. 多杀：pms 的 mk2/mk3/mk4（awpy 口径）vs 从 kills 自算
    for n in (2, 3, 4):
        add(f"多杀 {n}K", ov["total"].get(f"mk{n}"), multi.get(str(n)),
            "pms.mk vs 从 kills 分桶")

    # 2. 残局：总量 vs 各档机会数之和
    cl = ((ov.get("clutch") or {}).get("clutch") or {})
    by_size = cl.get("by_size") or {}
    sum_played = sum(v.get("played", 0) for v in by_size.values())
    add("残局机会总数", ov["total"].get("clutch_played"), sum_played,
        "总量 vs 1v1~1v5 机会数合计")

    # 3. 道具伤害：pms 总量 vs 各道具分项合计
    ut = utility(conn, steamid)
    sum_util = sum((d.get("damage") or 0) for k, d in ut.items()
                   if isinstance(d, dict) and k in ("he", "fire"))
    add("道具伤害", ov["total"].get("utility_damage"), sum_util,
        "pms 总量 vs 手雷+燃烧分项")

    # 4. 击杀：pms 累计 vs kills 事件数（排除自杀）
    k_events = conn.execute(
        f"SELECT COUNT(*) c FROM kills WHERE attacker_steamid=? "
        f"AND attacker_steamid != victim_steamid AND {NOT_EX}",
        (steamid,)).fetchone()["c"]
    add("击杀数", ov["total"].get("kills"), k_events, "pms.kills vs kills 表事件数")

    # 5. 开火：pms 累计 vs weapon_stat 合计
    wf = conn.execute(
        f"SELECT COALESCE(SUM(fires),0) c FROM weapon_stat "
        f"WHERE steamid=? AND {NOT_EX}", (steamid,)).fetchone()["c"]
    add("开火次数", ov["total"].get("fire_count"), wf, "pms vs weapon_stat")

    # 5b. 武器段合计：detail.weapons 的 fires 求和必须等于总开火
    # （曾经以 kills 为主体 + LIMIT 16，丢掉无击杀武器，武器段只有 1319 而总览 1519）
    wsum = sum((w.get("fires") or 0) for w in (det.get("weapons") or []))
    add("武器段开火合计", ov["total"].get("fire_count"), wsum,
        "总开火 vs 武器明细各行 fires 之和")

    # 6. 急停：分母是枪械开火数（不含投掷与挥刀）
    gf = ov["total"].get("gun_fire_count") or 0
    fs = (ov["total"].get("stop_shots") or 0) + (ov["total"].get("imprecise_shots") or 0)
    add("阈内低速+超阈值 = 枪械开火", fs, gf, "急停分项加总 vs gun_fire_count")

    # 6b. 枪械开火不得超过总开火
    checks.append({"item": "枪械开火 ≤ 总开火",
                   "summary": ov["total"].get("fire_count"),
                   "detail": gf,
                   "ok": gf <= (ov["total"].get("fire_count") or 0),
                   "note": "weapon_fire 含投掷与挥刀，所以枪械数应小于等于总数"})

    # 7. 武器段按类别过滤后必须与总览闭合（否则两边各说各话）
    _gf2 = sum((w.get("fires") or 0) for w in (det.get("weapons") or [])
               if w.get("cat") == "gun")
    add("武器段枪械开火 = 总览", _gf2, gf, "按 cat=gun 过滤后的 fires 合计")

    # 8. 残局：总量必须等于 1vX 明细合计
    # （曾经 avg_all 用事件流=7、窗口与地图段用 awpy=10，同一份数据给出两个答案）
    _cl = ((ov.get("clutch") or {}).get("clutch") or {})
    _bysize = sum((v.get("played") or 0)
                  for v in (_cl.get("by_size") or {}).values() if isinstance(v, dict))
    add("残局总数 = 1vX 明细合计", _cl.get("played") or 0, _bysize,
        "同一事件流重建，任何一处换口径都会造出两个答案")

    bad = [c for c in checks if not c["ok"]]
    return {"ok": not bad, "checked": len(checks), "failed": len(bad),
            "checks": checks}


def detail(conn: sqlite3.Connection, steamid: int) -> dict:
    """HLTV 级细项：多杀分布 / 武器击杀 / 对位战绩 / 伤害构成 / 残局。"""
    # ---- 多杀（按每回合击杀数分桶）----
    # 必须排除自杀/环境死亡（attacker == victim），否则那一回合会被多算 1 杀，
    # 把 3 杀顶成 4 杀（曾导致 detail 出现 4K=1，而 pms 的 mk4=0）。
    multi = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    for r in conn.execute(
        f"SELECT COUNT(*) c FROM kills WHERE attacker_steamid=? "
        f"AND attacker_steamid != victim_steamid AND {NOT_EX} "
        f"GROUP BY match_id, round", (steamid,)
    ):
        c = r["c"]
        k = str(min(c or 0, 5))
        if k in multi:
            multi[k] += 1

    # ---- 武器击杀（含特殊击杀：穿墙/穿烟/盲狙/跳跃）
    # ---- 武器（以 weapon_stat 为主体：所有开火过的武器都要有一行）----
    # 以前以 kills 为主体 + LIMIT 16，结果「有开火但没击杀」的武器（道具投掷、
    # 刀、没打死人的枪）整条被丢掉，武器段开火合计 1319 而总览 1519，差 200。
    # 现在左连 kills 与 damage，保证 fire_count 合计恒等于总开火数，且带伤害。
    weapons = []
    for r in conn.execute(
        f"""SELECT w.weapon w,
                  SUM(w.fires) fires, SUM(w.hits) hits,
                  SUM(w.kills) wkills, SUM(w.imprecise) imp,
                  COALESCE(k.c, 0) n, COALESCE(k.h, 0) hs, COALESCE(k.p, 0) pen,
                  COALESCE(k.s, 0) smoke, COALESCE(k.ns, 0) noscope,
                  COALESCE(k.j, 0) jump, k.dt,
                  COALESCE(d.d, 0) dmg
           FROM weapon_stat w
           LEFT JOIN (SELECT weapon, COUNT(*) c, SUM(headshot) h, SUM(penetrated) p,
                             SUM(thrusmoke) s, SUM(noscope) ns,
                             SUM(COALESCE(jumping,0)) j, AVG(distance) dt
                      FROM kills WHERE attacker_steamid=? AND {NOT_EX}
                      GROUP BY weapon) k ON k.weapon = w.weapon
           LEFT JOIN (SELECT weapon, SUM(MIN(dmg_health,100)) d
                      FROM damage WHERE attacker_steamid=? AND weapon IS NOT NULL
                        AND {NOT_EX}
                      GROUP BY weapon) d ON d.weapon = w.weapon
           WHERE w.steamid=? AND w.{NOT_EX}
           GROUP BY w.weapon
           ORDER BY SUM(w.kills) DESC, SUM(w.fires) DESC""",
        (steamid, steamid, steamid)
    ):
        w = str(r["w"] or "?")
        if w.lower() in ("world", "worldent", "?"):
            continue
        fires, hits, n = r["fires"] or 0, r["hits"] or 0, r["n"] or 0
        weapons.append(dict(
            w=w, n=n, hs=r["hs"] or 0, dmg=r["dmg"] or 0,
            pen=r["pen"] or 0, smoke=r["smoke"] or 0, noscope=r["noscope"] or 0,
            jump=r["jump"] or 0,
            dist=(round(r["dt"], 1) if r["dt"] is not None else None),
            fires=fires, hits=hits,
            acc=(round(hits / fires * 100, 1) if fires else None),
            # imp / imprecise 两个键都留：前端旧代码读 imprecise，CSV 和新代码读 imp
            imp=(r["imp"] or 0), imprecise=(r["imp"] or 0),
            imp_rate=(round((r["imp"] or 0) / fires * 100, 1) if fires else None),
            # 武器伤害按回合摊，才方便横向比效率
            dmg_per_round=None,
        ))

    # 每武器射击统计（命中率必须按武器算）
    # 武器分类：枪械 / 近战 / 投掷物。汇总里与枪法相关的指标只该看枪械；
    # 投掷物和刀虽然也触发 weapon_fire，但那是「使用」不是「射击」。
    _UTIL = ("flashbang", "flashgrenade", "hegrenade", "smokegrenade", "molotov",
             "incgrenade", "decoy", "snowball", "tagrenade", "breachcharge",
             "bumpmine", "sensorgrenade")
    _MELEE = ("taser", "knife")

    def _cat(w):
        w = str(w or "").lower()
        if w in _UTIL or w.endswith("grenade"):
            return "util"
        if w in _MELEE or w.startswith("knife"):
            return "melee"
        return "gun"

    for w in weapons:
        w["cat"] = _cat(w["w"])

    # CS2 的 damage 事件把消音版记在基础武器名下（m4a1_silencer 的伤害全记成 m4a1），
    # 两把枪无法拆开。有击杀却 0 伤害会让「按武器算伤害效率」直接失真，
    # 所以留空而不是给 0 —— 空 = 算不出来，0 = 确实是零。
    _base_has = {str(w["w"]).lower(): w for w in weapons}
    for w in weapons:
        _n = str(w["w"]).lower()
        if _n.endswith("_silencer") and w.get("dmg") == 0:
            _b = _base_has.get(_n.replace("_silencer", ""))
            if _b:
                w["dmg"] = None
                w["dmg_note"] = f"伤害并入 {_b['w']}（CS2 事件不带消音版后缀）"

    # 环境击杀（world / worldent）不是武器，从武器榜里剔除
    weapons = [w for w in weapons if str(w["w"]).lower() not in ("world", "worldent", "?")]

    # CS2 的 damage 事件把消音版伤害记在基础武器名下（M4A1-S → m4a1、USP-S → hkp2000、
    # 各种刀 → knife），变体行单独查会得到 0 伤害。这里只在「别名目标没有独立行」时回填，
    # 避免同一份伤害被两行重复计入。
    _present = {str(w["w"]).lower() for w in weapons}
    _dmg_alias = {"m4a1_silencer": "m4a1", "usp_silencer": "hkp2000",
                  "knife_gypsy_jackknife": "knife", "knife_t": "knife",
                  "incgrenade": "inferno", "molotov": "inferno"}
    _dmg_by = {r["weapon"]: (r["d"] or 0) for r in conn.execute(
        f"SELECT weapon, SUM(MIN(dmg_health,100)) d FROM damage "
        f"WHERE attacker_steamid=? AND weapon IS NOT NULL AND {NOT_EX} "
        f"GROUP BY weapon", (steamid,))}
    for w in weapons:
        if w["dmg"]:
            continue
        alias = _dmg_alias.get(str(w["w"]).lower())
        if alias and alias not in _present:
            w["dmg"] = _dmg_by.get(alias, 0)

    # 武器伤害按回合摊：用该玩家的总回合数（不是该武器的使用回合）
    _rd = conn.execute(f"SELECT COALESCE(SUM(rounds),0) r FROM pms "
                       f"WHERE steamid=? AND {NOT_EX}",
                       (steamid,)).fetchone()["r"] or 0
    for w in weapons:
        w["dmg_per_round"] = (round(w["dmg"] / _rd, 2) if _rd and w["dmg"] else None)

    # ---- 对位：我杀谁 / 谁杀我 ----
    names = {r["steamid"]: r["name"] for r in conn.execute(
        "SELECT DISTINCT steamid, name FROM players")}
    killed = [{"sid": r["v"], "name": names.get(r["v"], str(r["v"])), "n": r["c"]}
              for r in conn.execute(
                  f"""SELECT victim_steamid v, COUNT(*) c FROM kills
                     WHERE attacker_steamid=? AND {NOT_EX} GROUP BY victim_steamid
                     ORDER BY c DESC LIMIT 12""", (steamid,))]
    died = [{"sid": r["a"], "name": names.get(r["a"], str(r["a"])), "n": r["c"]}
            for r in conn.execute(
                f"""SELECT attacker_steamid a, COUNT(*) c FROM kills
                   WHERE victim_steamid=? AND attacker_steamid IS NOT NULL
                     AND {NOT_EX}
                   GROUP BY attacker_steamid ORDER BY c DESC LIMIT 12""", (steamid,))]

    # ---- 伤害构成：枪械 / 手雷 / 火焰 ----
    dmg = {"gun": 0, "he": 0, "fire": 0, "other": 0}
    for r in conn.execute(
        f"""SELECT weapon, SUM(dmg_health) d FROM damage
           WHERE attacker_steamid=? AND {NOT_EX} GROUP BY weapon""", (steamid,)
    ):
        w = (r["weapon"] or "").lower()
        d = r["d"] or 0
        if "hegrenade" in w:
            dmg["he"] += d
        elif "inferno" in w or "molotov" in w or "incgrenade" in w:
            dmg["fire"] += d
        elif w in ("world", "worldent", "trigger_hurt") or not w:
            dmg["other"] += d
        else:
            dmg["gun"] += d

    fm = conn.execute(
        f"SELECT SUM(fk) fk, SUM(fd) fd FROM pms WHERE steamid=? AND {NOT_EX}",
        (steamid,)).fetchone()
    return {"multi": multi, "weapons": weapons, "killed": killed, "died": died,
            "dmg": dmg, "fk": fm["fk"] or 0, "fd": fm["fd"] or 0}


def _buy_type(round_no: int, equip_fz) -> str | None:
    """按个人冻结结束时的装备价值分档（个人口径，能分辨「全队 ECO 但我起了英雄 AK」）。

    equip_fz 是本回合买完后（冻结结束）本人身上的装备价值；None 表示该回合没有采样。
    阈值：第 1/13 回合强制手枪局；≥4500 全买；≥3000 半买；≥1500 强起；其余 ECO。
    """
    if equip_fz is None:
        return None
    if round_no in (1, 13):
        return "手枪局"
    if equip_fz >= 4500:
        return "全买"
    if equip_fz >= 3000:
        return "半买"
    if equip_fz >= 1500:
        return "强起"
    return "ECO"


def econ_stats(conn: sqlite3.Connection, steamid: int) -> dict:
    """经济局胜率 / 装备效率 / 首杀胜率 / 回合原因 / 手枪局。"""
    # 我方是否是 A 队（按第一回合对比）
    flags = {}
    for r in conn.execute(
        """SELECT m.id mid,
                  (SELECT first_side FROM players p
                    WHERE p.match_id=m.id AND p.steamid=?) fs,
                  (SELECT a_side FROM rounds r WHERE r.match_id=m.id ORDER BY round LIMIT 1) a0
           FROM matches m""", (steamid,)
    ):
        flags[r["mid"]] = (r["fs"] == r["a0"]) if (r["fs"] and r["a0"]) else True

    # ---- 经济局：按 buy_type 分组的胜负（个人口径）----
    # 统计单位是「我的每回合」：按我自己该回合买完后的装备价值（round_end.equip_fz）分档，
    # 所以能分辨「全队 ECO 但我起了英雄 AK」。花费用钱包法 round_end.spend。
    my_round: dict[tuple, tuple] = {}
    for r in conn.execute(
            """SELECT re.match_id, re.round, re.equip_fz, re.spend
               FROM round_end re
               WHERE re.steamid = ?
                 AND re.match_id IN (SELECT id FROM matches
                                     WHERE excluded IS NULL OR excluded=0)""",
            (steamid,)
    ):
        my_round[(r["match_id"], r["round"])] = (r["equip_fz"], r["spend"])

    buy = {}
    spent_tot = saved_tot = eq_tot = 0.0
    econ_n = 0
    for r in conn.execute(
        """SELECT e.match_id mid, e.round rd, e.buy_type bt, e.side sd,
                  e.pre_bal, e.post_bal, e.start_eq, e.end_eq, r.a_side, r.a_win
           FROM economy e JOIN rounds r ON r.match_id=e.match_id AND r.round=e.round
           WHERE e.match_id IN (SELECT id FROM matches
                                WHERE excluded IS NULL OR excluded=0)"""
    ):
        is_a = flags.get(r["mid"], True)
        my_side = r["a_side"] if r["a_side"] else "T"
        if not is_a:
            my_side = "CT" if my_side == "T" else "T"
        if r["sd"] != my_side:
            continue
        won = bool(r["a_win"]) if is_a else not bool(r["a_win"])
        equip_fz, spend = my_round.get((r["mid"], r["rd"]), (None, None))
        bt = _buy_type(r["rd"] or 0, equip_fz)
        if bt:
            b = buy.setdefault(bt, {"n": 0, "w": 0, "spent": 0, "eq": 0})
            b["n"] += 1
            b["w"] += 1 if won else 0
            b["spent"] += spend or 0
            b["eq"] += equip_fz or 0
        spent_tot += spend or 0
        saved_tot += r["end_eq"] or 0
        eq_tot += r["start_eq"] or 0
        econ_n += 1

    # ---- 我方队伍的真实花费与装备保留（按人归属，不用 economy 表的 pre/post_bal）----
    # spend_cat 只有阵营粒度，换边后无法区分哪一半是我方，所以这里按「同队 5 人」汇总 pms。
    # economy.pre_bal 存的是回合初装备价值、post_bal 是冻结时现金，两个量纲相减算不出花费，
    # 曾导致每回合花费 $331、装备保留率 10276%。
    team = conn.execute(
        """SELECT COALESCE(SUM(p.spent), 0) spent,
                  COALESCE(SUM(p.equip_value * p.rounds), 0) equip_sum,
                  COALESCE(SUM(p.equip_round_start * p.rounds), 0) inherit_sum
           FROM pms p
           JOIN players me ON me.match_id = p.match_id AND me.steamid = ? AND me.is_me = 1
           JOIN players mate ON mate.match_id = p.match_id AND mate.steamid = p.steamid
                            AND mate.first_side = me.first_side
           WHERE p.match_id IN (SELECT match_id FROM players WHERE steamid = ?)
             AND p.match_id IN (SELECT id FROM matches
                                WHERE excluded IS NULL OR excluded=0)""",
        (steamid, steamid)).fetchone()
    spent_tot = float(team["spent"] or 0)
    equip_sum = float(team["equip_sum"] or 0)      # 5 人 × 各回合的人均装备 = 团队合计
    inherit_sum = float(team["inherit_sum"] or 0)
    saved_tot = equip_sum              # equip_value 已是人均、×rounds 再对 5 人求和即团队值，不再除 5
    # 装备保留率 = 继承装备 ÷ 回合末装备 —— 「每回合的装备里有多少是上回合带过来的」
    inv_rate = round(inherit_sum / equip_sum * 100, 1) if equip_sum else None

    buys = []
    order = {"手枪局": 0, "ECO": 1, "强起": 2, "半买": 3, "全买": 4}
    for bt, b in sorted(buy.items(), key=lambda kv: order.get(kv[0], 9)):
        buys.append({"type": bt, "n": b["n"], "w": b["w"],
                     "wr": round(b["w"] / b["n"] * 100) if b["n"] else 0,
                     "spent": round(b["spent"] / max(b["n"], 1)),
                     # 个人口径：equip_fz 本身就是本人装备价值，不用再除 5
                     "eq": round(b["eq"] / max(b["n"], 1))})

    # ---- 首杀胜率（我拿首杀 vs 敌方拿首杀）----
    # 同队判定：players.first_side 相同 = 同队（一局内队伍不变，只换边）
    teams = {}
    for r in conn.execute("SELECT match_id mid, steamid sid, first_side fs FROM players"):
        teams.setdefault(r["mid"], {})[r["sid"]] = r["fs"]
    fk_rounds = conn.execute(
        """SELECT k.match_id mid, k.attacker_steamid att, r.a_side, r.a_win
           FROM kills k
           JOIN (SELECT match_id, round, MIN(tick) mt FROM kills GROUP BY match_id, round) f
             ON f.match_id=k.match_id AND f.round=k.round AND f.mt=k.tick
           JOIN rounds r ON r.match_id=k.match_id AND r.round=k.round"""
    ).fetchall()
    fk_n = fk_w = fd_n = fd_w = 0
    for r in fk_rounds:
        is_a = flags.get(r["mid"], True)
        won = bool(r["a_win"]) if is_a else not bool(r["a_win"])
        att = r["att"]
        if not att:
            continue
        tmap = teams.get(r["mid"], {})
        my_fs = tmap.get(steamid)
        mate = (att == steamid) or (my_fs and tmap.get(att) == my_fs)
        if mate:
            fk_n += 1; fk_w += 1 if won else 0
        else:
            fd_n += 1; fd_w += 1 if won else 0

    # ---- 回合原因 ----
    # 两处修正：
    # 1) 补 NOT_EX —— 原来没过滤被排除的局
    # 2) 剔掉 surrender —— 它是「整场投降」不是「回合怎么结束的」，
    #    混在 bomb_exploded 里一个 0.2% 显得像脏数据。投降局整体走 excluded。
    reasons = [{"r": r["reason"] or "未知", "n": r["c"]} for r in conn.execute(
        f"""SELECT r.reason, COUNT(*) c FROM rounds r
            JOIN matches m ON m.id=r.match_id
            WHERE {NOT_EX}
              AND LOWER(COALESCE(r.reason,'')) NOT LIKE '%surrender%'
            GROUP BY r.reason ORDER BY c DESC""")]

    # ---- 手枪局（每半场第 1 回合）----
    pistol_n = pistol_w = 0
    for r in conn.execute(
        f"""SELECT r.match_id mid, r.round rd, r.a_side, r.a_win FROM rounds r
           WHERE r.round IN (1,13) AND {NOT_EX}"""
    ):
        is_a = flags.get(r["mid"], True)
        won = bool(r["a_win"]) if is_a else not bool(r["a_win"])
        pistol_n += 1; pistol_w += 1 if won else 0

    # ---- 花费构成（CT / T 分别，按类）----
    # 步枪/手枪/道具 = purchases 精确 cost；甲/钳子 = 差值反推（见 awpy_ingest）
    spend_mix = {"CT": [], "T": []}
    try:
        agg2: dict[str, dict[str, int]] = {"CT": {}, "T": {}}
        for r in conn.execute(
                "SELECT side, cat, SUM(cost) c FROM spend_cat GROUP BY side, cat"):
            sd = str(r["side"] or "")
            if sd in agg2:
                agg2[sd][str(r["cat"])] = r["c"] or 0
        for sd in ("CT", "T"):
            items = sorted(agg2[sd].items(), key=lambda kv: -kv[1])
            tot = sum(v for _, v in items) or 1
            spend_mix[sd] = [{"cat": c, "cost": v,
                              "pct": round(v / tot * 100, 1)} for c, v in items]
    except Exception:
        spend_mix = {"CT": [], "T": []}

    # ---- 保经济：败局里存活且仍留有装备 ----
    # 「保枪」只是口头说法，本质是保经济：手枪局保半甲、保道具也算。
    # 所以判据不查具体武器，只看「该回合我方输 + 玩家活着 + 装备价值 > 0」。
    # 与残局保枪（clutch 分节）是两个不同指标：那个只在 1vN 局面下算。
    save_n = save_val = 0
    lost_n = 0
    for r in conn.execute(
        """SELECT re.alive, re.equip, rd.a_win
           FROM round_end re
           JOIN rounds rd ON rd.match_id = re.match_id AND rd.round = re.round
           WHERE re.steamid = ?""", (steamid,)
    ):
        if (r["a_win"] or 0) != 0:
            continue                      # 只看败局
        lost_n += 1
        if (r["alive"] or 0) == 1 and (r["equip"] or 0) > 0:
            save_n += 1
            save_val += r["equip"] or 0
    if lost_n == 0:
        save_econ = {"rounds": None, "lost_rounds": 0, "pct": None,
                     "value": None, "avg": None}
    else:
        save_econ = {
            "rounds": save_n,
            "lost_rounds": lost_n,
            "pct": round(save_n / lost_n * 100, 1),
            "value": round(save_val),
            "avg": round(save_val / save_n) if save_n else None,
        }

    return {
        "buy": buys,
        "save_economy": save_econ,
        "spend_mix": spend_mix,
        "spent_avg": round(spent_tot / max(econ_n, 1)),
        "spent_total": round(spent_tot),
        "saved_total": round(saved_tot),
        "eq_avg": round(eq_tot / max(econ_n, 1)),
        "inv_rate": inv_rate,
        "fk_rounds": {"n": fk_n, "w": fk_w,
                      "wr": round(fk_w / fk_n * 100) if fk_n else 0},
        "fd_rounds": {"n": fd_n, "w": fd_w,
                      "wr": round(fd_w / fd_n * 100) if fd_n else 0},
        "reasons": reasons,
        "pistol": {"n": pistol_n, "w": pistol_w,
                   "wr": round(pistol_w / pistol_n * 100) if pistol_n else 0},
    }


_TIER = {
    "手枪": {"glock", "usp_silencer", "hkp2000", "p250", "fiveseven", "tec9",
             "cz75a", "elite", "deagle", "revolver"},
    "冲锋枪": {"mac10", "mp9", "mp7", "mp5sd", "ump45", "p90", "bizon"},
    "霰弹枪": {"nova", "xm1014", "mag7", "sawedoff"},
    "狙击枪": {"awp", "ssg08", "scar20", "g3sg1"},
    "步枪": {"ak47", "m4a1", "m4a1_silencer", "galilar", "famas", "aug", "sg556",
             "negev", "m249"},
    "近战": {"knife", "knife_t", "taser"},
}


# active_weapon_name 存的是游戏内显示名，先映射回内部名
_SHOW2KEY = {
    "AK-47": "ak47", "M4A4": "m4a1", "M4A1-S": "m4a1_silencer", "AWP": "awp",
    "Desert Eagle": "deagle", "USP-S": "usp_silencer", "Glock-18": "glock",
    "P2000": "hkp2000", "P250": "p250", "Five-SeveN": "fiveseven", "Tec-9": "tec9",
    "CZ75-Auto": "cz75a", "Dual Berettas": "elite", "R8 Revolver": "revolver",
    "MAC-10": "mac10", "MP9": "mp9", "MP7": "mp7", "MP5-SD": "mp5sd",
    "UMP-45": "ump45", "P90": "p90", "PP-Bizon": "bizon",
    "Galil AR": "galilar", "FAMAS": "famas", "AUG": "aug", "SG 553": "sg556",
    "SSG 08": "ssg08", "SCAR-20": "scar20", "G3SG1": "g3sg1",
    "Nova": "nova", "XM1014": "xm1014", "MAG-7": "mag7", "Sawed-Off": "sawedoff",
    "Negev": "negev", "M249": "m249", "Zeus x27": "taser",
    "Knife": "knife", "HE Grenade": "hegrenade", "Flashbang": "flashbang",
    "Smoke Grenade": "smokegrenade", "Molotov": "molotov",
    "Incendiary Grenade": "incgrenade", "Decoy Grenade": "decoy",
}


def econ_rounds(conn: sqlite3.Connection, steamid: int,
                match_ids: list[int] | None = None) -> list[dict]:
    """逐回合经济：个人花费/装备/保经济 × 团队购买档位/团队花费。

    单一实现，CSV 与 API 都调这里。之前这段逻辑只写在 export_csv 里，
    结果导出文件有 99 行逐回合数据、接口里一行都拿不到。
    """
    where, args = ["rd.a_side IS NOT NULL AND rd.a_side != ''",
                   ("rd.match_id IN (SELECT id FROM matches "
                    "WHERE excluded IS NULL OR excluded=0)")], []
    if match_ids:
        where.append("rd.match_id IN (%s)" % ",".join("?" * len(match_ids)))
        args.extend(match_ids)

    # 团队花费：我队 5 人同一回合的钱包法花费合计（同 players.first_side = 同队）
    team_spend: dict[tuple, int] = {}
    for r in conn.execute(
            """SELECT re.match_id, re.round, SUM(re.spend) c
               FROM round_end re
               JOIN players p ON p.match_id = re.match_id AND p.steamid = re.steamid
               WHERE re.spend IS NOT NULL
                 AND p.first_side = (SELECT first_side FROM players
                                     WHERE match_id = re.match_id AND steamid = ?)
               GROUP BY re.match_id, re.round""", (steamid,)):
        team_spend[(r["match_id"], r["round"])] = r["c"]

    # 回合末状态 + 冻结时装备 + 钱包法花费（round_end 每人每回合一行，一次查完）
    # spend = 回合开始现金 − 冻结结束现金；NULL 表示没有采样，输出 None 而不是 0
    end_state: dict[tuple, tuple] = {}
    for r in conn.execute(
            "SELECT match_id, round, alive, equip, equip_fz, spend FROM round_end WHERE steamid=?",
            (steamid,)):
        end_state[(r["match_id"], r["round"])] = (
            r["alive"], r["equip"], r["equip_fz"], r["spend"])

    # economy 每回合有 T/CT 两行，key 必须带 side，否则拿到对手的档位
    buy_map: dict[tuple, tuple] = {}
    for r in conn.execute(
            "SELECT match_id, round, side, buy_type, start_eq FROM economy"):
        buy_map[(r["match_id"], r["round"], (r["side"] or "").upper())] = (
            r["buy_type"], r["start_eq"])

    out = []
    for r in conn.execute(
            """SELECT rd.match_id, rd.round, rd.a_side, rd.a_win,
                      m.map, m.played_at
               FROM rounds rd JOIN matches m ON m.id=rd.match_id
               WHERE %s ORDER BY rd.match_id, rd.round""" % " AND ".join(where),
            args):
        k = (r["match_id"], r["round"])
        side = (r["a_side"] or "").upper()
        bt, start_eq = buy_map.get((r["match_id"], r["round"], side), (None, None))
        alive, equip, equip_fz, spent = end_state.get(k, (None, None, None, None))
        won = bool(r["a_win"])
        out.append({
            "match_id": r["match_id"], "round_number": r["round"],
            "map": r["map"] or "", "played_at": r["played_at"] or "",
            "my_side": side, "win": won,
            "player_spend": spent,
            # 个人分档：按我自己该回合买完后的装备价值（round_end.equip_fz）
            "player_buy_type": _buy_type(r["round"] or 0, equip_fz),
            # start_eq 是 5 人合计，÷5 成人均
            "player_equipment_value_round_start":
                (round((start_eq or 0) / 5.0, 1) if start_eq is not None else None),
            # 回合结束时（结算前 -64 tick）身上的装备；本回合阵亡为 0。
            # 不是 freeze time 末的快照——那个口径 demo 里没现成字段
            "player_equipment_value_end": equip,
            "player_alive": (bool(alive) if alive is not None else None),
            "team_buy_type": bt,
            "team_spend": team_spend.get(k),
            "saved": (not won and alive == 1 and (equip or 0) > 0),
        })
    return out


def _tier(w) -> str:
    w = str(w or "").replace("weapon_", "")
    w = _SHOW2KEY.get(w, w).lower()
    for t, s in _TIER.items():
        if w in s:
            return t
    return "道具"


GRENADE_KIND = {
    # key: (type 短名, 中文, purchases 里的 item 名, grenade_throw 里的 type)
    "he": ("he", "手雷", ["hegrenade"], ["he"]),
    "fire": ("fire", "燃烧弹", ["molotov", "incendiary"], ["molotov", "incendiary", "fire"]),
    "smoke": ("smoke", "烟雾弹", ["smokegrenade"], ["smoke"]),
    "flash": ("flash", "闪光弹", ["flashbang"], ["flashbang", "flash"]),
    "decoy": ("decoy", "诱饵弹", ["decoy"], ["decoy"]),
}

# 伤害归属：damage 表里的 weapon 名 ≠ 购买项名。
# 燃烧弹的伤害记在 weapon='inferno' 名下（燃烧区域），不是 molotov/incgrenade，
# 曾经只按购买项名去查 → 燃烧伤害恒为 0，47 点伤害没进分类（206 vs 159）。
GRENADE_DMG_KEYS = {
    "he": ["hegrenade"],
    "fire": ["inferno", "molotov", "incgrenade", "incendiary"],
}


def utility(conn, steamid: int, match_ids: list[int] | None = None) -> dict:
    """五种道具的购买 / 捡起 / 投掷 / 伤害（火雷）与闪光效果。

    match_ids 传了就只统计这几场（CSV 的「近 10/20/50 场」窗口行要用到），
    不传则是全期。注意这是「回去重新数那几场」，不是拿全期数除以场次——
    道具使用在快局和拉锯局之间差好几倍，平均值会骗人。

    口径说明：
    - 购买/捡起：purchases 表按 item 匹配，天然按人
    - 投掷：grenade_use 表（demoparser2 引爆事件带 user_steamid）
    - 火雷伤害：damage 表按 weapon，按人
    - 闪光效果：pms 汇总 + blinds 明细
    """
    out = {}
    # 场次切片条件：所有查询共用，免得某一条忘了加
    if match_ids:
        _ph = ",".join("?" * len(match_ids))
        _scope = f"match_id IN ({_ph})"
        _args = [steamid] + list(match_ids)
    else:
        _scope = NOT_EX
        _args = [steamid]

    n_rounds = conn.execute(
        f"SELECT COALESCE(SUM(rounds),0) r FROM pms WHERE steamid=? AND {_scope}",
        tuple(_args)).fetchone()["r"] or 0
    # 每人的购买/捡起
    per = {}
    for r in conn.execute(
        f"""SELECT item, action, COUNT(*) n FROM purchases
           WHERE steamid=? AND {_scope} GROUP BY item, action""", tuple(_args)):
        per[(str(r["item"] or "").lower(), r["action"])] = r["n"]

    # 个人投掷（grenade_use：demoparser2 引爆事件带的 user_steamid）。
    # 这是「真投出去了」的数；买了死在手里的不在这里，所以 <= 购买数 是正常的。
    # 老表 grenade_throw 只有全场汇总（awpy 的 thrower_steamid 全 None，无法归属到人），
    # 曾经作为 fallback 会把「全场 10 人合计」冒充成个人投掷数（闪光从 35 变 210），
    # 已彻底移除 —— 没有个人数据就返回空值，不拿全场数顶替。
    throws = {}
    try:
        for r in conn.execute(
                f"SELECT type, SUM(n) n FROM grenade_use WHERE steamid=? AND {_scope} "
                f"GROUP BY type",
                tuple(_args)):
            throws[str(r["type"] or "").lower()] = r["n"] or 0
    except Exception:
        throws = {}

    # 火雷伤害（按人）+ 有效投掷（产生过伤害/致盲的投掷，按 tick 去重）
    dmg = {}
    used = {}
    for r in conn.execute(
        f"""SELECT weapon, SUM(MIN(dmg_health,100)) d, COUNT(*) n,
                  COUNT(DISTINCT tick) t
           FROM damage WHERE attacker_steamid=? AND {_scope} GROUP BY weapon""",
        tuple(_args)):
        w = str(r["weapon"] or "").lower()
        dmg[w] = dict(d=r["d"] or 0, n=r["n"] or 0)
        used[w] = r["t"] or 0

    for key, (_, cn, items, throw_keys) in GRENADE_KIND.items():
        buy = sum(per.get((it, "purchase"), 0) for it in items)
        pick = sum(per.get((it, "pickup"), 0) for it in items)
        drop = sum(per.get((it, "drop"), 0) for it in items)
        row = dict(
            key=key, name=cn,
            buy=buy, pickup=pick, drop=drop,
            throw=sum(throws.get(tk, 0) for tk in throw_keys),
        )
        if key in ("he", "fire"):
            dkeys = GRENADE_DMG_KEYS.get(key, [])
            row["damage"] = sum(dmg.get(k, {}).get("d", 0) for k in dkeys)
            row["hits"] = sum(dmg.get(k, {}).get("n", 0) for k in dkeys)
            # 有效投掷：这一颗真的造成了伤害（按 tick 去重）
            row["used"] = sum(used.get(k, 0) for k in dkeys)
            # 局均伤害比累计伤害有参考价值（累计只反映打了多少场）
            row["dmg_per_round"] = (round(row["damage"] / n_rounds, 2)
                                    if n_rounds else None)
            row["dmg_per_use"] = (round(row["damage"] / row["used"], 1)
                                  if row["used"] else None)
        out[key] = row

    # 闪光专项（本人）
    t = conn.execute(
        f"""SELECT COALESCE(SUM(flashes_thrown),0) ft,
                  COALESCE(SUM(flash_duration),0) fd,
                  COALESCE(SUM(enemies_flashed),0) ef
           FROM pms WHERE steamid=? AND {_scope}""", tuple(_args)).fetchone()
    # blinds 表带别名，条件里的 match_id 要带 b. 前缀，不能直接套 _scope
    if match_ids:
        _ph = ",".join("?" * len(match_ids))
        _scope_b = f"b.match_id IN ({_ph})"
        _args_b = [steamid] + list(match_ids)
    else:
        _scope_b = NOT_EX.replace("match_id", "b.match_id")
        _args_b = [steamid]
    # 原来这条连排除局都没过滤：用户手动排除的场次，闪光效率还在里面算
    eff = conn.execute(
        f"""SELECT COUNT(DISTINCT b.tick) n FROM blinds b
            WHERE b.attacker_steamid=? AND {_scope_b}
              AND (b.victim_side IS NULL OR b.attacker_side IS NULL
                   OR b.victim_side != b.attacker_side)""", tuple(_args_b)).fetchone()
    ft = t["ft"] or 0
    ef = t["ef"] or 0
    dur = t["fd"] or 0
    out["flash"].update(
        thrown_self=ft,
        effective=eff["n"] if eff else 0,
        eff_pct=round((eff["n"] / ft * 100), 1) if ft and eff else None,
        duration=round(dur, 2),
        # 每颗闪光的「致盲人秒」——多人叠加会放大，不代表单人被闪多久
        avg_per_throw=round(dur / ft, 2) if ft else None,
        # 最直观：每个被闪到的敌人平均瞎多久
        per_hit=round(dur / ef, 2) if ef else None,
        # 一颗闪平均闪到几个人（>1 说明经常多杀）
        hits_per_throw=round(ef / ft, 2) if ft else None,
        enemies_flashed=ef,
    )
    return out


def duel_stats(conn, steamid: int) -> dict:
    """武器分级对枪：精确版（知道双方手持）。"""
    WEAK = {"手枪", "冲锋枪", "霰弹枪"}
    MAIN = {"步枪", "狙击枪"}

    # ---- 我死在什么武器手里 ----
    died = {}
    for r in conn.execute(
        "SELECT weapon, COUNT(*) c FROM kills WHERE victim_steamid=? GROUP BY weapon",
        (steamid,)):
        t = _tier(r["weapon"])
        died[t] = died.get(t, 0) + r["c"]
    died_total = sum(died.values()) or 1
    weak_n = sum(died.get(t, 0) for t in WEAK)

    # ---- 我用什么武器拿人头 ----
    used = {}
    for r in conn.execute(
        "SELECT weapon, COUNT(*) c FROM kills WHERE attacker_steamid=? GROUP BY weapon",
        (steamid,)):
        t = _tier(r["weapon"])
        used[t] = used.get(t, 0) + r["c"]

    # ---- 精确对枪：我赢=我杀他；我输=他杀我（双方武器都已知）----
    duels = []          # [(my_tier, opp_tier, win?)]
    for r in conn.execute(
        """SELECT weapon my_w, victim_weapon opp_w FROM kills
           WHERE attacker_steamid=? AND victim_weapon IS NOT NULL AND victim_weapon<>''""",
        (steamid,)):
        duels.append((_tier(r["my_w"]), _tier(r["opp_w"]), True))
    for r in conn.execute(
        """SELECT weapon opp_w, victim_weapon my_w FROM kills
           WHERE victim_steamid=? AND victim_weapon IS NOT NULL AND victim_weapon<>''""",
        (steamid,)):
        duels.append((_tier(r["my_w"]), _tier(r["opp_w"]), False))

    def _duel(pred):
        w = [x for x in duels if pred(x) and x[2]]
        l = [x for x in duels if pred(x) and not x[2]]
        n = len(w) + len(l)
        return {"w": len(w), "l": len(l), "n": n,
                "wr": round(len(w) / n * 100) if n else 0}

    # 我用劣势枪 vs 对方主战枪
    disadv = _duel(lambda x: x[0] in WEAK and x[1] in MAIN)
    # 我用主战枪 vs 对方劣势枪
    adv = _duel(lambda x: x[0] in MAIN and x[1] in WEAK)
    # 同等档次（步枪 vs 步枪之类）
    even = _duel(lambda x: (x[0] in MAIN and x[1] in MAIN) or (x[0] in WEAK and x[1] in WEAK))
    # 我拿主战被对方劣劣势枪反杀
    lose_strong = adv["l"]
    weak_death_exact = round(lose_strong / died_total * 100)

    # ---- 经济不对称：我方 ECO/强起 vs 对方全买 ----
    # 分档已改个人口径，这里比较的是「该回合该阵营 5 人的人均 equip_fz」，
    # 不再用 economy.start_eq/end_eq 的团队合计再除 5 近似。
    flags = {}
    a0_side = {}
    for r in conn.execute(
        """SELECT m.id mid,
                  (SELECT first_side FROM players p WHERE p.match_id=m.id AND p.steamid=?) fs,
                  (SELECT a_side FROM rounds r WHERE r.match_id=m.id ORDER BY round LIMIT 1) a0
           FROM matches m""", (steamid,)):
        flags[r["mid"]] = (r["fs"] == r["a0"]) if (r["fs"] and r["a0"]) else True
        a0_side[r["mid"]] = r["a0"]

    # 每回合每阵营的人均装备（round_end.equip_fz 按 side 汇总求人均）。
    # 某人某回合的阵营 = 该回合 a_side；若他的 first_side ≠ 首回合 a_side，则是另一边。
    fz_acc: dict[tuple, list] = {}
    for r in conn.execute(
            """SELECT re.match_id mid, re.round rd, re.equip_fz fz,
                      p.first_side fs, r.a_side a_side
               FROM round_end re
               JOIN rounds r ON r.match_id = re.match_id AND r.round = re.round
               JOIN players p ON p.match_id = re.match_id AND p.steamid = re.steamid
               WHERE re.equip_fz IS NOT NULL
                 AND re.match_id IN (SELECT match_id FROM players WHERE steamid = ?)""",
            (steamid,)):
        a_sd = (r["a_side"] or "T").upper()
        sd = a_sd if r["fs"] == a0_side.get(r["mid"]) else ("CT" if a_sd == "T" else "T")
        cell_fz = fz_acc.setdefault((r["mid"], r["rd"], sd), [0, 0])
        cell_fz[0] += r["fz"]
        cell_fz[1] += 1

    rounds = {}
    for r in conn.execute(
        """SELECT e.match_id mid, e.round rd, e.side sd, e.start_eq, e.end_eq,
                  e.pre_bal, e.post_bal, r.a_side
           FROM economy e JOIN rounds r ON r.match_id=e.match_id AND r.round=e.round"""
    ):
        is_a = flags.get(r["mid"], True)
        a_side = r["a_side"] or "T"
        my_side = a_side if is_a else ("CT" if a_side == "T" else "T")
        agg_fz = fz_acc.get((r["mid"], r["rd"], (r["sd"] or "").upper()))
        bt = _buy_type(r["rd"] or 0, (agg_fz[0] / agg_fz[1]) if agg_fz and agg_fz[1] else None)
        cell = rounds.setdefault((r["mid"], r["rd"]), {})
        cell["mine" if r["sd"] == my_side else "opp"] = bt

    kd_round = {}
    for r in conn.execute(
        """SELECT match_id mid, round rd,
                  SUM(CASE WHEN attacker_steamid=? THEN 1 ELSE 0 END) k,
                  SUM(CASE WHEN victim_steamid=? THEN 1 ELSE 0 END) d
           FROM kills GROUP BY match_id, round""", (steamid, steamid)):
        kd_round[(r["mid"], r["rd"])] = (r["k"] or 0, r["d"] or 0)

    dis = {"rounds": 0, "k": 0, "d": 0}
    advr = {"rounds": 0, "k": 0, "d": 0}
    evr = {"rounds": 0, "k": 0, "d": 0}
    for (mid, rd), cell in rounds.items():
        mine_bt, opp_bt = cell.get("mine"), cell.get("opp")
        if not mine_bt or not opp_bt:
            continue
        k, d = kd_round.get((mid, rd), (0, 0))
        lvl = {"ECO": 0, "强起": 1, "全买": 2, "手枪局": 1}
        mv, ov = lvl.get(mine_bt, 1), lvl.get(opp_bt, 1)
        tgt = dis if mv < ov else (advr if mv > ov else evr)
        tgt["rounds"] += 1
        tgt["k"] += k
        tgt["d"] += d

    def _kd(x):
        return round(x["k"] / max(x["d"], 1), 2)

    return {
        "died_by": [{"t": t, "n": n} for t, n in sorted(died.items(), key=lambda kv: -kv[1])],
        "used_by": [{"t": t, "n": n} for t, n in sorted(used.items(), key=lambda kv: -kv[1])],
        "died_total": sum(died.values()),
        "weak_death_pct": round(weak_n / died_total * 100),
        "weak_death_exact": weak_death_exact,
        "duel_total": len(duels),
        "duel_disadv": disadv,
        "duel_adv": adv,
        "duel_even": even,
        "disadvantage": {**dis, "kd": _kd(dis)},
        "advantage": {**advr, "kd": _kd(advr)},
        "even": {**evr, "kd": _kd(evr)},
    }


def player_list(conn: sqlite3.Connection, min_matches: int | None = None) -> list[dict]:
    """按 steamid 聚合，只保留出现 >= min_matches 场的玩家。

    min_matches 为 None 时读设置里的 player_min_matches（默认 1 = 全列）；
    显式传参（API 的 ?min_matches=）优先。
    设置 0 = 不过滤，列出所有出现过的玩家（含路人）。
    """
    # 读设置里的 player_min_matches（设置页「玩家列表显示门槛」控制的就是这个）。
    # 默认值给 1 而不是 3：5 场 demo 的库里只有 2 人能达到 3 场，
    # 下拉里只出现两个人，用户会以为「切不了」——其实是阈值筛掉了。
    if min_matches is None:
        try:
            import settings as _st
            min_matches = int(_st.get("player_min_matches", 1))
        except Exception:
            min_matches = 1
    min_matches = max(0, int(min_matches))
    # 样本不足（所有人都不够）时退回全部，否则新用户只有 1-2 场会看到空列表
    # is_me 的那条永远保留，即使场次少
    rows = [dict(r) for r in conn.execute(
        """SELECT p.steamid,
                  (SELECT p2.name FROM players p2
                    WHERE p2.steamid=p.steamid AND p2.name IS NOT NULL AND p2.name<>''
                    ORDER BY p2.match_id DESC LIMIT 1) name,
                  MAX(p.is_me) is_me,
                  -- 场次统计必须和概览同口径：被标记「不算数」的局不进 matches，
                  -- 单独放到 excluded 里给前端提示。之前这里数全表 pms，
                  -- 出现「下拉 24 场 / 概览 22 场」的对不上（差的就是 excluded 的局）。
                  (SELECT COUNT(*) FROM pms x WHERE x.steamid=p.steamid
                    AND x.match_id IN (SELECT id FROM matches
                                        WHERE excluded IS NULL OR excluded=0)) matches,
                  (SELECT COUNT(*) FROM pms x WHERE x.steamid=p.steamid
                    AND x.match_id IN (SELECT id FROM matches
                                        WHERE excluded=1)) excluded
           FROM players p
           GROUP BY p.steamid
           ORDER BY is_me DESC, matches DESC, p.steamid""")]

    kept = [r for r in rows if r["is_me"] or (r["matches"] or 0) >= min_matches]
    return kept if kept else rows
