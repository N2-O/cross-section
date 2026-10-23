"""修库：把「我」的 steamid 对齐，并按正确阵营重算每回合 a_side / a_win。

为什么需要 ——
早期解析把 matches.my_steamid 写成过一个不在任何名单里的号（真实案例：库里 25 场
全写成 ...970，本人是 ...967），之后每次解析又继承这个值，于是每场都取不到
my_side0，a_side 退化成硬编码的 "T"：
  · demos 列表 JOIN pms 不上 → K/D/ADR 满屏横线
  · 比分和胜负按 T 方算 → 跟你没关系，可能还是反的
  · 概览的胜率也走 rounds.a_win → 一起错
这个脚本按 players.first_side 把每场每回合的阵营重推一遍，不动 demo 文件、不重解析。

用法：
    python cs2tool/repair_me.py --data <data 目录>           # 直接改库
    python cs2tool/repair_me.py --data <data 目录> --dry     # 只报告，不改
data 目录里应有 cs2.db 和 settings.json（就是工具启动时 --data 指向的那个目录）。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys


def side_of(fs: str, rnd: int, half: int = 12) -> str:
    """CS2 阵营：常规 12 回合半场，加时每 3 回合换边（与 awpy_ingest 保持一致）。"""
    s = fs or "T"
    o = "CT" if s == "T" else "T"
    if rnd <= half:
        return s
    if rnd <= 24:
        return o
    ot = (rnd - 25) // 3
    return o if ot % 2 == 0 else s


def pick_me(conn: sqlite3.Connection, settings_path: str) -> int | None:
    """定「我」是谁：settings.my_steamid → settings.steamid → players 出场次数投票。"""
    cands: list[int] = []
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for k in ("my_steamid", "steamid"):
            v = str(cfg.get(k) or "").strip()
            if v.isdigit():
                cands.append(int(v))
    except Exception:
        pass

    total = conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]
    votes = conn.execute(
        "SELECT steamid, COUNT(DISTINCT match_id) n FROM players "
        "GROUP BY steamid ORDER BY n DESC, steamid LIMIT 5").fetchall()
    for r in votes:
        if r["n"] >= max(2, total - 1):
            cands.append(int(r["steamid"]))

    for c in cands:
        if conn.execute("SELECT 1 FROM players WHERE steamid=? LIMIT 1", (c,)).fetchone():
            return c
    # 只要出现在名单里就还算能用（可能只打过几场）
    for c in cands:
        if conn.execute("SELECT 1 FROM pms WHERE steamid=? LIMIT 1", (c,)).fetchone():
            return c
    return votes and int(votes[0]["steamid"]) or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="工具的 data 目录（含 cs2.db / settings.json）")
    ap.add_argument("--dry", action="store_true", help="只报告，不写库")
    a = ap.parse_args()

    db = os.path.join(a.data, "cs2.db")
    if not os.path.isfile(db):
        print(f"找不到 {db}")
        return 2
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    me = pick_me(conn, os.path.join(a.data, "settings.json"))
    if not me:
        print("无法确定「我」是谁（settings 里没配 steamid，players 表也投不出票）")
        return 1
    print(f"认定本人 steamid = {me}")

    matches = conn.execute("SELECT id, map, played_at, my_steamid FROM matches ORDER BY id").fetchall()
    n_fixed = n_nome = 0
    before_w = before_t = after_w = after_t = 0

    for m in matches:
        mid = m["id"]
        rd = conn.execute("SELECT round, winner, a_side, a_win FROM rounds WHERE match_id=? "
                          "ORDER BY round", (mid,)).fetchall()
        before_t += len(rd)
        before_w += sum(int(r["a_win"] or 0) for r in rd)

        fs_row = conn.execute("SELECT first_side FROM players WHERE match_id=? AND steamid=?",
                              (mid, me)).fetchone()
        if not fs_row or not fs_row["first_side"]:
            # 这场没有我：阵营留空，别再拿 T 方冒充
            n_nome += 1
            if not a.dry:
                with conn:
                    conn.execute("UPDATE rounds SET a_side='', a_win=0 WHERE match_id=?", (mid,))
                    if m["my_steamid"] != me:
                        pass  # 保持原值：这场确实没我，写我的话 _me 也照样 JOIN 不到
            continue

        fs = fs_row["first_side"]
        w = 0
        if not a.dry:
            with conn:
                for r in rd:
                    s = side_of(fs, int(r["round"]))
                    win = int(r["winner"] == s)
                    w += win
                    conn.execute("UPDATE rounds SET a_side=?, a_win=? WHERE match_id=? AND round=?",
                                 (s, win, mid, r["round"]))
                conn.execute("UPDATE matches SET my_steamid=? WHERE id=?", (me, mid))
                conn.execute("UPDATE players SET is_me=(steamid=?) WHERE match_id=?", (me, mid))
        else:
            for r in rd:
                w += int(r["winner"] == side_of(fs, int(r["round"])))
        n_fixed += 1
        after_t += len(rd)
        after_w += w
        if m["my_steamid"] != me:
            print(f"  #{mid} {m['map']} {m['played_at']}: my_steamid {m['my_steamid']} → {me}，"
                  f"{len(rd)} 回合按 {fs} 开局重算（{w} 胜）")

    if not a.dry:
        with conn:
            conn.execute("UPDATE players SET is_me=(steamid=?) WHERE steamid=?", (me, me))
    print(f"\n有我的场：{n_fixed} 场已重算；没我的场：{n_nome} 场（阵营清空）")
    print(f"我方回合胜：修正前 {before_w}/{before_t} → 修正后 {after_w}/{after_t}")
    print("（--dry 模式，未写库）" if a.dry else "已写库。重启工具服务后生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
