"""数据库体检：定位「已分析但页面没数据」到底断在哪一步。"""
from __future__ import annotations

import os
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cs2.db")

if not os.path.isfile(DB):
    print(f"[错误] 找不到数据库：{DB}")
    print("       程序至少启动过一次才会生成这个文件。")
    sys.exit(1)

print(f"数据库: {DB}")
print(f"大小  : {os.path.getsize(DB) / 1048576:.2f} MB")
print()

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

TABLES = ["matches", "demos", "players", "kills", "rounds", "pms",
          "economy", "damage", "snapshots"]
print("=" * 46)
print("  表行数")
print("=" * 46)
counts = {}
for t in TABLES:
    try:
        n = c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        counts[t] = n
        flag = "" if n else "   <-- 空!"
        print(f"  {t:12s} {n:>7d}{flag}")
    except sqlite3.OperationalError as e:
        print(f"  {t:12s}   缺失 ({e})")

print()
print("=" * 46)
print("  玩家身份")
print("=" * 46)
try:
    rows = c.execute(
        "SELECT id, map, played_at, my_steamid FROM matches ORDER BY id").fetchall()
    for r in rows:
        print(f"  场次 {r['id']}  {r['map']:14s} {r['played_at'] or '?':16s} "
              f"my_steamid={r['my_steamid'] or 'NULL  <-- 没设!'}")
except Exception as e:
    print("  读取失败:", e)

print()
try:
    me = c.execute("SELECT steamid, name FROM players WHERE is_me=1 LIMIT 5").fetchall()
    if me:
        for r in me:
            print(f"  is_me=1 : {r['name']} ({r['steamid']})")
    else:
        print("  is_me=1 : 无  <-- 这就是页面空数据的直接原因")
except Exception as e:
    print("  读取失败:", e)

print()
print("=" * 46)
print("  pms 明细（页面读的就是这张表）")
print("=" * 46)
if counts.get("pms"):
    try:
        rows = c.execute(
            """SELECT p.name, p.steamid, p.is_me, x.match_id, x.rounds, x.kills, x.deaths,
                      x.adr, x.rating
               FROM pms x JOIN players p ON p.steamid=x.steamid AND p.match_id=x.match_id
               ORDER BY p.name, x.match_id""").fetchall()
        seen = set()
        for r in rows:
            adr = f"{r['adr']:.1f}" if r["adr"] is not None else "NULL"
            rat = f"{r['rating']:.2f}" if r["rating"] is not None else "NULL"
            mark = "  <== 你" if r["is_me"] else ""
            print(f"  M{r['match_id']} {r['name'][:14]:16s} sid={r['steamid']} "
                  f"R{r['rounds']} {r['kills']}/{r['deaths']} ADR={adr:>6s} "
                  f"Rating={rat}{mark}")
            seen.add((r["steamid"], r["name"]))
        print()
        print("  按 steamid 汇总（出现场次数）:")
        for sid, name, n in c.execute(
                """SELECT p.steamid, MIN(p.name) name, COUNT(DISTINCT x.match_id) n
                   FROM pms x JOIN players p ON p.steamid=x.steamid AND p.match_id=x.match_id
                   GROUP BY p.steamid ORDER BY n DESC"""):
            print(f"    {name[:16]:18s} sid={sid}  {n} 场")
    except Exception as e:
        print("  读取失败:", e)
else:
    print("  空表 -> 点主页「重新统计」；若仍为空，说明 rounds/kills 也没写入")

print()
print("=" * 46)
print("  demo 分析状态")
print("=" * 46)
try:
    for r in c.execute("SELECT name, analyzed, match_id, error FROM demos").fetchall():
        err = (r["error"] or "")[:40]
        print(f"  {r['name'][:42]:44s} analyzed={r['analyzed']} "
              f"match={r['match_id']} {err}")
except Exception as e:
    print("  读取失败:", e)

print()
print("诊断完成。把这段输出整段发回来。")
