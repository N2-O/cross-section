"""按 match_id 生成回放数据（供 /api/replay 用），带磁盘缓存。

    build(conn, match_id, demo_path, overviews_dir) -> dict
"""
from __future__ import annotations

import os
import re


def read_overview(overviews_dir: str, map_name: str) -> dict:
    p = os.path.join(overviews_dir, map_name + ".txt")
    if not os.path.exists(p):
        raise FileNotFoundError(
            f"缺少地图 {map_name} 的雷达参数（{map_name}.txt）\n"
            f"当前查找目录：{overviews_dir}\n"
            f"修复：把 CS2 安装目录下\n"
            f"    game\\csgo\\resource\\overviews\\{map_name}.txt\n"
            f"复制进上面这个目录即可，或在「设置」里填写 CS2 安装目录。"
        )
    txt = open(p, encoding="utf-8", errors="replace").read()
    kv = {m.group(1): m.group(2) for m in re.finditer(r'"([A-Za-z_]+)"\s+"([^"]*)"', txt)}
    kv["__layers"] = read_layers(txt)
    return kv


#: 回放数据结构版本。samples 增删字段就 +1，server 端比对后自动重建旧缓存。
REPLAY_V = 4


def _row_z(row, zcol):
    """取一行的世界 Z；列不在、值是 NaN 或取不到时返回 None（分层功能降级，不影响出图）。"""
    if not zcol:
        return None
    v = getattr(row, zcol, None)
    try:
        if v is None or v != v:
            return None
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def read_layers(txt: str) -> list:
    """从 overview 的 verticalsections 段读出分层高度。

    只有多层图（Nuke / Vertigo / Train / Baggage）才有这一段，单层图返回 []。
    每层给一个 z 区间，前端按玩家 Z 落在哪一层决定用哪张底图（上层 <map>.png、
    下层 <map>_lower.png），跟游戏内小地图切层的规则一致。
    """
    i = txt.find('"verticalsections"')
    if i < 0:
        return []
    j = txt.find("{", i)
    if j < 0:
        return []
    depth, k = 0, j
    while k < len(txt):
        ch = txt[k]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    layers, cur = [], None
    for line in txt[j + 1:k].splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        m = re.match(r'"([A-Za-z0-9_]+)"', s)
        if m and not m.group(1).startswith("Altitude"):
            cur = {"name": m.group(1), "zmin": None, "zmax": None}
            layers.append(cur)
            continue
        m = re.search(r'"Altitude(Min|Max)"\s+"([-\d.]+)"', s)
        if m and cur is not None:
            cur["zmin" if m.group(1) == "Min" else "zmax"] = float(m.group(2))
    return [x for x in layers if x["zmin"] is not None and x["zmax"] is not None]


def toid(v):
    try:
        return int(v)
    except Exception:
        return -1


SHORT = {"usp_silencer": "USP-S", "m4a1_silencer": "M4A1-S", "hkp2000": "P2000",
         "glock": "Glock-18", "ak47": "AK-47", "deagle": "Desert Eagle", "awp": "AWP",
         "m4a1": "M4A4", "tec9": "Tec-9", "revolver": "R8 Revolver",
         "fiveseven": "Five-SeveN", "cz75a": "CZ75-Auto", "sg556": "SG 553",
         "galilar": "Galil AR", "mac10": "MAC-10", "ump45": "UMP-45",
         "mp7": "MP7", "mp5sd": "MP5-SD", "ssg08": "SSG 08", "scar20": "SCAR-20",
         "nova": "Nova", "xm1014": "XM1014", "mag7": "MAG-7", "sawedoff": "Sawed-Off",
         "m249": "M249", "negev": "Negev", "elite": "Dual Berettas",
         "bizon": "PP-Bizon", "famas": "FAMAS", "p250": "P250", "p90": "P90",
         "mp9": "MP9", "aug": "AUG", "g3sg1": "G3SG1", "knife": "刀", "knife_t": "刀",
         "hegrenade": "手雷", "flashbang": "闪光", "smokegrenade": "烟雾",
         "molotov": "燃烧瓶", "incgrenade": "燃烧弹", "decoy": "诱饵"}


def short_weapon(w: str) -> str:
    w = str(w).replace("weapon_", "")
    return SHORT.get(w, w)


