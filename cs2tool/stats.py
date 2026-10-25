"""从原始表计算每人每场指标，写入 pms 表。可重复运行（口径改了重算即可）。

思路：ingest 只存原始事件，指标全部在这里算，所以调整口径不必重新解析 demo。
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict


def side_of_round(first_side: str, rnd: int, half: int = 12) -> str:
    """某回合某玩家所在阵营。

    CS2 规则：
      · 常规赛 MR12：1-12 第一半场，13-24 第二半场
      · 加时 MR3：每 3 回合换边，起点延续第二半场阵营
        （25-27 同第二半场 → 28-30 换回 → 31-33 再换 …）
      · 非标准半场（小局/自定义）：只有一次换边
    """
    s = first_side or "T"
    o = "CT" if s == "T" else "T"
    if rnd <= half:
        return s
    if half == 12:
        if rnd <= 24:
            return o          # 第二半场
        # 加时：25-27 延续 o，每 3 回合交替
        ot = (rnd - 25) // 3
        return o if ot % 2 == 0 else s
    return o


def rating2(adr: float, kpr: float, dpr: float, apr: float, kast_pct: float) -> float:
    impact = 2.13 * kpr + 0.42 * apr - 0.41
    return (0.0073 * kast_pct + 0.3591 * kpr - 0.5329 * dpr + 0.2372 * impact
            + 0.0032 * adr + 0.1587) / 1.052


def compute_match(conn: sqlite3.Connection, match_id: int) -> int:
    rounds = conn.execute(
        "SELECT round, t_end, winner, reason FROM rounds WHERE match_id=? ORDER BY round",
        (match_id,)).fetchall()
    if not rounds:
        return 0
    n = len(rounds)
    half = 12 if n > 20 else n // 2
    players = {r["steamid"]: dict(r) for r in
               conn.execute("SELECT steamid, name, first_side FROM players WHERE match_id=?", (match_id,))}
    if not players:
        return 0

    kills = [dict(k) for k in conn.execute(
        "SELECT round, tick, attacker_steamid a, victim_steamid v, assister_steamid s, "
        "headshot, dmg_health FROM kills WHERE match_id=? ORDER BY round, tick", (match_id,))]
    # 伤害口径：valid = 按受害者剩余血量截断、排除死后补枪的有效伤害（不含甲伤，与游戏内 HUD 一致）
    hurts = [dict(h) for h in conn.execute(
        "SELECT round, attacker_steamid a, valid d FROM damage WHERE match_id=?", (match_id,))]

    side = {(p, rd): side_of_round(players[p]["first_side"], rd, half)
            for p in players for rd in range(1, n + 1)}

    K = defaultdict(int); D = defaultdict(int); A = defaultdict(int)
    HS = defaultdict(int); DMG = defaultdict(int)
    k_rounds = defaultdict(set); a_rounds = defaultdict(set); d_rounds = defaultdict(set)
    tK = defaultdict(int); tD = defaultdict(int); tDMG = defaultdict(int)
    cK = defaultdict(int); cD = defaultdict(int); cDMG = defaultdict(int)
    fk = defaultdict(int); fd = defaultdict(int)
    traded_rounds = defaultdict(set)
    multi_best = defaultdict(int)

    by_round = defaultdict(list)
    for k in kills:
        by_round[k["round"]].append(k)
        a, v, s, rd = k["a"], k["v"], k["s"], k["round"]
        if a and a > 0:
            K[a] += 1; k_rounds[a].add(rd)
            if k["headshot"]:
                HS[a] += 1
            if side.get((a, rd)) == "T":
                tK[a] += 1
            else:
                cK[a] += 1
        if v and v > 0:
            D[v] += 1; d_rounds[v].add(rd)
            if side.get((v, rd)) == "T":
                tD[v] += 1
            else:
                cD[v] += 1
        if s and s > 0:
            A[s] += 1; a_rounds[s].add(rd)

    for h in hurts:
        a, rd, d = h["a"], h["round"], h["d"] or 0
        if a and a > 0:
            DMG[a] += d
            if side.get((a, rd)) == "T":
                tDMG[a] += d
            else:
                cDMG[a] += d

    for rd, lst in by_round.items():
        lst.sort(key=lambda x: x["tick"])
        if lst[0]["a"] and lst[0]["a"] > 0:
            fk[lst[0]["a"]] += 1
        if lst[0]["v"] and lst[0]["v"] > 0:
            fd[lst[0]["v"]] += 1
        cnt = defaultdict(int)
        for k in lst:
            if k["a"] and k["a"] > 0:
                cnt[k["a"]] += 1
                multi_best[k["a"]] = max(multi_best[k["a"]], cnt[k["a"]])
        # 补枪：队友在 5 秒内杀掉凶手
        for i, k in enumerate(lst):
            v, vt = k["v"], k["tick"]
            if not v or v <= 0:
                continue
            for later in lst[i + 1:]:
                if later["tick"] - vt > 320:
                    break
                a2 = later["a"]
                if a2 and a2 > 0 and a2 != v and side.get((a2, rd)) == side.get((v, rd)):
                    traded_rounds[v].add(rd)
                    break

    rows = []
    for pid in players:
        tot_k, tot_d, tot_a, tot_dmg = K[pid], D[pid], A[pid], DMG[pid]
        kast_n = sum(1 for rd in range(1, n + 1)
                     if (rd in k_rounds[pid]) or (rd in a_rounds[pid])
                     or (rd not in d_rounds[pid]) or (rd in traded_rounds[pid]))
        kast = kast_n / n * 100
        kpr, dpr, apr = tot_k / n, tot_d / n, tot_a / n
        adr = tot_dmg / n
        rows.append(dict(
            match_id=match_id, steamid=pid, rounds=n,
            t_rounds=sum(1 for rd in range(1, n + 1) if side.get((pid, rd)) == "T"),
            ct_rounds=sum(1 for rd in range(1, n + 1) if side.get((pid, rd)) == "CT"),
            kills=tot_k, deaths=tot_d, assists=tot_a, hs=HS[pid], dmg=tot_dmg,
            adr=round(adr, 1), kast=round(kast, 1),
            rating=round(rating2(adr, kpr, dpr, apr, kast), 2),
            kpr=round(kpr, 2), dpr=round(dpr, 2), apr=round(apr, 2),
            impact=round(2.13 * kpr + 0.42 * apr - 0.41, 2),
            fk=fk[pid], fd=fd[pid],
            mk2=1 if multi_best[pid] >= 2 else 0,
            mk3=1 if multi_best[pid] >= 3 else 0,
            mk4=1 if multi_best[pid] >= 4 else 0,
            tkills=tK[pid], t_deaths=tD[pid], t_dmg=tDMG[pid],
            ct_kills=cK[pid], ct_deaths=cD[pid], ct_dmg=cDMG[pid],
        ))

    with conn:
        conn.execute("DELETE FROM pms WHERE match_id=?", (match_id,))
        cols = list(rows[0].keys())
        conn.executemany(
            f"INSERT INTO pms ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [tuple(r[c] for c in cols) for r in rows])
    return len(rows)


def recompute_all(conn: sqlite3.Connection) -> int:
    n = 0
    for r in conn.execute("SELECT id FROM matches").fetchall():
        n += compute_match(conn, r["id"])
    return n
