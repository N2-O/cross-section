"""基于 awpy 的解析层 —— 替换原 ingest_core 的解析与统计。

为什么换
--------
1. 速度：awpy 解析 230MB demo 约 1.5 秒，原实现 1-2 分钟
2. 口径：ADR/KAST 由 awpy 的 stats 提供，伤害按剩余血量截断
   （原实现直接 sum dmg_health，overkill 全算，ADR 虚高 40%+）
3. 字段更全：trade / clutch / flash_assists / 购买事件 / 致盲事件

数据流
------
awpy.Demo.load(...) → 写入 SQLite（保留原始事件 + 已算好的指标）
     ↓
stats_api / ability / api_v1 从 SQLite 读（不再自己算基础指标）
"""
from __future__ import annotations

import hashlib
import os
import sqlite3

from awpy import Demo

import store2

VERSION = "awpy-3.1.1"

# awpy 用 terrorist / counter-terrorist
SIDE_MAP = {"terrorist": "T", "counter-terrorist": "CT", "t": "T", "ct": "CT"}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_time(path: str, duration_s: float = 0.0) -> str:
    """比赛**开始**时间。

    demo 文件名里的 `id >> 31` 是「比赛结束」时刻，而 Steam 比赛历史页显示的是
    「开始」时刻，两者差一整场时长。实测 match 73（de_vertigo）：结束 15:22、
    时长 19:42、算出开始 15:02，Steam 页写 15:01:53 —— 对得上。
    所以这里减掉 duration_s 对齐 Steam 口径，否则用户会看到稳定的 ~20 分钟偏差。
    """
    import datetime
    t = store2.demo_real_time(os.path.basename(path))
    if t:
        try:
            dt = datetime.datetime.strptime(t, "%Y-%m-%d %H:%M")
            if duration_s and duration_s > 0:
                dt -= datetime.timedelta(seconds=float(duration_s))
            return dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            return t
    return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")


def _side(v) -> str | None:
    if v is None:
        return None
    return SIDE_MAP.get(str(v).lower())


def _resolve_me(conn, roster_sids, given=None):
    """决定本场的「我」是谁：settings 配置 > 传入参数 > 库里历史值。

    三者都**必须真的出现在本场名单里**，否则返回 None（这场按「无我」处理）。
    以前这里直接继承 matches 表里最近一个非空 my_steamid，一个脏值会被一场一场
    传下去——真实案例：库里 25 场全写成 ...970（本人 ...967），于是每场都取不到
    my_side0，a_side 退化成硬编码的 T，比分/胜负/胜率整体算错。
    """
    try:
        roster_sids = {int(x) for x in roster_sids}
    except Exception:
        return None
    cands = []
    try:
        import settings as _st
        for k in ("my_steamid", "steamid"):
            v = str(_st.get(k, "") or "").strip()
            if v.isdigit():
                cands.append(int(v))
    except Exception:
        pass
    if given:
        try:
            cands.append(int(given))
        except (TypeError, ValueError):
            pass
    try:
        for r in conn.execute(
                "SELECT my_steamid m, COUNT(*) c FROM matches "
                "WHERE my_steamid IS NOT NULL GROUP BY my_steamid "
                "ORDER BY c DESC LIMIT 5"):
            if r["m"]:
                cands.append(int(r["m"]))
    except Exception:
        pass
    for c in cands:
        if c in roster_sids:
            return c
    return None


# ---------- 武器分类：急停只对「枪械」有意义 ----------
# weapon_fire 不区分开枪和投掷——扔闪光/手雷/燃烧瓶、挥刀都会触发它。
# 移动投掷是常态，把这些算进急停的分母会让指标失真（实测 105 次道具/刀里
# 有 86% 被判成「超阈值」，纯属噪声）。
# 注意 flashbang 不含 "grenade" 字样，不能只靠关键字判断。
UTIL_WEAPONS = {
    "flashbang", "flashgrenade", "hegrenade", "smokegrenade", "molotov",
    "incgrenade", "decoy", "snowball", "tagrenade", "breachcharge",
    "bumpmine", "sensorgrenade",
}
MELEE_WEAPONS = {"taser", "knife", "knife_t", "knife_gypsy_jackknife",
                 "knife_bayonet", "knife_m9_bayonet", "knife_karambit"}


def is_gun(weapon) -> bool:
    """该 weapon_fire 是否属于「开枪」（急停、命中率这类指标只该看它）。"""
    w = str(weapon or "").replace("weapon_", "").lower()
    if not w:
        return False
    if w in UTIL_WEAPONS or w in MELEE_WEAPONS:
        return False
    if w.startswith("knife") or w.endswith("grenade"):
        return False
    return True


def _i(v, default=0) -> int:
    try:
        if v is None or v != v:
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def _f(v, default=0.0) -> float:
    try:
        if v is None or v != v:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _side_of(fs, rnd, half: int = 12) -> str:
    """某人第 rnd 回合的阵营。fs = 第一半场阵营（"T"/"CT"）。

    CS2 常规 12 回合半场；加时每 3 回合换边，起点延续第二半场。
    与 ingest_awpy 内部的 side_of 同义 —— 提到模块级是为了让 damage 段
    （判友伤）也能用，那段在内部 side_of 定义之前执行。
    """
    s = fs or "T"
    o = "CT" if s == "T" else "T"
    if rnd <= half:
        return s
    if half == 12:
        if rnd <= 24:
            return o
        ot = (rnd - 25) // 3
        return o if ot % 2 == 0 else s
    return o


