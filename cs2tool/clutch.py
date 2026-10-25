"""残局与多杀重建 —— 从 kills / rounds 原始事件重建，不依赖 awpy 的高层字段。

为什么自己算
------------
awpy 3.1.1 的 `stats` 只给 `clutches_played / clutches_won`，`clutch_1v1..1v5`
字段常年返回 0（未填充）。所以 1vN 分布、残局内击杀/伤害、保枪、人数变化
这些必须从事件流重建。

重建原则
--------
1. 以回合为单元，按 tick 递增回放击杀，维护双方存活人数
2. 玩家成为本方唯一存活者且敌方 > 0 → 该玩家进入残局（机会 +1）
3. 残局窗口 = [残局起始 tick, 回合结束 tick]，窗口内的击杀/伤害计入该残局
4. 残局结果取回合结果（本方赢 = 残局胜）
5. 同一回合同一玩家只记一次残局机会（哪怕反复死而复生不可能）

数据不足时不伪造：拿不到的字段返回 None，前端显示 —。
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict


def _side_rivals(side: str) -> str:
    return "CT" if side == "T" else "T"


def build(conn: sqlite3.Connection, steamid: int,
          match_ids: list[int] | None = None) -> dict:
    """返回该玩家的残局 / 多杀 / 人数优势统计。

    match_ids 限定只算这些场次（用于按地图、按时间窗单独统计）。
    不传则算全部——全局汇总与各切片必须用同一个函数，否则总量和明细会打架。
    """
    # ---- 取该玩家参与的比赛 ----
    matches = [dict(r) for r in conn.execute(
        """SELECT m.id, m.map, m.played_at,
                  (SELECT COUNT(*) FROM rounds r WHERE r.match_id=m.id) rounds_total
           FROM matches m JOIN pms x ON x.match_id=m.id
           WHERE x.steamid=? AND (m.excluded IS NULL OR m.excluded=0)
           ORDER BY m.played_at, m.id""", (steamid,))]
    if match_ids is not None:
        keep = set(match_ids)
        matches = [m for m in matches if m["id"] in keep]

    empty = {
        "clutch": {"played": 0, "won": 0, "lost": 0, "pct": None,
                   "by_size": {}, "kills": 0, "damage": 0,
                   "save_rounds": 0, "save_value": None, "rounds": []},
        "multi": {"mk2": 0, "mk3": 0, "mk4": 0, "mk5": 0, "rate": None},
        "advantage": {"first_adv": 0, "first_adv_win": 0, "first_adv_pct": None,
                      "comeback": 0, "comeback_by": {}, "rounds": []},
    }
    if not matches:
        return empty

    clutch_by_size: dict[str, dict] = {}
    clutch_rounds: list[dict] = []
    adv_rounds: list[dict] = []
    alive_total = 0
    mk = {"2": 0, "3": 0, "4": 0, "5": 0}
    total_rounds = 0

    for m in matches:
        mid = m["id"]
        # 每回合的击杀事件（按 tick 升序）
        kills = [dict(r) for r in conn.execute(
            """SELECT round, tick, attacker_steamid, victim_steamid
               FROM kills WHERE match_id=?
               ORDER BY round, tick""", (mid,))]
        per_round: dict[int, list] = defaultdict(list)
        for k in kills:
            per_round[int(k["round"] or 0)].append(k)

        rounds = [dict(r) for r in conn.execute(
            """SELECT round, t_start, t_freeze, t_end, a_side, a_win
               FROM rounds WHERE match_id=? ORDER BY round""", (mid,))]

        # 每人首回合阵营（kills 表没存 side，用 first_side 推）
        side_of = {int(r["steamid"]): _norm_side(r["first_side"])
                   for r in conn.execute(
                       "SELECT steamid, first_side FROM players WHERE match_id=?", (mid,))}

        # 该玩家每回合的阵营
        my_side_rows = conn.execute(
            """SELECT first_side FROM players WHERE match_id=? AND steamid=?""",
            (mid, steamid)).fetchone()
        first_side = (my_side_rows["first_side"] if my_side_rows else None) or "T"

        for rd in rounds:
            rn = int(rd["round"] or 0)
            if rn <= 0:
                continue
            total_rounds += 1
            my_side = _my_side(first_side, rn)
            enemies = _side_rivals(my_side)

            evs = per_round.get(rn, [])
            # 该玩家本回合击杀数（多杀统计）
            my_kills = sum(1 for k in evs if k["attacker_steamid"] == steamid)
            if my_kills >= 2:
                mk[str(min(my_kills, 5))] = mk.get(str(min(my_kills, 5)), 0) + 1

            # ---- 回放存活人数，找残局起点与人数优势点 ----
            alive = {my_side: 5, enemies: 5}
            clutch_start = None
            clutch_size = None
            first_adv_tick = None
            was_behind = False   # 曾处于人数劣势

            for k in evs:
                vs = _my_side(side_of.get(int(k["victim_steamid"] or 0), "T"), rn)
                if vs in alive and alive[vs] > 0:
                    alive[vs] -= 1
                # 人数优势首次形成
                if first_adv_tick is None and alive[my_side] > alive[enemies]:
                    first_adv_tick = int(k["tick"] or 0)
                if alive[my_side] < alive[enemies]:
                    was_behind = True
                # 残局起点：我是本方最后一人、敌方还有人
                if (clutch_start is None
                        and alive[my_side] == 1 and alive[enemies] > 0
                        and _i_am_alive(evs, steamid, my_side, k["tick"])):
                    clutch_start = int(k["tick"] or 0)
                    clutch_size = alive[enemies]

            # 本回合我是否成为残局者
            if clutch_start is not None:
                won = bool(rd["a_win"]) and _norm_side(rd["a_side"]) == my_side

                # 残局窗口内的击杀与伤害
                tk = [k for k in evs if int(k["tick"] or 0) >= clutch_start
                      and k["attacker_steamid"] == steamid]
                dmg = conn.execute(
                    """SELECT COALESCE(SUM(valid),0) d
                       FROM damage WHERE match_id=? AND round=? AND attacker_steamid=?
                       AND tick>=?""",
                    (mid, rn, steamid, clutch_start)).fetchone()

                # 保枪：残局输了，但活到回合判定前一刻 → 装备被保住
                save = 0
                save_eq = 0
                rte = None
                try:
                    rte = conn.execute(
                        """SELECT alive, equip FROM round_end
                           WHERE match_id=? AND round=? AND steamid=?""",
                        (mid, rn, steamid)).fetchone()
                    if rte and rte["alive"] and not won:
                        save = 1
                        save_eq = int(rte["equip"] or 0)
                except Exception:
                    pass

                key = f"1v{clutch_size}"
                b = clutch_by_size.setdefault(
                    key, {"played": 0, "won": 0, "lost": 0, "kills": 0,
                          "saves": 0, "save_eq": 0, "alive": 0})
                b["played"] += 1
                b["won" if won else "lost"] += 1
                b["kills"] += len(tk)
                b["saves"] += save
                b["save_eq"] += save_eq
                if rte and rte["alive"]:
                    b["alive"] += 1
                    alive_total += 1

                clutch_rounds.append({
                    "match_id": mid, "map": m["map"], "played_at": m["played_at"],
                    "round": rn, "size": clutch_size, "start_tick": clutch_start,
                    "won": won, "kills": len(tk), "damage": int(dmg["d"]) if dmg else 0,
                    "save": save, "save_eq": save_eq,
                })

            # 人数优势 / 劣势翻盘
            if first_adv_tick is not None:
                won = bool(rd["a_win"]) and _norm_side(rd["a_side"]) == my_side
                adv_rounds.append({
                    "match_id": mid, "map": m["map"], "round": rn,
                    "adv_tick": first_adv_tick, "won": won,
                    "comeback": bool(was_behind and won),
                })

    # ---- 汇总 ----
    played = sum(v["played"] for v in clutch_by_size.values())
    won = sum(v["won"] for v in clutch_by_size.values())
    save_total = sum(v.get("saves", 0) for v in clutch_by_size.values())
    save_eq_total = sum(v.get("save_eq", 0) for v in clutch_by_size.values())
    adv = [r for r in adv_rounds if r["adv_tick"]]
    adv_won = sum(1 for r in adv if r["won"])
    cb = [r for r in adv_rounds if r["comeback"]]

    cb_by = defaultdict(int)
    for r in clutch_rounds:
        if not r["won"]:
            cb_by[f"1v{r['size']}"] += 1

    return {
        "clutch": {
            "played": played, "won": won, "lost": played - won,
            "pct": round(won / played * 100, 1) if played else None,
            "by_size": {k: clutch_by_size[k] for k in sorted(clutch_by_size)},
            "kills": sum(r["kills"] for r in clutch_rounds),
            "damage": sum(r["damage"] for r in clutch_rounds),
            "save_rounds": save_total,
            "save_value": save_eq_total or None,
            "save_avg": round(save_eq_total / save_total) if save_total else None,
            # 残局存活率：残局里活到回合判定时点的比例（含打赢的）
            "alive": alive_total,
            "alive_pct": round(alive_total / played * 100, 1) if played else None,
            "save_pct": round(save_total / played * 100, 1) if played else None,
            "rounds": sorted(clutch_rounds, key=lambda r: (r["played_at"] or "", r["round"])),
        },
        "multi": {
            "mk2": mk.get("2", 0), "mk3": mk.get("3", 0),
            "mk4": mk.get("4", 0), "mk5": mk.get("5", 0),
            "rate": round((mk.get("2", 0) + mk.get("3", 0) + mk.get("4", 0) + mk.get("5", 0))
                          / total_rounds * 100, 1) if total_rounds else None,
        },
        "advantage": {
            "first_adv": len(adv), "first_adv_win": adv_won,
            "first_adv_pct": round(adv_won / len(adv) * 100, 1) if adv else None,
            "comeback": len(cb), "comeback_by": dict(cb_by),
            "rounds": sorted(adv_rounds, key=lambda r: (r["match_id"], r["round"])),
        },
    }


def _norm_side(s: str | None) -> str:
    s = (s or "").lower()
    if s.startswith("t"):
        return "T"
    if s.startswith("c"):
        return "CT"
    return s.upper()


def _my_side(first_side: str, rnd: int) -> str:
    """CS2 阵营：常规 12 回合半场；加时每 3 回合换边，起点延续第二半场。"""
    s = _norm_side(first_side) or "T"
    o = _side_rivals(s)
    if rnd <= 12:
        return s
    if rnd <= 24:
        return o
    ot = (rnd - 25) // 3
    return o if ot % 2 == 0 else s


def _i_am_alive(evs: list, steamid: int, my_side: str, at_tick) -> bool:
    """该 tick 之前我是否还没死（用于确认残局起点确实由我触发）。"""
    at = int(at_tick or 0)
    for k in evs:
        if int(k["tick"] or 0) > at:
            break
        if k["victim_steamid"] == steamid:
            return False
    return True