#: parse_ticks 只返回「明确请求」的列。不把 Z 写进 props，DataFrame 里压根没这列，
#: 后面 row.Z 必然 AttributeError（6.3.0 就这么翻的车，所有地图回放全打不开）。
TICK_PROPS = ["X", "Y", "health", "armor", "has_helmet", "is_alive", "team_num",
              "yaw", "pitch", "inventory", "balance", "flash_duration", "has_defuser"]


def parse_ticks_with_z(dp, all_ticks):
    """取 tick 数据，尽量带上 Z；拿不到就降级（返回 zcol=None，回放照出、只是不分层）。"""
    try:
        ticks = dp.parse_ticks(TICK_PROPS + ["Z"], ticks=all_ticks)
    except Exception:
        ticks = dp.parse_ticks(TICK_PROPS, ticks=all_ticks)
        return ticks, None
    return ticks, ("Z" if "Z" in getattr(ticks, "columns", []) else None)


def build(conn, match_id: int, demo_path: str, overviews_dir: str, step: int = 16) -> dict:
    m = conn.execute("SELECT map FROM matches WHERE id=?", (match_id,)).fetchone()
    if not m:
        raise RuntimeError("match 不存在")
    map_name = m["map"]
    kv = read_overview(overviews_dir, map_name)
    layers = kv.pop("__layers", [])          # 多层图的 z 分层区间，单层图为 []
    pos_x, pos_y, scale = float(kv["pos_x"]), float(kv["pos_y"]), float(kv["scale"])

    half = 12
    rounds_db = [dict(r) for r in conn.execute(
        "SELECT round, t_start, t_freeze, t_end, winner, reason, a_side FROM rounds "
        "WHERE match_id=? ORDER BY round", (match_id,))]
    players_db = {r["steamid"]: dict(r) for r in conn.execute(
        "SELECT steamid, name, first_side, is_me, left_round FROM players WHERE match_id=?",
        (match_id,))}
    n_r = len(rounds_db)
    half = 12 if n_r > 12 else n_r

    def side_at(sid, rd):
        """CS2 阵营：常规 12 回合半场；加时每 3 回合换边，起点延续第二半场。"""
        fs = players_db.get(sid, {}).get("first_side") or "T"
        opp = "CT" if fs == "T" else "T"
        if rd <= half:
            return fs
        if half == 12:
            if rd <= 24:
                return opp
            ot = (rd - 25) // 3
            return opp if ot % 2 == 0 else fs
        return opp

    my_steamid = None
    for sid, p in players_db.items():
        if p["is_me"]:
            my_steamid = sid
            break
    # 兜底：players 里没标 is_me 时，用这场记录的 my_steamid
    if my_steamid is None:
        _m = conn.execute("SELECT my_steamid FROM matches WHERE id=?", (match_id,)).fetchone()
        if _m and _m["my_steamid"]:
            try:
                my_steamid = int(_m["my_steamid"])
            except (TypeError, ValueError):
                my_steamid = None
    my_first_side = players_db.get(my_steamid, {}).get("first_side") if my_steamid else None

    from demoparser2 import DemoParser
    dp = DemoParser(demo_path)

    # 每回合采集到「下一回合 freeze 前」：回合结束后还有约 7 秒可以移动、对枪，
    # 只采到 t_end 的话那段时间是空白的，人像被冻在最后一帧
    span = []
    for i, r in enumerate(rounds_db):
        s0 = int(r["t_start"])
        # 回合结束后约 7 秒仍可移动/对枪；再长就截进下一回合的准备阶段了
        # 从 7 秒砍到 6.5：尾巴上那半秒已经能看到下回合的预备动作
        hard = int(r["t_end"]) + int(6.5 * 64)
        if i + 1 < len(rounds_db):
            s1 = min(hard, int(rounds_db[i + 1]["t_freeze"]) - 1)
        else:
            s1 = hard
        span.append((s0, s1))
    all_ticks = []
    for s0, s1 in span:
        all_ticks.extend(range(s0, s1 + 1, step))
    ticks, _zcol = parse_ticks_with_z(dp, all_ticks)
    ticks = ticks[ticks.X.abs() > 1]
    # 当前手持武器（inventory 只是背包，顺序不固定，不能当手持用）
    try:
        aw = dp.parse_ticks(["active_weapon_name"], ticks=all_ticks)
        aw = aw[["tick", "steamid", "active_weapon_name"]]
        ticks = ticks.merge(aw, on=["tick", "steamid"], how="left")
    except Exception:
        ticks["active_weapon_name"] = ""

    fires = dp.parse_event("weapon_fire")
    fires["user_steamid"] = [toid(v) for v in fires["user_steamid"]]

    ev = {}
    for name in ["smokegrenade_detonate", "smokegrenade_expired", "inferno_startburn",
                 "inferno_expire", "hegrenade_detonate", "flashbang_detonate", "decoy_started"]:
        try:
            d = dp.parse_event(name)
            d["user_steamid"] = [toid(v) for v in d["user_steamid"]]
            ev[name] = d
        except Exception:
            ev[name] = None

    bomb_ev = {}
    for name in ["bomb_planted", "bomb_defused", "bomb_exploded", "bomb_dropped", "bomb_pickup"]:
        try:
            d = dp.parse_event(name)
            if "user_steamid" in d.columns:
                d["user_steamid"] = [toid(v) for v in d["user_steamid"]]
            bomb_ev[name] = d
        except Exception:
            bomb_ev[name] = None

    # 击杀附加标记：盲狙/混烟/穿墙/跳跃/被闪/复仇/支配
    kill_flags = {}
    try:
        pd = dp.parse_event("player_death")
        pd["user_steamid"] = [toid(v) for v in pd["user_steamid"]]
        def _b(v):
            return 1 if (v is True or v == 1) else 0
        for x in pd.itertuples():
            f = (_b(getattr(x, "noscope", 0)) << 0) | (_b(getattr(x, "thrusmoke", 0)) << 1) | \
                (_b(getattr(x, "penetrated", 0)) << 2) | (_b(getattr(x, "attackerinair", 0)) << 3) | \
                (_b(getattr(x, "attackerblind", 0)) << 4) | (_b(getattr(x, "revenge", 0)) << 5) | \
                (_b(getattr(x, "dominated", 0)) << 6)
            if f:
                kill_flags[(x.user_steamid, int(x.tick))] = f
    except Exception:
        pass

    # 伤害口径：valid 列在解析时已按受害者剩余血量截断、并排除死后补枪（不含甲伤，与游戏内 HUD 一致），
    # 这里直接按 (round, attacker) 聚合；原始 dmg_health 仅留作日志对照。
    dmg_by_round = {}
    dmg_raw_by_round = {}  # 旧口径（原始 dmg_health），仅供日志对照，不写入回放数据
    for dd in conn.execute(
            "SELECT round, attacker_steamid a, "
            "       COALESCE(SUM(valid),0) v, COALESCE(SUM(dmg_health),0) raw "
            "FROM damage WHERE match_id=? GROUP BY round, attacker_steamid",
            (match_id,)):
        rnd = int(dd["round"])
        a = dd["a"]
        nm = players_db.get(a, {}).get("name") if (a and a > 0) else None
        if not nm:
            continue
        dmg_raw_by_round.setdefault(rnd, {})
        dmg_raw_by_round[rnd][nm] = dmg_raw_by_round[rnd].get(nm, 0) + (dd["raw"] or 0)
        v = dd["v"] or 0
        if v > 0:
            dmg_by_round.setdefault(rnd, {})
            dmg_by_round[rnd][nm] = dmg_by_round[rnd].get(nm, 0) + v

    _raw_total = sum(sum(x.values()) for x in dmg_raw_by_round.values())
    _eff_total = sum(sum(x.values()) for x in dmg_by_round.values())
    if _raw_total:
        print(f"  伤害口径：原始 {_raw_total} → 有效 {_eff_total}"
              f"（差 {(_eff_total - _raw_total) / _raw_total * 100:+.1f}%）")

    kills_db = {}
    for k in conn.execute("SELECT round, tick, attacker_steamid a, victim_steamid v, assister_steamid s, "
                          "weapon, headshot FROM kills WHERE match_id=? ORDER BY tick", (match_id,)):
        kills_db.setdefault(k["round"], []).append(dict(k))

    def px(x):
        return round((x - pos_x) / scale, 1)

    def py(y):
        return round((pos_y - y) / scale, 1)

    # 每回合双方经济（按 side 分行）
    econ_map = {}
    for e in conn.execute(
            "SELECT round, side, pre_bal, post_bal, start_eq, end_eq "
            "FROM economy WHERE match_id=?", (match_id,)):
        econ_map[(int(e["round"]), str(e["side"]))] = {
            "pre": e["pre_bal"], "post": e["post_bal"],
            "se": e["start_eq"], "eq": e["end_eq"]}

    out_rounds = []
    for i_r, r in enumerate(rounds_db):
        rd, fzt = int(r["round"]), int(r["t_freeze"])
        t0, t1 = span[i_r]
        sub = ticks[(ticks.tick >= t0) & (ticks.tick <= t1)]
        by_pid = {toid(s): g.sort_values("tick") for s, g in sub.groupby(sub.steamid)}

        plist = []
        for sid, p in sorted(players_db.items(), key=lambda kv2: kv2[1]["name"]):
            g = by_pid.get(sid)
            if g is None or g.empty:
                continue
            samples = []
            for row in g.itertuples():
                inv = row.inventory if isinstance(row.inventory, (list, tuple)) else []
                raw_act = getattr(row, "active_weapon_name", "")
                act = "" if (raw_act is None or raw_act != raw_act) else str(raw_act)
                # 显示真实手持（切刀赶路、切雷都是真实状态）
                main = act if act else (str(inv[0]) if inv else "")
                main = main.replace("weapon_", "")
                samples.append([round((row.tick - t0) / 64.0, 2), px(row.X), py(row.Y),
                                round(float(row.yaw), 1), int(row.health), int(row.armor),
                                int(bool(row.has_helmet)), int(row.balance),
                                round(float(row.flash_duration), 2),
                                main or (inv[0] if inv else ""), int(bool(row.is_alive)),
                                int(bool(row.has_defuser)),
                                # [12] 世界坐标 Z：多层图（Nuke/Vertigo/Train/Baggage）靠它
                                # 判断这个人在楼上还是楼下，前端据此切 <map>_lower.png
                                _row_z(row, _zcol)])
            same_team = (p["first_side"] == my_first_side) if my_first_side else (sid == my_steamid)
            _nm = (p["name"] or "").strip()
            plist.append({"name": _nm or f"玩家{sid % 10000:04d}", "sid": sid,
                          "side": side_at(sid, rd), "left": p.get("left_round") or 0,
                          "mine": bool(same_team), "isMe": sid == my_steamid, "s": samples})

        shots = []
        fd = fires[(fires.tick >= t0) & (fires.tick <= t1)]
        for x in fd.itertuples():
            if "knife" in str(x.weapon):
                continue
            g = by_pid.get(x.user_steamid)
            if g is None or g.empty:
                continue
            i2 = int(g.tick.searchsorted(x.tick, side="right")) - 1
            if i2 < 0:
                i2 = 0
            row2 = g.iloc[i2]
            if abs(int(row2.tick) - int(x.tick)) > 128:
                continue
            shots.append([round((x.tick - t0) / 64.0, 2), px(row2.X), py(row2.Y),
                          round(float(row2.yaw), 1), short_weapon(x.weapon)])

        grenades = []
        for kind, sev, eev in [("smoke", "smokegrenade_detonate", "smokegrenade_expired"),
                               ("molotov", "inferno_startburn", "inferno_expire"),
                               ("he", "hegrenade_detonate", None),
                               ("flash", "flashbang_detonate", None),
                               ("decoy", "decoy_started", None)]:
            sd = ev.get(sev)
            if sd is None:
                continue
            sd = sd[(sd.tick >= t0) & (sd.tick <= t1)]
            ed = ev.get(eev)
            ed = ed[(ed.tick >= t0) & (ed.tick <= t1)] if ed is not None else None
            for x in sd.itertuples():
                ts = round((x.tick - t0) / 64.0, 2)
                te = ts + {"smoke": 18.0, "molotov": 7.0, "he": 0.5, "flash": 0.3, "decoy": 15.0}[kind]
                if ed is not None:
                    cand = ed[(ed.entityid == x.entityid) & (ed.tick > x.tick)]
                    if len(cand):
                        te = round((int(cand.tick.iloc[0]) - t0) / 64.0, 2)
                sid_g = toid(x.user_steamid)
                name = players_db.get(sid_g, {}).get("name", "")
                gside = side_at(sid_g, rd)
                # 落点世界 Z：多层图靠它把道具画在楼下/楼上（事件表给不出就置 None，
                # 前端会退回用投掷者当时所在层）
                gz = getattr(x, "z", None)
                gz = None if gz is None or gz != gz else round(float(gz), 1)
                grenades.append([kind, name, ts, te, px(x.x), py(x.y), gside, gz])

        # 道具使用统计：投出数 / 生效时长 / 伤害（HE、火分开）/ 被闪时长
        util = {}
        def _u(nm):
            return util.setdefault(nm, {"smoke": 0, "molotov": 0, "flash": 0, "he": 0,
                                        "decoy": 0, "sec": 0.0, "dmg": 0,
                                        "he_dmg": 0, "fire_dmg": 0, "flash_sec": 0.0})
        for kind, nm, ts_, te_, gx, gy, gside, gz in grenades:
            if not nm:
                continue
            u = _u(nm)
            u[kind] = u.get(kind, 0) + 1
            if kind in ("smoke", "molotov", "decoy"):
                u["sec"] = round(u.get("sec", 0) + max(0.0, te_ - ts_), 1)
        for dd in conn.execute("SELECT attacker_steamid a, weapon, valid d FROM damage "
                               "WHERE match_id=? AND round=?", (match_id, rd)):
            w = str(dd["weapon"]).replace("weapon_", "")
            if w in ("hegrenade", "inferno", "molotov", "incgrenade"):
                nm = players_db.get(dd["a"], {}).get("name", "")
                if nm:
                    u = _u(nm)
                    u["dmg"] = u.get("dmg", 0) + (dd["d"] or 0)
                    if w == "hegrenade":
                        u["he_dmg"] += (dd["d"] or 0)
                    else:
                        u["fire_dmg"] += (dd["d"] or 0)
        # 被闪时长：flash_duration 不衰减（保持到下次被闪），按上升沿累加每次致盲时长
        for sid, g in by_pid.items():
            nm = players_db.get(sid, {}).get("name", "")
            if not nm:
                continue
            vals = [float(x) if x == x else 0.0 for x in g["flash_duration"]]
            tot = 0.0
            prev = 0.0
            for v in vals:
                if v > prev + 0.4:      # 新的一次闪光
                    tot += v
                prev = v
            if tot > 0:
                _u(nm)["flash_sec"] = round(tot, 1)

        kills = [[round((k["tick"] - t0) / 64.0, 2),
                  players_db.get(k["a"], {}).get("name") or ("" if not k["a"] or k["a"] < 0 else ""),
                  players_db.get(k["v"], {}).get("name", ""),
                  short_weapon(k["weapon"]), int(bool(k["headshot"])),
                  players_db.get(k["s"], {}).get("name", "") if k["s"] and k["s"] > 0 else "",
                  kill_flags.get((k["v"], int(k["tick"])), 0)]
                 for k in kills_db.get(rd, [])]

        # C4：拾取/掉落/下包/拆包/爆炸 时间线
        bombs = []
        carry = None
        for nm, typ in (("bomb_pickup", "pickup"), ("bomb_dropped", "drop"),
                        ("bomb_planted", "plant"), ("bomb_defused", "defuse"),
                        ("bomb_exploded", "explode")):
            dd = bomb_ev.get(nm)
            if dd is None or "tick" not in dd.columns:
                continue
            sub_b = dd[(dd.tick >= t0) & (dd.tick <= t1)]
            for x in sub_b.itertuples():
                ts = round((x.tick - t0) / 64.0, 2)
                who = players_db.get(toid(getattr(x, "user_steamid", -1)), {}).get("name", "")
                rec = {"t": ts, "type": typ, "who": who}
                # 下包/掉落都记下当时的坐标与 Z，拆包点、掉落点才能在多层图上落到正确楼层
                if typ in ("plant", "drop"):
                    g2 = by_pid.get(toid(getattr(x, "user_steamid", -1)))
                    if g2 is not None and not g2.empty:
                        i3 = int(g2.tick.searchsorted(x.tick, side="right")) - 1
                        if i3 < 0:
                            i3 = 0
                        rec["x"] = px(g2.iloc[i3].X)
                        rec["y"] = py(g2.iloc[i3].Y)
                        rec["z"] = _row_z(g2.iloc[i3], _zcol)
                if typ == "plant":
                    site = int(getattr(x, "site", 0))
                    rec["site"] = "A" if site == 210 else ("B" if site == 209 else str(site))
                    rec["carrier"] = carry
                if typ == "pickup":
                    carry = who
                if typ in ("drop", "plant"):
                    carry = None
                bombs.append(rec)
        bombs.sort(key=lambda z: z["t"])
        # 回合开始时的 C4 持有者 = 最早的持包者（pickup / drop 的 who）
        c4_carrier = None
        for b in bombs:
            if b.get("who"):
                c4_carrier = b["who"]
                break

        # C4 炸死的人：demo 里这类死亡不进击杀事件，用「alive 由 1 变 0 且紧贴爆炸时刻」
        # 补出来，否则击杀日志里看着一个都没炸死
        _exb = [b for b in bombs if b["type"] == "explode"]
        if _exb:
            _te = _exb[0]["t"]
            _known = {k[2] for k in kills}
            for p in plist:
                if p["name"] in _known:
                    continue
                prev = None
                for q in p["s"]:
                    if prev is not None and prev == 1 and q[10] == 0 and -0.6 <= q[0] - _te <= 1.2:
                        kills.append([round(q[0], 2), "", p["name"], "c4", 0, "", 0])
                        _known.add(p["name"])
                        break
                    prev = q[10]
            kills.sort(key=lambda z: z[0])

        # 该回合双方队伍经济（开始余额 / 战后装备）
        my_side = next((p["side"] for p in plist if p["mine"]), None)
        opp_side = ("CT" if my_side == "T" else "T") if my_side else None
        _ec = econ_map.get((rd, my_side), {})
        _eo = econ_map.get((rd, opp_side), {})
        # 队伍经济 = 5 人现金合计(post_bal) + 5 人装备价值合计(end_eq)
        # 原来 mine/opp 直接塞的是 start_eq（起始装备价值），那不是"存款"
        _mc, _me = (_ec.get("post") or 0), (_ec.get("eq") or 0)
        _oc, _oe = (_eo.get("post") or 0), (_eo.get("eq") or 0)
        econ_info = {"mine": _mc + _me, "opp": _oc + _oe,
                     "mine_cash": _mc, "opp_cash": _oc,
                     "mine_eq": _me, "opp_eq": _oe,
                     "mine_end": _me, "opp_end": _oe,
                     "mine_side": my_side, "opp_side": opp_side}

        out_rounds.append({"r": rd, "winner": r["winner"], "reason": r["reason"],
                           "a_side": my_side or r["a_side"],
                           "t0": 0.0, "fz": round((fzt - t0) / 64.0, 2),
                           "dur": round((t1 - t0) / 64.0, 2),
                           "players": plist, "kills": kills, "shots": shots, "grenades": grenades,
                           "bombs": bombs, "c4": c4_carrier,
                           "dmg": dmg_by_round.get(rd, {}), "util": util,
                           "econ": econ_info})

    stats_map = {}
    for row in conn.execute(
            """SELECT p.name, x.adr, x.kast, x.rating, x.assists, x.kills, x.deaths, x.hs,
                      x.fk, x.mk2, x.mk3, x.mk4, x.dmg
               FROM pms x JOIN players p ON p.steamid=x.steamid AND p.match_id=x.match_id
               WHERE x.match_id=?""", (match_id,)):
        stats_map[row["name"]] = {"adr": row["adr"], "kast": row["kast"], "rating": row["rating"],
                                  "assists": row["assists"], "kills": row["kills"],
                                  "deaths": row["deaths"], "hs": row["hs"],
                                  "fk": row["fk"],
                                  "mk": (row["mk2"] or 0) + (row["mk3"] or 0) + (row["mk4"] or 0)}
    for r in out_rounds:
        for p in r["players"]:
            st = stats_map.get(p["name"], {})
            # 这些是「整场」统计，不是回合内累计 —— 输出前统一修精度，
            # 否则 kast 的原始浮点（72.7272720336914）会直接糊到表格里
            adr = st.get("adr")
            kast = st.get("kast")
            rating = st.get("rating")
            p["adr"] = round(adr, 1) if adr is not None else None
            p["kast"] = round(kast, 1) if kast is not None else None
            p["rating"] = round(rating, 2) if rating is not None else None
            p["assists"] = st.get("assists", 0)
            p["fk"] = st.get("fk", 0)
            p["mk"] = st.get("mk", 0)
            k = st.get("kills") or 0
            p["hs"] = round((st.get("hs") or 0) / k * 100, 0) if k else 0

    return {"map": map_name, "pos": [pos_x, pos_y, scale], "match_id": match_id,
            "replay_v": REPLAY_V, "layers": layers, "rounds": out_rounds}