def ingest_awpy(conn: sqlite3.Connection, demo_path: str,
                my_steamid: int | None = None, log=print,
                force: bool = False) -> int:
    fh = sha256(demo_path)
    row = conn.execute("SELECT id FROM matches WHERE file_hash=?", (fh,)).fetchone()
    if row and not force:
        log(f"  已在库中（match {row['id']}），跳过")
        return int(row["id"])
    if row and force:
        old = int(row["id"])
        log(f"  重新解析：清空旧数据（match {old}）")
        with conn:
            # 清单统一在 store2.MATCH_CHILD_TABLES 维护。曾因这里漏了
            # grenade_use/spend_cat/weapon_stat/round_end，重解析 4 次后
            # 这四张表 92% 是孤儿行，闪光投出从 35 涨到 210。
            for t in store2.MATCH_CHILD_TABLES:
                try:
                    conn.execute(f"DELETE FROM {t} WHERE match_id=?", (old,))
                except sqlite3.OperationalError:
                    pass
            conn.execute("DELETE FROM matches WHERE id=?", (old,))
            conn.execute("UPDATE demos SET analyzed=0, match_id=NULL WHERE match_id=?", (old,))

    log("  awpy 解析中…")
    dem = Demo(demo_path)
    # 只加载真正用到的：grenades / fires / smokes / round_economy 全项目零引用，
    # 白等它们解析完（实测占 dem.load 的一部分）。
    dem.load("rounds", "kills", "damages", "stats",
             "shots", "item_events", "bomb", "blinds")

    hdr = dem.header or {}
    map_name = hdr.get("map_name") or ""
    server = hdr.get("server_name") or ""
    platform = store2.detect_platform(server) if hasattr(store2, "detect_platform") else ""

    rounds = dem.rounds
    kills = dem.kills
    dmg = dem.damages
    stats = dem.stats

    log("采样位置快照")
    # ---------- 一次性快照采样 ----------
    # 原来分 5 次调 dem.snapshots()，每次重扫一遍 demo，合计约 5 秒。
    # 所有需要的 tick 都来自 rounds / kills / shots，load 完就能算全，
    # 所以这里一次采完，后面各处查索引即可。
    _snap_at: dict[int, list] = {}
    try:
        _ticks: set[int] = set()
        for _r in rounds.iter_rows(named=True):
            _fz, _et = _r["freeze_end_tick"], _r["end_tick"]
            # 回合开始 tick：钱包法算花费要用「回合开始现金」
            _st = _r["start_tick"]
            if _st is not None:
                _ticks.add(int(_st))
                # buytime 结束 = 回合开始 + 20 秒（mp_buytime 默认 20s，从回合开始算）。
                # freeze time 常见只有 15 秒，freeze_end 之后还能买枪，钱包法要拿这个
                # 时刻的钱包当终点，否则 freeze 后买的枪（如 R8 的 Nova）整把漏算。
                _bt = int(_st) + 20 * 64
                if _et is None or _bt <= int(_et):
                    _ticks.add(_bt)
            if _fz is not None:
                _ticks.add(int(_fz))
            if _et is not None:
                _ticks.add(int(_et))
                if int(_et) > 128:
                    _ticks.add(int(_et) - 64)      # 回合判定前 1 秒（保枪采样）
        for _k in kills.iter_rows(named=True):
            if _k["tick"] is not None:
                _ticks.add(int(_k["tick"]))
        try:
            for _s in dem.shots.iter_rows(named=True):
                if _s["tick"] is not None:
                    _ticks.add(int(_s["tick"]))
        except Exception:
            pass
        if _ticks:
            _blob = dem.snapshots(ticks=sorted(_ticks))
            for _srow in _blob.iter_rows(named=True):
                _snap_at.setdefault(int(_srow["tick"]), []).append(_srow)
        log(f"  快照采样 {len(_ticks)} 个时刻 / {len(_blob) if _ticks else 0} 行")
    except Exception as _e:
        log(f"  [warn] 快照批量采样失败: {type(_e).__name__}: {_e}")

    # 钱包法的「购买结束」时刻：buytime 结束（回合开始 + 20 秒），不是 freeze_end。
    # CS2 的 mp_buytime 默认 20 秒且从回合开始算，freeze time 实测常见只有 15 秒，
    # 中间那 5 秒照样能买枪 —— 用 freeze_end 当终点会把这段买的东西整把漏算
    # （实测某局 R8 真花 2050，freeze_end 口径只算出 1000）。该 tick 没采到、或回合
    # 在 buytime 结束前就打完了，退回 freeze_end_tick。
    wallet_end: dict[int, int] = {}
    for _r in rounds.iter_rows(named=True):
        if _r["start_tick"] is None:
            continue
        _rn = int(_r["round_num"])
        _fz_r, _et_r = _r["freeze_end_tick"], _r["end_tick"]
        _bt_r = int(_r["start_tick"]) + 20 * 64
        if _bt_r in _snap_at and (_et_r is None or _bt_r <= int(_et_r)):
            wallet_end[_rn] = _bt_r
        elif _fz_r is not None:
            wallet_end[_rn] = int(_fz_r)

    if len(rounds) == 0:
        raise RuntimeError("没有可识别的回合")

    # ---------- 回合边界表（用于 tick → round 映射）
    bounds = []
    for r in rounds.iter_rows(named=True):
        s = r["start_tick"] if r["start_tick"] is not None else r["freeze_end_tick"]
        e = r["end_tick"]
        if s is None or e is None:
            continue
        bounds.append((int(s), int(e), int(r["round_num"])))
    bounds.sort()

    def tick_round(tk) -> int | None:
        tk = int(tk)
        for s, e, rn in bounds:
            if s <= tk <= e:
                return rn
        # 落在回合间隙：取前一个回合
        prev = None
        for s, e, rn in bounds:
            if tk > e:
                prev = rn
        return prev

    # ---------- 玩家与首回合阵营
    # 第一回合的 kills 里能看出阵营；没有击杀时退化到 0
    first_round = bounds[0][2] if bounds else 1
    pside: dict[int, str] = {}
    pname: dict[int, str] = {}
    for k in kills.iter_rows(named=True):
        if tick_round(k["tick"]) != first_round:
            continue
        if k["attacker_steamid"]:
            pside.setdefault(int(k["attacker_steamid"]), _side(k["attacker_side"]) or "")
            pname.setdefault(int(k["attacker_steamid"]), k["attacker_name"] or "")
        if k["victim_steamid"]:
            pside.setdefault(int(k["victim_steamid"]), _side(k["victim_side"]) or "")
            pname.setdefault(int(k["victim_steamid"]), k["victim_name"] or "")

    # stats 表里有全部 10 人，用它补齐名字与阵营
    for s in stats.iter_rows(named=True):
        sid = int(s["steamid"])
        pname.setdefault(sid, s["name"] or "")
        if sid not in pside:
            # 从 kills 任取一条该玩家的阵营
            for k in kills.iter_rows(named=True):
                if k["attacker_steamid"] and int(k["attacker_steamid"]) == sid:
                    pside[sid] = _side(k["attacker_side"]) or "T"
                    break
                if k["victim_steamid"] and int(k["victim_steamid"]) == sid:
                    pside[sid] = _side(k["victim_side"]) or "T"
                    break

    # 「我」必须真的在场：settings 配置优先，其次传入值/库里历史值，
    # 都不在本场名单里就返回 None —— 宁可这场标「无我」，也不能拿别人的队
    # 冒充我方（旧逻辑继承脏值后 a_side 会退化成 T，胜负和比分全错）。
    my_steamid = _resolve_me(conn, pside.keys(), my_steamid)

    log("写入回合与击杀")
    # ---------- 写 matches
    total_ticks = int(rounds["end_tick"].max())
    with conn:
        cur = conn.execute(
            """INSERT INTO matches (file, file_hash, map, server, platform, played_at,
                                    tickrate, total_ticks, duration_s, my_steamid)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (os.path.basename(demo_path), fh, map_name, server, platform,
             _file_time(demo_path, total_ticks / 64.0), 64, total_ticks,
             round(total_ticks / 64.0, 1), my_steamid))
        mid = int(cur.lastrowid)

        store2.insert_players(conn, mid, [
            dict(match_id=mid, steamid=sid, name=pname.get(sid, ""),
                 first_side=pside.get(sid) or "T",
                 is_me=int(sid == my_steamid) if my_steamid else 0,
                 left_round=0, joined_round=0, left_reason=None, reconnect_round=0)
            for sid in pname])

        # ---------- 写 rounds
        rrows = []
        for r in rounds.iter_rows(named=True):
            s = r["start_tick"] if r["start_tick"] is not None else r["freeze_end_tick"]
            fz = r["freeze_end_tick"] if r["freeze_end_tick"] is not None else s
            e = r["end_tick"]
            wside = _side(r["winner_side"])
            # A 队 = 第一回合出现在 kills 里的任一玩家的首回合阵营，取数据里 winner_side 反推不可行
            rrows.append(dict(
                match_id=mid, round=int(r["round_num"]),
                t_start=_i(s), t_freeze=_i(fz), t_end=_i(e),
                winner=wside or "", reason=r["reason_name"] or "",
                a_side="", a_win=0,
                paused_sec=round(max(0.0, (_i(e) - _i(fz)) / 64.0 - 115.0), 1)))
        store2.insert_many(conn, "rounds", rrows)

        # 投降局：整场投了，最后一个回合的 reason 会记成 `terrorists surrender`
        # 或 `ct surrender`。这种局后面是故意放掉的，混进平均值会把 ADR/KAST 拉低，
        # 自动标 excluded，理由写清楚（用户仍然可以在 demos 页改回来）。
        _sur = [x["reason"] for x in rrows
                if "surrender" in str(x.get("reason") or "").lower()]
        if _sur:
            conn.execute(
                "UPDATE matches SET excluded=1, exclude_note=? WHERE id=?",
                (f"投降（{_sur[0]}）", mid))

    # A 队（a_side）在 side_of 定义之后统一回填（见 pms 段）

    # ---------- 写 kills
    # 跳跃击杀：awpy 的 kills 没有该字段，用 snapshots 在击杀同 tick 上取 is_jumping
    jump_map: dict[tuple, int] = {}
    try:
        for _t in sorted({_i(k["tick"]) for k in kills.iter_rows(named=True)}):
            for s in _snap_at.get(_t, []):
                sid2 = int(s["steamid"]) if s["steamid"] else None
                if sid2:
                    jump_map[(sid2, _i(s["tick"]))] = 1 if s["is_jumping"] else 0
    except Exception as e:
        log(f"  [warn] 跳跃判定失败: {type(e).__name__}: {e}")

    krows = []
    for k in kills.iter_rows(named=True):
        rn = tick_round(k["tick"])
        ax, ay = _f(k["attacker_x"]), _f(k["attacker_y"])
        vx, vy = _f(k["victim_x"]), _f(k["victim_y"])
        dist = ((ax - vx) ** 2 + (ay - vy) ** 2) ** 0.5 if (ax or ay) and (vx or vy) else None
        krows.append(dict(
            match_id=mid, round=rn or 0, tick=_i(k["tick"]),
            attacker_steamid=int(k["attacker_steamid"]) if k["attacker_steamid"] else None,
            victim_steamid=int(k["victim_steamid"]) if k["victim_steamid"] else None,
            assister_steamid=int(k["assister_steamid"]) if k["assister_steamid"] else None,
            weapon=k["weapon"] or "",
            victim_weapon=None,
            headshot=int(bool(k["headshot"])),
            penetrated=int(bool(k["penetrated"])),
            noscope=int(bool(k["noscope"])),
            thrusmoke=int(bool(k["thrusmoke"])),
            attackerblind=0,
            jumping=jump_map.get((int(k["attacker_steamid"]) if k["attacker_steamid"] else 0,
                                  _i(k["tick"])), 0),
            dmg_health=0, dmg_armor=0,
            distance=round(dist, 1) if dist else None,
            hitgroup=k["hitgroup_name"] or ""))
    store2.insert_many(conn, "kills", krows)

    # ---------- 写 damage
    # 口径：awpy 的 dmg_health 是原始值，含过量击杀（血不满还打 80）与死后补枪，
    # 直接 SUM 会偏高 30%+。valid = 按受害者剩余血量截断、死后命中记 0。
    # 同一受害者一回合可能被多人依次打，必须按 (round, victim, tick) 顺序扣血。
    death_tick: dict[tuple, int] = {}
    for k in krows:
        v = k["victim_steamid"]
        if v:
            death_tick[(k["round"], v)] = k["tick"]

    drows = []
    for d in dmg.iter_rows(named=True):
        drows.append(dict(
            match_id=mid, round=tick_round(d["tick"]) or 0, tick=_i(d["tick"]),
            attacker_steamid=int(d["attacker_steamid"]) if d["attacker_steamid"] else None,
            victim_steamid=int(d["victim_steamid"]) if d["victim_steamid"] else None,
            weapon=d["weapon"] or "",
            dmg_health=_i(d["dmg_health"]), dmg_armor=_i(d["dmg_armor"]),
            hitgroup=d["hitgroup_name"] or ""))
    drows.sort(key=lambda r: (r["round"], r["victim_steamid"] or 0, r["tick"]))

    remain: dict[tuple, int] = {}
    dmg_raw_sum = 0
    dmg_valid_sum = 0
    for r in drows:
        raw = r["dmg_health"]
        v = r["victim_steamid"]
        dmg_raw_sum += raw
        if not v:
            r["valid"] = raw          # 无受害者（环境伤害/自杀等）不做截断
        else:
            key = (r["round"], v)
            dk = death_tick.get(key)
            if dk is not None and r["tick"] > dk:
                r["valid"] = 0        # 死后命中，不计
            else:
                left = remain.get(key, 100)
                r["valid"] = max(0, min(raw, left))
                remain[key] = left - r["valid"]
        # 友伤：同阵营的伤害不计入个人伤害 —— CS2 官方 ADR/HUD 只统计对敌人的伤害。
        # pside 存的是各人「第一半场阵营」，配合 _side_of 还原该回合的实际阵营，
        # 换边后（R13 起）判断依然正确。自杀同理归零（a == v 时阵营相同）。
        a = r["attacker_steamid"]
        if r["valid"] and a and v:
            sa, sv = pside.get(a), pside.get(v)
            # 缺任一方阵营信息就不判（宁可照算，也不能凭默认值误判成友伤）
            if sa and sv and _side_of(sa, r["round"]) == _side_of(sv, r["round"]):
                r["valid"] = 0
        dmg_valid_sum += r["valid"]
    store2.insert_many(conn, "damage", drows)
    if dmg_raw_sum:
        log(f"[口径] 伤害合计 原始 {dmg_raw_sum} → 有效 {dmg_valid_sum}"
            f"（{(dmg_valid_sum - dmg_raw_sum) / dmg_raw_sum * 100:+.1f}%）")

    log("统计射击与经济")
    # ---------- 扩展：射击 / 经济 / 目标 / 存活 / 保枪
    fire_map: dict[tuple, int] = {}
    hit_keys: set[tuple] = set()
    imprecise_map: dict[tuple, int] = {}
    stopped_map: dict[tuple, int] = {}
    gun_fire_map: dict[tuple, int] = {}      # 只算枪械的开火数（急停的分母）
    speed_map: dict[tuple, float] = {}
    # 34 units/s 是 CS2 步枪还能精确射击的速度上限，超过就是没停住。
    STOP_SPEED_MAX = 34.0
    try:
        shots = dem.shots

        # 急停判定：看开火瞬间的移动速度，不用 inaccuracy。
        # awpy 的 inaccuracy 读的是武器的 m_fAccuracyPenalty（连发累积的精度惩罚），
        # 官方源码注释写明「a proxy for inaccuracy; CS2 does not network the
        # fully-computed inaccuracy」——真正的散布由引擎实时算，不写进 demo。
        # 实测也印证：速度 0-5 与 120+ 的开火，inaccuracy 中位数几乎相同。

        for _t in sorted({_i(s["tick"]) for s in shots.iter_rows(named=True)
                          if s["tick"] is not None}):
            for r in _snap_at.get(_t, []):
                if r["steamid"] is None:
                    continue
                speed_map[(int(r["steamid"]), _i(r["tick"]))] = float(r["velocity"] or 0)

        for s in shots.iter_rows(named=True):
            sid = int(s["steamid"]) if s["steamid"] else None
            if not sid:
                continue
            rn = tick_round(s["tick"]) or 0
            k = (sid, rn)
            fire_map[k] = fire_map.get(k, 0) + 1          # 总开火（含投掷与挥刀）
            # 急停只对枪械有意义：扔道具、挥刀也会触发 weapon_fire，
            # 而移动投掷是常态，混进来会把指标污染成噪声。
            if is_gun(s["weapon"]):
                gun_fire_map[k] = gun_fire_map.get(k, 0) + 1
                sp = speed_map.get((sid, _i(s["tick"])))
                if sp is not None:
                    if sp <= STOP_SPEED_MAX:
                        stopped_map[k] = stopped_map.get(k, 0) + 1
                    else:
                        imprecise_map[k] = imprecise_map.get(k, 0) + 1
            hit_keys.add((sid, int(s["tick"])))

        # 命中判定：开火 tick 与 player_hurt tick 配对（实测 94.5% 同 tick，容差 ±2）
        hit_map: dict[tuple, int] = {}
        for d in dmg.iter_rows(named=True):
            sid = int(d["attacker_steamid"]) if d["attacker_steamid"] else None
            if not sid:
                continue
            tk = int(d["tick"])
            for delta in (0, 1, -1, 2, -2):
                if (sid, tk + delta) in hit_keys:
                    k = (sid, tick_round(tk + delta) or 0)
                    hit_map[k] = hit_map.get(k, 0) + 1
                    break
    except Exception as e:
        log(f"  [warn] 射击统计失败: {type(e).__name__}: {e}")

    # 个人花费：钱包法。spent = 回合开始现金 − buytime 结束现金（t_start + 20s）。
    # 退款、护甲、买枪送人都在钱包曲线上自然体现，不用逐个事件加减。
    # 注意终点不能取 freeze_end：freeze 之后还有几秒可以买枪（见 wallet_end）。
    # 主口径已改为引擎 m_iCashSpentThisRound，这里只做兜底与对账。
    spent_map: dict[tuple, int] = {}
    start_money: dict[tuple, int] = {}     # (sid, round) -> 回合开始现金
    try:
        for _r in rounds.iter_rows(named=True):
            rn = int(_r["round_num"])
            _st, _fz = _r["start_tick"], _r["freeze_end_tick"]
            _we = wallet_end.get(rn)          # 终点点位：buytime 结束（退回 freeze_end）
            if _we is None:
                continue
            _fz_i = int(_fz) if _fz is not None else _we
            # 起点优先用 start_tick 快照；缺了退到回合内最早的一帧
            _cands: list[int] = []
            if _st is not None:
                _cands.append(int(_st))
            _cands += [t for t in sorted(_snap_at)
                       if (_st is None or t >= int(_st)) and t <= _fz_i
                       and t not in _cands]
            for _t in _cands:
                for s in _snap_at.get(_t, []):
                    sid = int(s["steamid"]) if s["steamid"] else None
                    if not sid or s["money"] is None:
                        continue
                    start_money.setdefault((sid, rn), _i(s["money"]))
            for s in _snap_at.get(_we, []):
                sid = int(s["steamid"]) if s["steamid"] else None
                if not sid or s["money"] is None:
                    continue
                a = start_money.get((sid, rn))
                if a is None:
                    continue            # 起点缺失：跳过，下游显示为空而不是 0
                spent_map[(sid, rn)] = max(0, a - _i(s["money"]))
    except Exception as e:
        log(f"  [warn] 花费统计失败: {type(e).__name__}: {e}")

    # 目标：安包 / 拆包
    plant_map: dict[int, int] = {}
    defuse_map: dict[int, int] = {}
    try:
        for b in dem.bomb.iter_rows(named=True):
            if not b["steamid"]:
                continue
            sid = int(b["steamid"])
            if b["event"] == "finish_plant":
                plant_map[sid] = plant_map.get(sid, 0) + 1
            elif b["event"] == "defuse":
                defuse_map[sid] = defuse_map.get(sid, 0) + 1
    except Exception as e:
        log(f"  [warn] 目标事件失败: {type(e).__name__}: {e}")

    # 装备价值（buytime 结束时）+ 回合末存活/装备
    equip_fz: dict[tuple, int] = {}
    equip_start: dict[tuple, int] = {}
    money_fz: dict[tuple, int] = {}
    cash_start: dict[tuple, int] = {}       # 回合开始现金（start_tick 快照）
    money_end: dict[tuple, int] = {}        # 回合判定前 1 秒的现金
    equip_end: dict[tuple, int] = {}        # 回合判定前 1 秒的装备价值
    alive_end: dict[tuple, int] = {}        # 回合判定前 1 秒是否存活
    try:
        # 回合初继承装备：equipment_value_round_start 字段本身记录的就是回合初值，
        # 采样点保持 freeze_end 快照即可。同一帧顺手记下 freeze_end 时的装备价值，
        # 作为 equip_fz 的兜底（buytime 结束帧缺失时回退）。
        for _t in [int(r["freeze_end_tick"]) for r in rounds.iter_rows(named=True)
                   if r["freeze_end_tick"] is not None]:
            for s in _snap_at.get(_t, []):
                sid = int(s["steamid"]) if s["steamid"] else None
                if not sid:
                    continue
                rn = tick_round(s["tick"]) or 0
                equip_start[(sid, rn)] = _i(s["equipment_value_round_start"])
                if s["equipment_value"] is not None:
                    equip_fz.setdefault((sid, rn), _i(s["equipment_value"]))
        # 买完后的装备 + 终点现金：都取 buytime 结束那一刻（不是 freeze_end，见 wallet_end 注释）。
        # equip_fz 必须用这个点位，否则那 5 秒里买的枪会整把漏算（实测 R8 买到 2250
        # 却被记成 1200，购买分档误判成 ECO）。上面的 freeze_end 值只在缺帧时保留。
        for _rn, _we in wallet_end.items():
            for s in _snap_at.get(_we, []):
                sid = int(s["steamid"]) if s["steamid"] else None
                if not sid:
                    continue
                if s["equipment_value"] is not None:
                    equip_fz[(sid, _rn)] = _i(s["equipment_value"])
                if s["money"] is None:
                    continue
                money_fz[(sid, _rn)] = _i(s["money"])
        # 回合开始现金：口径与钱包法的起点一致（start_tick 快照的 money）
        for _r in rounds.iter_rows(named=True):
            if _r["start_tick"] is None:
                continue
            rn = int(_r["round_num"])
            for s in _snap_at.get(int(_r["start_tick"]), []):
                sid = int(s["steamid"]) if s["steamid"] else None
                if not sid or s["money"] is None:
                    continue
                cash_start[(sid, rn)] = _i(s["money"])
        # end_tick 时玩家状态已重置（health 全 0），采样点改到回合判定前 1 秒
        for _t in [int(r["end_tick"]) - 64 for r in rounds.iter_rows(named=True)
                   if r["end_tick"] is not None and int(r["end_tick"]) > 128]:
            for s in _snap_at.get(_t, []):
                sid = int(s["steamid"]) if s["steamid"] else None
                if not sid:
                    continue
                rn = tick_round(s["tick"]) or 0
                _hp = _i(s["health"])
                equip_end[(sid, rn)] = _i(s["equipment_value"]) if _hp > 0 else 0
                alive_end[(sid, rn)] = 1 if _hp > 0 else 0
                money_end[(sid, rn)] = _i(s["money"])
    except Exception as e:
        log(f"  [warn] 装备采样失败: {type(e).__name__}: {e}")

    # ---------- 存活回合：由「死亡发生的回合」反推    # 不能用 snapshots 的 end_tick 判活 —— 那时回合已结算，health 早被重置，
    # 会导致存活率虚低（曾经算出 13%，真实约 11%）。
    death_rounds: dict[int, set] = {}
    for k in kills.iter_rows(named=True):
        if not k["victim_steamid"]:
            continue
        sid = int(k["victim_steamid"])
        rn = tick_round(k["tick"])
        if rn:
            death_rounds.setdefault(sid, set()).add(rn)

    # ---------- 写 pms（awpy.stats 直接落库，再补算阵营拆分与评分）
    n_rounds = len(bounds)
    # CS2 固定 12 回合换边，跟比赛多早结束无关。
    # 旧写法 n_rounds//2 会让 17 回合的比赛把 R9 之后判成"下半场"，阵营全错。
    half = 12

    def side_of(fs: str, rnd: int) -> str:
        """CS2 阵营：常规 12 回合半场；加时每 3 回合换边，起点延续第二半场。"""
        s = fs or "T"
        o = "CT" if s == "T" else "T"
        if rnd <= half:
            return s
        if half == 12:
            if rnd <= 24:
                return o
            ot = (rnd - 25) // 3
            return o if ot % 2 == 0 else s
        return o

    # A 队（a_side）：**上半场打 T 的那队**，与「我」是谁无关。
    # 换边后跟着变（side_of 从 "T" 起算）。这样即使本场没识别出我，每回合的
    # 客观成败也有值 —— 旧逻辑在这种情况下写 a_win=0，导致比分显示成 0:总回合数、
    # 胜场统计也全归零。「我在哪一队」由 players.first_side（my_side）另行判断。
    with conn:
        for rr in conn.execute("SELECT round, winner FROM rounds WHERE match_id=?", (mid,)):
            a_side = side_of("T", int(rr["round"]))
            a_win = int(rr["winner"] == a_side)
            conn.execute("UPDATE rounds SET a_side=?, a_win=? WHERE match_id=? AND round=?",
                         (a_side, a_win, mid, rr["round"]))

    # 每人每阵营的回合数 + 击杀/死亡/原始伤害
    agg: dict[int, dict] = {}
    for sid, fs in pside.items():
        d = {"T": {"rounds": 0, "k": 0, "d": 0, "raw": 0},
             "CT": {"rounds": 0, "k": 0, "d": 0, "raw": 0}}
        for rn in range(1, n_rounds + 1):
            d[side_of(fs, rn)]["rounds"] += 1
        agg[sid] = d

    for k in kills.iter_rows(named=True):
        # 自杀/环境死亡（attacker == victim，如摔死、被自己的火烧死）
        # 不算击杀——awpy 的 stats.kills 也不计，两边口径必须一致，
        # 否则 tkills + ct_kills 会比 kills 多出几次环境死亡。
        if k["attacker_steamid"] and k["attacker_steamid"] != k["victim_steamid"]:
            sid = int(k["attacker_steamid"])
            sd = _side(k["attacker_side"])
            if sid in agg and sd in agg[sid]:
                agg[sid][sd]["k"] += 1
        if k["victim_steamid"]:
            sid = int(k["victim_steamid"])
            sd = _side(k["victim_side"])
            if sid in agg and sd in agg[sid]:
                agg[sid][sd]["d"] += 1
    for x in dmg.iter_rows(named=True):
        if x["attacker_steamid"]:
            sid = int(x["attacker_steamid"])
            sd = _side(x["attacker_side"])
            if sid in agg and sd in agg[sid]:
                agg[sid][sd]["raw"] += _i(x["dmg_health"])

    # 穿透/混烟/盲狙击杀（按进攻方统计）
    special: dict[int, dict] = {}
    for k in kills.iter_rows(named=True):
        if not k["attacker_steamid"]:
            continue
        sid = int(k["attacker_steamid"])
        d = special.setdefault(sid, {"pen": 0, "smoke": 0, "noscope": 0, "trade": 0})
        if k["penetrated"]:
            d["pen"] += 1
        if k["thrusmoke"]:
            d["smoke"] += 1
        if k["noscope"]:
            d["noscope"] += 1
        if k["is_trade"]:
            d["trade"] += 1

    prows = []
    # ---------- 按阵营拆的首杀 / 首死 ----------
    # 总 FK/FD 由 awpy 给，但没有 T/CT 拆分，判断不了「T 方首死是否集中」。
    # 这里从击杀事件流取每回合的第一个有效击杀，按每名玩家在该回合的阵营归类
    # （不只算本人，否则切换选中玩家时别人的这四列全是 0）。
    side_fk: dict[int, dict[str, int]] = {}
    side_fd: dict[int, dict[str, int]] = {}
    try:
        _first: dict[int, tuple[int, int]] = {}
        for k in sorted(kills.iter_rows(named=True),
                        key=lambda x: _i(x["tick"])):
            atk = _i(k["attacker_steamid"])
            vic = _i(k["victim_steamid"])
            if not atk or atk == vic:
                continue            # 环境死亡/自杀不算首杀事件
            rn = tick_round(k["tick"])
            if rn is None or rn in _first:
                continue
            _first[rn] = (atk, vic)
        for rn, (atk, vic) in _first.items():
            for sid_p, fs_p in pside.items():
                sd_p = side_of(fs_p, rn)
                if sd_p not in ("T", "CT"):
                    continue
                if atk == sid_p:
                    side_fk.setdefault(sid_p, {"T": 0, "CT": 0})[sd_p] += 1
                if vic == sid_p:
                    side_fd.setdefault(sid_p, {"T": 0, "CT": 0})[sd_p] += 1
    except Exception as e:
        log(f"  [warn] 分阵营 FK/FD 失败: {type(e).__name__}: {e}")
    # 汇总到人（fire/hit/imprecise 是 (sid, round) 粒度，这里按人求和）
    def sum_by_sid(m: dict) -> dict[int, int]:
        out: dict[int, int] = {}
        for (s2, _rn), v in m.items():
            out[s2] = out.get(s2, 0) + v
        return out

    fire_by = sum_by_sid(fire_map)
    hit_by = sum_by_sid(hit_map)
    imp_by = sum_by_sid(imprecise_map)
    stop_by = sum_by_sid(stopped_map)
    gunfire_by = sum_by_sid(gun_fire_map)
    spent_by = sum_by_sid(spent_map)
    equip_by = sum_by_sid(equip_fz)
    equip_start_by = sum_by_sid(equip_start)

    for s in stats.iter_rows(named=True):
        sid = int(s["steamid"])
        rd = max(1, _i(s["rounds_played"]))
        a = agg.get(sid) or {"T": {"rounds": 0, "k": 0, "d": 0, "raw": 0},
                             "CT": {"rounds": 0, "k": 0, "d": 0, "raw": 0}}
        sp = special.get(sid, {"pen": 0, "smoke": 0, "noscope": 0, "trade": 0})

        adr = _f(s["adr"])
        total_dmg = round(adr * rd)          # 与 awpy 的截断口径一致
        raw_all = a["T"]["raw"] + a["CT"]["raw"]
        # 截断后的总伤害按原始伤害比例分摊到两阵营，保证合计一致
        def split(raw_side):
            return round(total_dmg * raw_side / raw_all) if raw_all else 0

        prows.append(dict(
            match_id=mid, steamid=sid,
            rounds=rd,
            t_rounds=a["T"]["rounds"], ct_rounds=a["CT"]["rounds"],
            kills=_i(s["kills"]), deaths=_i(s["deaths"]), assists=_i(s["assists"]),
            hs=_i(s["headshot_kills"]),
            dmg=total_dmg,
            adr=adr, kast=_f(s["kast"]),
            rating=0.0, impact=0.0,
            kpr=round(_i(s["kills"]) / rd, 3),
            dpr=round(_i(s["deaths"]) / rd, 3),
            apr=round(_i(s["assists"]) / rd, 3),
            fk=_i(s["opening_kills"]), fd=_i(s["opening_deaths"]),
            t_fk=side_fk.get(sid, {}).get("T", 0),
            t_fd=side_fd.get(sid, {}).get("T", 0),
            ct_fk=side_fk.get(sid, {}).get("CT", 0),
            ct_fd=side_fd.get(sid, {}).get("CT", 0),
            mk2=_i(s["multikill_2k"]), mk3=_i(s["multikill_3k"]), mk4=_i(s["multikill_4k"]),
            tkills=a["T"]["k"], t_deaths=a["T"]["d"],
            t_dmg=split(a["T"]["raw"]),
            ct_kills=a["CT"]["k"], ct_deaths=a["CT"]["d"],
            ct_dmg=split(a["CT"]["raw"]),
            flash_assists=_i(s["flash_assists"]),
            trade_kills=sp["trade"],
            traded_deaths=_i(s["traded_deaths"]),
            clutch_played=_i(s["clutches_played"]),
            clutch_won=_i(s["clutches_won"]),
            clutch_1v1=_i(s["clutch_1v1"]), clutch_1v2=_i(s["clutch_1v2"]),
            clutch_1v3=_i(s["clutch_1v3"]), clutch_1v4=_i(s["clutch_1v4"]),
            clutch_1v5=_i(s["clutch_1v5"]),
            utility_damage=_i(s["utility_damage"]),
            flashes_thrown=_i(s["flashes_thrown"]),
            enemies_flashed=_i(s["enemies_flashed"]),
            flash_duration=round(_f(s["flash_duration_dealt"]), 2),
            penetrated_kills=sp["pen"],
            thrusmoke_kills=sp["smoke"],
            noscope_kills=sp["noscope"],
            fire_count=fire_by.get(sid, 0),
            hit_count=hit_by.get(sid, 0),
            imprecise_shots=imp_by.get(sid, 0),
            stop_shots=stop_by.get(sid, 0),
            gun_fire_count=gunfire_by.get(sid, 0),
            spent=spent_by.get(sid, 0),
            equip_value=round(equip_by.get(sid, 0) / rd) if rd else 0,
            equip_round_start=round(equip_start_by.get(sid, 0) / rd) if rd else 0,
            survive_rounds=max(0, rd - len(death_rounds.get(sid, ()))),
            plants=plant_map.get(sid, 0),
            defuses=defuse_map.get(sid, 0),
            version=VERSION,
        ))
    store2.insert_many(conn, "pms", prows)

    # ---------- 每武器射击统计（命中率不能用全局值代替）
    wstat: dict[tuple, dict] = {}
    try:
        shot_ticks: dict[tuple, set] = {}      # (sid, weapon) -> fire ticks
        for s in shots.iter_rows(named=True):
            sid = int(s["steamid"]) if s["steamid"] else None
            if not sid:
                continue
            w = str(s["weapon"] or "").replace("weapon_", "")
            k = (sid, w)
            e = wstat.setdefault(k, {"fires": 0, "hits": 0, "kills": 0, "imprecise": 0})
            e["fires"] += 1
            # 武器级也用速度判急停，口径与个人级一致
            sp2 = speed_map.get((sid, _i(s["tick"])))
            if sp2 is not None and sp2 > STOP_SPEED_MAX:
                e["imprecise"] += 1
            shot_ticks.setdefault(k, set()).add(int(s["tick"]))
        hurt = set()
        for d in dmg.iter_rows(named=True):
            sid = int(d["attacker_steamid"]) if d["attacker_steamid"] else None
            if sid:
                hurt.add((sid, int(d["tick"])))
        for k, ticks in shot_ticks.items():
            wstat[k]["hits"] = sum(1 for t2 in ticks if (k[0], t2) in hurt)
        for k in kills.iter_rows(named=True):
            sid = int(k["attacker_steamid"]) if k["attacker_steamid"] else None
            if not sid:
                continue
            w = str(k["weapon"] or "").replace("weapon_", "")
            e = wstat.setdefault((sid, w), {"fires": 0, "hits": 0, "kills": 0, "imprecise": 0})
            e["kills"] += 1
    except Exception as e:
        log(f"  [warn] 武器统计失败: {type(e).__name__}: {e}")

    if wstat:
        with conn:
            conn.execute("DELETE FROM weapon_stat WHERE match_id=?", (mid,))
        store2.insert_many(conn, "weapon_stat", [
            dict(match_id=mid, steamid=sid, weapon=w,
                 fires=v["fires"], hits=v["hits"], kills=v["kills"],
                 imprecise=v["imprecise"])
            for (sid, w), v in wstat.items()
        ])

    # ---------- 引擎花费（m_iCashSpentThisRound）：round_end.spend 的主口径
    # 回合末的 m_iCashSpentThisRound 就是该回合真实总花费：天然含护甲、拆弹钳，
    # 且已扣退款，不依赖任何「哪个 tick 算购买结束」的推断。钱包法（cash_start −
    # buy_end 现金）虽然已经把终点挪到 buytime 结束，仍是间接推算（mp_buytime 被
    # 服主改过、或买完又退款都会偏），所以只做兜底。
    engine_spent: dict[tuple, int] = {}
    try:
        from demoparser2 import DemoParser as _DP_SP
        _sp_ends: dict[int, int] = {}
        for _r in rounds.iter_rows(named=True):
            if _r["end_tick"] is None:
                continue
            _sp_ends[int(_r["round_num"])] = int(_r["end_tick"])
        if _sp_ends:
            _sp_t2r = {t: rn for rn, t in _sp_ends.items()}
            _F_SPEND = ("CCSPlayerController.CCSPlayerController_InGameMoneyServices"
                        ".m_iCashSpentThisRound")
            _sptk = _DP_SP(demo_path).parse_ticks(
                [_F_SPEND], ticks=sorted(set(_sp_ends.values())))
            _sptk = _sptk.rename(columns={_F_SPEND: "spent"})
            for row in _sptk.itertuples(index=False):
                rn = _sp_t2r.get(_i(getattr(row, "tick"), -1))
                sid = _i(getattr(row, "steamid", None), 0)
                _raw = getattr(row, "spent", None)
                # 缺值(None/NaN)跳过，交给钱包法兜底；0 是有效值（手枪局没买），要留住
                if rn is None or not sid or _raw is None or _raw != _raw:
                    continue
                # 键序 (round, sid)，与花费构成块的 last_spent 一致
                engine_spent[(rn, sid)] = int(_raw)
    except Exception as e:
        engine_spent = {}
        log(f"  [warn] 引擎花费读取失败（spent 回退钱包法）: {type(e).__name__}: {e}")
    if engine_spent:
        log(f"  引擎花费 {len(engine_spent)} 人次（spent 主口径）")

    def _spend_val(sid: int, rn: int):
        """spent 三级取值：引擎值 → 钱包法 → None。"""
        eng = engine_spent.get((rn, sid))
        if eng is not None:
            return eng
        c0, c1 = cash_start.get((sid, rn)), money_fz.get((sid, rn))
        if c0 is not None and c1 is not None:
            return max(0, c0 - c1)
        return None

    # 回合判定前 1 秒采样：存活状态与携带装备（用于保枪统计）
    # end_tick 那一刻玩家状态已被重置，health 全是 0，不能用来判活。
    rte_rows = []
    pre = []          # 下面 try 可能抛异常，这里先兜底避免 NameError
    try:
        pre = [(int(r["round_num"]), int(r["end_tick"]) - 64)
               for r in rounds.iter_rows(named=True)
               if r["end_tick"] is not None and int(r["end_tick"]) > 128]
        tick2round = {t: rn for rn, t in pre}
        for _t in tick2round:
            for s in _snap_at.get(_t, []):
                sid = int(s["steamid"]) if s["steamid"] else None
                if not sid:
                    continue
                rn = tick2round.get(int(s["tick"]))
                if rn is None:
                    continue
                rte_rows.append(dict(
                    match_id=mid, round=rn, steamid=sid,
                    alive=1 if _i(s["health"]) > 0 else 0,
                    equip=_i(s["equipment_value"]),
                    equip_start=equip_start.get((sid, rn)),
                    equip_fz=equip_fz.get((sid, rn)),
                    cash_start=cash_start.get((sid, rn)),
                    cash_fz=money_fz.get((sid, rn)),   # buytime 结束（t_start+20s）时的现金
                    spend=_spend_val(sid, rn),
                ))
    except Exception as e:
        log(f"  [warn] 回合末采样失败: {type(e).__name__}: {e}")
    # awpy 的 snapshots 只返回「那一刻还活着」的玩家，死掉的人根本不在结果里。
    # 不补的话，round_end 只覆盖活到最后的回合（我 99 回合只进去 26 条），
    # 保枪/存活类统计的分母就废了。这里按「该场全部玩家 × 全部回合」补齐，
    # 快照里没有的一律视为该回合已死（alive=0, equip=0）。
    if pre:
        try:
            roster = [int(r["steamid"]) for r in conn.execute(
                "SELECT DISTINCT steamid FROM players WHERE match_id=?", (mid,)).fetchall()
                if r["steamid"]]
            have = {(int(x["steamid"]), int(x["round"])) for x in rte_rows}
            for rn, _t in pre:
                for sid in roster:
                    if (sid, rn) not in have:
                        rte_rows.append(dict(match_id=mid, round=rn, steamid=sid,
                                             alive=0, equip=0,
                                             equip_start=equip_start.get((sid, rn)),
                                             equip_fz=equip_fz.get((sid, rn)),
                                             cash_start=cash_start.get((sid, rn)),
                                             cash_fz=money_fz.get((sid, rn)),
                                             spend=_spend_val(sid, rn)))
        except Exception as e:
            log(f"  [warn] 回合末补齐失败: {type(e).__name__}: {e}")
    if rte_rows:
        with conn:
            conn.execute("DELETE FROM round_end WHERE match_id=?", (mid,))
        store2.insert_many(conn, "round_end", rte_rows)

    # ---------- economy / blinds / purchases（三张细表）
    with conn:
        for tb in ("economy", "blinds", "purchases"):
            conn.execute(f"DELETE FROM {tb} WHERE match_id=?", (mid,))

    def _buy_type(team_eq: int, rn: int) -> str:
        """按队伍 5 人装备合计分档；第 1、13 回合算手枪局。"""
        if rn in (1, 13):
            return "pistol"
        if team_eq >= 20000:
            return "full"
        if team_eq >= 12500:
            return "half"
        if team_eq >= 7000:
            return "force"
        return "eco"

    # 每回合每阵营的装备/余额合计
    team_eq: dict[tuple, int] = {}
    team_money: dict[tuple, int] = {}
    for (sid2, rn), v in equip_fz.items():
        fs = pside.get(sid2) or "T"
        sd = side_of(fs, rn)
        team_eq[(sd, rn)] = team_eq.get((sd, rn), 0) + v
    for (sid2, rn), v in money_fz.items():
        fs = pside.get(sid2) or "T"
        sd = side_of(fs, rn)
        team_money[(sd, rn)] = team_money.get((sd, rn), 0) + v
    start_eq_team: dict[tuple, int] = {}
    for (sid2, rn), v in equip_start.items():
        fs = pside.get(sid2) or "T"
        sd = side_of(fs, rn)
        start_eq_team[(sd, rn)] = start_eq_team.get((sd, rn), 0) + v
    # 回合开始现金合计：pre_bal 的真实口径（钱包法的起点）
    cash_start_team: dict[tuple, int] = {}
    for (sid2, rn), v in cash_start.items():
        fs = pside.get(sid2) or "T"
        sd = side_of(fs, rn)
        cash_start_team[(sd, rn)] = cash_start_team.get((sd, rn), 0) + v
    # 回合判定前 1 秒的现金合计：end_bal 的真实口径
    team_money_end: dict[tuple, int] = {}
    for (sid2, rn), v in money_end.items():
        fs = pside.get(sid2) or "T"
        sd = side_of(fs, rn)
        team_money_end[(sd, rn)] = team_money_end.get((sd, rn), 0) + v

    erows = []
    for (sd, rn) in sorted(team_eq, key=lambda x: (x[1], x[0])):
        eq = team_eq[(sd, rn)]
        erows.append(dict(
            match_id=mid, round=rn, side=sd,
            pre_bal=cash_start_team.get((sd, rn), 0), post_bal=team_money.get((sd, rn), 0),
            end_bal=team_money_end.get((sd, rn), 0),
            start_eq=start_eq_team.get((sd, rn), 0), end_eq=eq,
            buy_type=_buy_type(eq, rn),
        ))
    if erows:
        store2.insert_many(conn, "economy", erows)

    # 闪光：每次致盲一条
    brows = []
    try:
        for b in dem.blinds.iter_rows(named=True):
            at = b.get("attacker_steamid")
            vi = b.get("victim_steamid")
            if not at or not vi:
                continue
            brows.append(dict(
                match_id=mid, round=tick_round(b["tick"]) or 0, tick=int(b["tick"]),
                attacker_steamid=int(at), victim_steamid=int(vi),
                attacker_side=side_of(pside.get(int(at)) or "T", tick_round(b["tick"]) or 1),
                victim_side=side_of(pside.get(int(vi)) or "T", tick_round(b["tick"]) or 1),
                duration=round(_f(b.get("blind_duration") or b.get("duration") or 0), 2),
            ))
    except Exception as e:
        log(f"  [warn] blinds 失败: {type(e).__name__}: {e}")
    if brows:
        store2.insert_many(conn, "blinds", brows)

    # 购买/捡起/丢下/退款：item_events（列名是 item，不是 item_name）
    urows = []
    try:
        # 退款类事件也要留：钱包法下花费靠余额差，但退款事件是解释
        # 「这回合为什么花得少」的证据，丢了就查不出账。
        _KEEP = ("purchase", "pickup", "drop", "sell", "refund", "item_sell", "return")
        for it in dem.item_events.iter_rows(named=True):
            act = str(it.get("action") or "")
            if act.lower() not in _KEEP or not it["steamid"]:
                continue
            rn = tick_round(it["tick"]) or 0
            urows.append(dict(
                match_id=mid, round=rn, tick=int(it["tick"]),
                steamid=int(it["steamid"]), name=str(it.get("name") or ""),
                side=side_of(pside.get(int(it["steamid"])) or "T", rn or 1),
                action=act, item=str(it.get("item") or ""),
                cost=_i(it.get("cost")),
                orig_owner=it.get("original_owner_steamid"),
                near_zone=1 if it.get("near_buy_zone") else 0,
            ))
    except Exception as e:
        log(f"  [warn] purchases 失败: {type(e).__name__}: {e}")
    if urows:
        store2.insert_many(conn, "purchases", urows)

    # 投掷事件已改由 grenade_use 承载（demoparser2 引爆事件的 user_steamid，能归属到人）。
    # 老表 grenade_throw 依赖 awpy 的 grenades.thrower_steamid，而它全是 None，
    # 只能记「全队按类型计数」，无法归属到个人 —— 停写，不再产生这份误导性数据。
    # 表本身保留（老库兼容），但没有新行写入。

    # ---------- 投掷归属（按人）：demoparser2 的引爆事件带 user_steamid
    # awpy 的 grenades.thrower_steamid 全空，但 demoparser2 的 *_detonate 事件
    # 给出真正投掷者。注意这是「投出去了」的数，买了死在手里的不算，
    # 所以 投出 <= 购买 是正常的（实测全场投出率 55%）。
    try:
        from demoparser2 import DemoParser as _DP2
        _dp = _DP2(demo_path)
        EV2 = {"smoke": "smokegrenade_detonate", "flash": "flashbang_detonate",
               "he": "hegrenade_detonate", "decoy": "decoy_started",
               "fire": "inferno_startburn"}
        ucnt: dict[tuple, int] = {}
        # 一次解析全部事件：parse_event 一次只能一个，5 个事件要 12 秒（每次重读 demo），
        # parse_events 一趟 2 秒。返回 [(事件名, DataFrame), ...]。
        try:
            _all = dict(_dp.parse_events(list(EV2.values())))
        except Exception as _e:
            log(f"  [warn] parse_events 批量失败（{type(_e).__name__}），回落逐个解析")
            _all = {}
            for _v in EV2.values():
                try:
                    _all[_v] = _dp.parse_event(_v)
                except Exception:
                    pass
        for kind, evn in EV2.items():
            try:
                _df = _all.get(evn)
                if _df is None or "user_steamid" not in _df.columns:
                    continue
                _df["user_steamid"] = _df["user_steamid"].astype("int64")
                for _sid, _n in _df["user_steamid"].value_counts().items():
                    ucnt[(int(_sid), kind)] = ucnt.get((int(_sid), kind), 0) + int(_n)
            except Exception as _e2:
                log(f"  [warn] {evn} 取投掷者失败: {_e2}")
        if ucnt:
            with conn:
                conn.execute("DELETE FROM grenade_use WHERE match_id=?", (mid,))
            store2.insert_many(conn, "grenade_use", [
                dict(match_id=mid, steamid=s, type=k, n=v)
                for (s, k), v in ucnt.items()
            ])
    except Exception as e:
        log(f"  [warn] 投掷归属失败（demoparser2）: {type(e).__name__}: {e}")

    # ---------- 花费构成（按阵营）
    # 武器/道具：purchases 的精确 cost
    # 甲 + 钳子：purchases 里没有，用 m_iCashSpentThisRound 与 purchases 的差值反推
    #            钳子按 m_bPawnHasDefuser 由 False→True 的回合 × $400 计入
    CAT_ITEMS = {
        "rifle": ["ak47", "m4a1", "m4a1_silencer", "galilar", "famas", "aug", "sg556"],
        "sniper": ["awp", "ssg08", "scar20", "g3sg1"],
        "smg": ["bizon", "mp7", "mp9", "mac10", "p90", "ump45", "mp5sd"],
        "shotgun": ["nova", "xm1014", "mag7", "sawedoff", "negev", "m249"],
        "pistol": ["glock", "hkp2000", "usp_silencer", "p250", "deagle", "tec9",
                   "fiveseven", "cz75a", "revolver", "elite", "taser"],
        "util": ["hegrenade", "flashbang", "smokegrenade", "molotov", "incendiary",
                 "incgrenade", "decoy"],
    }
    ITEM2CAT = {it: cat for cat, items in CAT_ITEMS.items() for it in items}
    try:
        spend_by_cat: dict[tuple, int] = {}
        pur_by_round: dict[tuple, int] = {}
        # (a) 净购买额：只给甲残差用。买了又退的枪按净额算，
        #     否则毛额 − 引擎净花费 会系统性把甲压小甚至压成负数。
        for r in conn.execute(
                "SELECT round, steamid, "
                "SUM(CASE WHEN action='purchase' THEN cost ELSE -cost END) c "
                "FROM purchases WHERE match_id=? "
                "AND action IN ('purchase','sell','refund','item_sell','return') "
                "GROUP BY round, steamid",
                (mid,)):
            pur_by_round[(int(r["round"]), int(r["steamid"]))] = (r["c"] or 0)
        # (b) 分类构成：保持毛额，只吃 purchase。退款事件的 item 名不一定
        #     能和对上的购买行配对，硬减会把分类弄脏。
        for r in conn.execute(
                "SELECT round, steamid, item, SUM(cost) c FROM purchases "
                "WHERE match_id=? AND action='purchase' GROUP BY round, steamid, item",
                (mid,)):
            sid = int(r["steamid"])
            sd = side_of(pside.get(sid), int(r["round"]))
            cat = ITEM2CAT.get(str(r["item"] or "").lower(), "misc")
            spend_by_cat[(sd, cat)] = spend_by_cat.get((sd, cat), 0) + (r["c"] or 0)

        # 回合末快照：本回合现金支出 + 是否有钳子
        from demoparser2 import DemoParser as _DP3
        _dp3 = _DP3(demo_path)
        _F_SPENT = ("CCSPlayerController.CCSPlayerController_InGameMoneyServices"
                    ".m_iCashSpentThisRound")
        _F_KIT = "CCSPlayerController.m_bPawnHasDefuser"
        _ends = [int(b[1]) for b in bounds]
        _tk = _dp3.parse_ticks([_F_SPENT, _F_KIT], ticks=_ends)
        _tk = _tk.rename(columns={_F_SPENT: "spent", _F_KIT: "kit"})
        _tk["spent"] = _tk["spent"].fillna(0).astype("int64")
        _tk["kit"] = _tk["kit"].fillna(False).astype(bool)
        _tk = _tk.sort_values("tick")

        # 该回合的回合号：按结束 tick 对齐
        _tick2round = {int(b[1]): i + 1 for i, b in enumerate(bounds)}

        # 每人有钳子的回合数（相邻快照 False→True 记一次购买）
        kit_buys: dict[str, int] = {}
        prev: dict[int, bool] = {}
        for row in _tk.itertuples(index=False):
            sid = int(row.steamid)
            rn = _tick2round.get(int(row.tick))
            if rn is None:
                continue
            was = prev.get(sid, False)
            if row.kit and not was:
                sd = side_of(pside.get(sid), rn)
                if sd:
                    kit_buys[sd] = kit_buys.get(sd, 0) + 1
            prev[sid] = bool(row.kit)

        # 每人每回合末值：spent 是回合内累加，末值即总花费
        last_spent: dict[tuple, int] = {}
        for row in _tk.itertuples(index=False):
            sid = int(row.steamid)
            rn = _tick2round.get(int(row.tick))
            if rn is None:
                continue
            last_spent[(rn, sid)] = int(row.spent)

        # 甲 = 实际支出 − 已知购买（净额） − 钳子
        armor_by_side: dict[str, int] = {}
        neg_n = 0          # 残差为负的人次（净购买 > 引擎花费，疑似退款未配对）
        neg_sum = 0        # 残差为负的总额（负值）
        for (rn, sid), sp in last_spent.items():
            sd = side_of(pside.get(sid), rn)
            if sd is None:
                continue
            diff = sp - pur_by_round.get((rn, sid), 0)
            if diff > 0:
                armor_by_side[sd] = armor_by_side.get(sd, 0) + diff
            elif diff < 0:
                neg_n += 1
                neg_sum += diff

        for sd, n in kit_buys.items():
            spend_by_cat[(sd, "kit")] = n * 400
            # 钳子的钱已经算在 diff 里，扣掉避免重复
            armor_by_side[sd] = armor_by_side.get(sd, 0) - n * 400

        for sd in ("CT", "T"):
            if armor_by_side.get(sd, 0) > 0:
                spend_by_cat[(sd, "armor")] = armor_by_side[sd]

        if neg_n:
            log(f"  [口径告警] 甲残差为负 {neg_n} 人次 / 共 {abs(neg_sum)} 元"
                f"（净购买大于引擎花费，可能退款未配对）")

        # 钱包法（start_cash − freeze_end_cash）与引擎 m_iCashSpentThisRound 对账。
        # 注意 spent_map 的键是 (steamid, round)，last_spent 是 (round, steamid)。
        # 只告警，不改数据。
        mism_n = 0
        mism_max = 0
        for (rn, sid), sp in last_spent.items():
            wallet = spent_map.get((sid, rn))
            if wallet is None:
                continue
            d = abs(int(wallet) - int(sp))
            if d > mism_max:
                mism_max = d
            if d > 50:
                mism_n += 1
        if mism_n:
            log(f"  [口径告警] 钱包法与引擎花费不一致 {mism_n} 人次，"
                f"最大偏差 {mism_max} 元")

        srows = [dict(match_id=mid, side=sd, cat=c, cost=v)
                 for (sd, c), v in spend_by_cat.items() if v > 0]
        if srows:
            with conn:
                conn.execute("DELETE FROM spend_cat WHERE match_id=?", (mid,))
            store2.insert_many(conn, "spend_cat", srows)
    except Exception as e:
        log(f"  [warn] 花费构成失败: {type(e).__name__}: {e}")

    # ---------- Rating 2.0 / Impact（HLTV 公开公式）
    with conn:
        for r in conn.execute("""SELECT steamid, kpr, dpr, apr, kast, adr
                                 FROM pms WHERE match_id=?""", (mid,)).fetchall():
            kpr, dpr, apr = r["kpr"] or 0, r["dpr"] or 0, r["apr"] or 0
            kast, adr = r["kast"] or 0, r["adr"] or 0
            impact = 2.13 * kpr + 0.42 * apr - 0.41
            rating = (0.0073 * kast + 0.3591 * kpr - 0.5329 * dpr
                      + 0.2372 * impact + 0.0032 * adr + 0.1587)
            conn.execute("UPDATE pms SET impact=?, rating=? WHERE match_id=? AND steamid=?",
                         (round(impact, 3), round(rating, 3), mid, r["steamid"]))

    log(f"  match {mid}: {len(bounds)} 回合 / {len(krows)} 击杀 / {len(drows)} 条伤害事件 / {len(prows)} 人")
    return mid
