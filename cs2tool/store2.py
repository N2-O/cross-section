"""数据层：schema + demo 管理 + 指标计算。

分工：
  demos        每次扫描到的 demo 文件（含未分析的）
  matches      已解析的场次
  players      每场玩家
  rounds/kills/damage/economy/tracks   原始数据
  pms          每场每人的聚合指标（可从原始表重算）

指标口径改了只需要跑 recompute()，不用重新解析 demo。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Sequence

# 所有按 match_id 存的子表。删场次时必须全部覆盖，
# 漏一张就会在重解析/删 demo 后留下孤儿行，按 steamid 求和会成倍放大。
# 新增表时只改这一处，不要在各处另写清单。
MATCH_CHILD_TABLES = (
    "kills", "damage", "rounds", "economy", "players", "pms", "snapshots",
    "purchases", "blinds", "weapon_stat", "round_end",
    "grenade_throw", "grenade_use", "spend_cat",
)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

-- 扫描到的 demo 文件（不管有没有分析）
CREATE TABLE IF NOT EXISTS demos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,   -- 文件名
    size      INTEGER,
    mtime     TEXT,                   -- 文件时间（≈ 比赛时间）
    analyzed  INTEGER DEFAULT 0,
    match_id  INTEGER,
    map       TEXT,
    platform  TEXT,
    server    TEXT,
    error     TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file        TEXT NOT NULL,
    file_hash   TEXT NOT NULL UNIQUE,
    map         TEXT,
    server      TEXT,
    platform    TEXT,
    played_at   TEXT,
    tickrate    INTEGER DEFAULT 64,
    total_ticks INTEGER,
    duration_s  REAL,
    my_steamid  INTEGER,
    imported_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS players (
    match_id   INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    steamid    INTEGER NOT NULL,
    name       TEXT,
    first_side TEXT,
    is_me      INTEGER DEFAULT 0,
    PRIMARY KEY (match_id, steamid)
);

CREATE TABLE IF NOT EXISTS rounds (
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    round    INTEGER NOT NULL,
    t_start  INTEGER, t_freeze INTEGER, t_end INTEGER,
    winner   TEXT, reason TEXT,
    a_side   TEXT, a_win INTEGER,
    PRIMARY KEY (match_id, round)
);

CREATE TABLE IF NOT EXISTS kills (
    match_id INTEGER NOT NULL, round INTEGER NOT NULL, tick INTEGER NOT NULL,
    attacker_steamid INTEGER, victim_steamid INTEGER, assister_steamid INTEGER,
    weapon TEXT, headshot INTEGER, penetrated INTEGER, noscope INTEGER,
    thrusmoke INTEGER, attackerblind INTEGER, jumping INTEGER,
    dmg_health INTEGER, dmg_armor INTEGER, distance REAL, hitgroup TEXT,
    victim_weapon TEXT
);
CREATE INDEX IF NOT EXISTS idx_kills ON kills(match_id, round, tick);

CREATE TABLE IF NOT EXISTS damage (
    match_id INTEGER NOT NULL, round INTEGER NOT NULL, tick INTEGER NOT NULL,
    attacker_steamid INTEGER, victim_steamid INTEGER,
    weapon TEXT, dmg_health INTEGER, dmg_armor INTEGER, hitgroup TEXT
);
CREATE INDEX IF NOT EXISTS idx_damage ON damage(match_id, round);

CREATE TABLE IF NOT EXISTS economy (
    match_id INTEGER NOT NULL, round INTEGER NOT NULL, side TEXT NOT NULL,
    pre_bal INTEGER, post_bal INTEGER, end_bal INTEGER,
    start_eq INTEGER, end_eq INTEGER, buy_type TEXT,
    PRIMARY KEY (match_id, round, side)
);

-- 每人每场的聚合指标
CREATE TABLE IF NOT EXISTS pms (
    match_id INTEGER NOT NULL, steamid INTEGER NOT NULL,
    rounds INTEGER, t_rounds INTEGER, ct_rounds INTEGER,
    kills INTEGER, deaths INTEGER, assists INTEGER, hs INTEGER,
    dmg INTEGER, adr REAL, kast REAL, rating REAL,
    kpr REAL, dpr REAL, apr REAL, impact REAL,
    fk INTEGER, fd INTEGER, mk2 INTEGER, mk3 INTEGER, mk4 INTEGER,
    tkills INTEGER, t_deaths INTEGER, t_dmg INTEGER,
    ct_kills INTEGER, ct_deaths INTEGER, ct_dmg INTEGER,
    PRIMARY KEY (match_id, steamid)
);
CREATE INDEX IF NOT EXISTS idx_pms ON pms(steamid);

-- 每场的能力快照（跑一次分析写一条，用于长期趋势/退步预警）
CREATE TABLE IF NOT EXISTS snapshots (
    match_id   INTEGER NOT NULL,
    steamid    INTEGER NOT NULL,
    taken_at   TEXT DEFAULT (datetime('now','localtime')),
    played_at  TEXT,
    map        TEXT,
    -- 原始单场指标
    adr REAL, kast REAL, rating REAL, kd REAL, kpr REAL, dpr REAL,
    impact REAL, hs_pct REAL, rounds INTEGER,
    fk INTEGER, fd INTEGER, fk_wr REAL,        -- 首杀数/首死数/拿首杀后胜率
    spent_avg REAL, inv_rate REAL,             -- 队伍人均花费 / 装备保留率
    weak_death_pct REAL,                       -- 被劣势武器击杀率
    duel_adv_wr REAL, duel_disadv_wr REAL,     -- 对枪胜率（优势/劣势）
    pistol_wr REAL, buy_full_wr REAL, buy_force_wr REAL,  -- 手枪局/全买/强起胜率
    PRIMARY KEY (match_id, steamid)
);
CREATE INDEX IF NOT EXISTS idx_snap ON snapshots(steamid, played_at);

-- 购买事件（awpy.item_events）
CREATE TABLE IF NOT EXISTS purchases (
    match_id   INTEGER NOT NULL,
    round      INTEGER,
    tick       INTEGER,
    steamid    INTEGER,
    name       TEXT,
    side       TEXT,
    action     TEXT,          -- purchase / pickup / drop
    item       TEXT,
    cost       INTEGER,
    orig_owner INTEGER,       -- 拾取时原主人
    near_zone  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pur ON purchases(match_id, steamid);

-- 闪光致盲事件（awpy.blinds）
CREATE TABLE IF NOT EXISTS blinds (
    match_id  INTEGER NOT NULL,
    round     INTEGER,
    tick      INTEGER,
    attacker_steamid INTEGER,
    victim_steamid   INTEGER,
    attacker_side    TEXT,
    victim_side      TEXT,
    duration         REAL
);
CREATE INDEX IF NOT EXISTS idx_blind ON blinds(match_id, attacker_steamid);

-- 投掷次数（按类型；awpy 3.1.1 无法归属到人）
CREATE TABLE IF NOT EXISTS grenade_throw (
    match_id INTEGER NOT NULL,
    type     TEXT NOT NULL,
    n        INTEGER,
    PRIMARY KEY (match_id, type)
);

-- 投掷次数（按人 + 类型）：改用 demoparser2 的引爆事件取投掷者，
-- smokegrenade_detonate / flashbang_detonate / hegrenade_detonate /
-- decoy_started / inferno_startburn 的 user_steamid 100% 有值。
-- 注意这是「投出去了」的数量，买到手但死在手里的不在这里；
-- 所以 投出数 <= 购买数 是正常的（实测全场投出率约 55%）。
CREATE TABLE IF NOT EXISTS grenade_use (
    match_id INTEGER NOT NULL,
    steamid  INTEGER NOT NULL,
    type     TEXT NOT NULL,
    n        INTEGER,
    PRIMARY KEY (match_id, steamid, type)
);

-- 花费构成（按阵营）：步枪/手枪/道具/甲/钳子/其他
-- 武器和道具来自 purchases 的精确 cost；
-- 甲和钳子 purchases 表里没有，用 m_iCashSpentThisRound 与 purchases 的差值反推，
-- 其中钳子按 m_bPawnHasDefuser 由 False→True 的回合 × $400 计入（只有 CT 有）。
CREATE TABLE IF NOT EXISTS spend_cat (
    match_id INTEGER NOT NULL,
    side     TEXT NOT NULL,
    cat      TEXT NOT NULL,
    cost     INTEGER,
    PRIMARY KEY (match_id, side, cat)
);
-- 回合末状态（在回合判定前一刻采样，用于保枪/存活判定）
CREATE TABLE IF NOT EXISTS round_end (
    match_id INTEGER NOT NULL,
    round    INTEGER NOT NULL,
    steamid  INTEGER NOT NULL,
    alive    INTEGER,          -- 1=回合结束前仍活着
    equip    INTEGER,          -- 当时携带的装备价值（可保留部分）
    PRIMARY KEY (match_id, round, steamid)
);
CREATE INDEX IF NOT EXISTS idx_rte ON round_end(match_id, steamid);

-- 每武器射击统计（命中率按武器算，不能拿全局值代替）
CREATE TABLE IF NOT EXISTS weapon_stat (
    match_id INTEGER NOT NULL,
    steamid  INTEGER NOT NULL,
    weapon   TEXT NOT NULL,
    fires    INTEGER,          -- 该武器开火次数
    hits     INTEGER,          -- 其中产生了伤害的开火次数
    kills    INTEGER,          -- 该武器击杀数
    imprecise INTEGER,         -- 开火瞬间速度 >34 units/s 的次数（未急停）
    PRIMARY KEY (match_id, steamid, weapon)
);
"""

PLATFORM_HINTS = [
    ("valve", "官方匹配"), ("faceit", "FACEIT"), ("5e", "5E"), ("b5", "B5"),
    ("perfect world", "完美世界"), ("perfectworld", "完美世界"), ("esl", "ESL"),
    ("esea", "ESEA"), ("gamersclub", "Gamers Club"), ("fastcup", "FastCup"),
]


def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """老库补列（CREATE TABLE IF NOT EXISTS 不会改已有表）。"""
    want = {
        "kills": [("victim_weapon", "TEXT"), ("jumping", "INTEGER")],
        # 每武器射击统计：不精确射击率要按武器分档，后加
        "weapon_stat": [("imprecise", "INTEGER")],
        # 掉线/中途加入：0 或 NULL 表示整场都在
        "players": [("left_round", "INTEGER"), ("joined_round", "INTEGER"),
                    ("left_reason", "TEXT"), ("reconnect_round", "INTEGER")],
        # 回合被暂停的秒数（从回合时长推断，正常上限 115 秒）
        "rounds": [("paused_sec", "REAL")],
        # 排除出统计的局（投降、摆烂、半路不打了）：
        # 打完但自己没认真打的数据留在库里，但默认不参与平均/走势/能力画像
        "matches": [("excluded", "INTEGER DEFAULT 0"), ("exclude_note", "TEXT")],
        # awpy 统计层新增的指标
        "pms": [
            ("flash_assists", "INTEGER"),
            ("trade_kills", "INTEGER"),
            ("traded_deaths", "INTEGER"),
            ("clutch_played", "INTEGER"),
            ("clutch_won", "INTEGER"),
            ("clutch_1v1", "INTEGER"), ("clutch_1v2", "INTEGER"),
            ("clutch_1v3", "INTEGER"), ("clutch_1v4", "INTEGER"),
            ("clutch_1v5", "INTEGER"),
            ("utility_damage", "INTEGER"),
            ("flashes_thrown", "INTEGER"),
            ("enemies_flashed", "INTEGER"),
            ("flash_duration", "REAL"),
            ("survive_rounds", "INTEGER"),
            ("fire_count", "INTEGER"),
            ("hit_count", "INTEGER"),
            ("imprecise_shots", "INTEGER"),
            ("stop_shots", "INTEGER"),
            ("gun_fire_count", "INTEGER"),
            ("t_fk", "INTEGER"),
            ("t_fd", "INTEGER"),
            ("ct_fk", "INTEGER"),
            ("ct_fd", "INTEGER"),
            ("spent", "INTEGER"),
            ("equip_value", "INTEGER"),
            ("equip_round_start", "INTEGER"),
            ("plants", "INTEGER"),
            ("defuses", "INTEGER"),
            ("penetrated_kills", "INTEGER"),
            ("thrusmoke_kills", "INTEGER"),
            ("noscope_kills", "INTEGER"),
            ("version", "TEXT"),
        ],
    }
    for table, cols in want.items():
        try:
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.Error:
            continue
        for name, typ in cols:
            if name not in have:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
                except sqlite3.Error:
                    pass
    conn.commit()


def detect_platform(server: str) -> str:
    s = (server or "").lower()
    for key, name in PLATFORM_HINTS:
        if key in s:
            return name
    return "其他" if server else "未知"


# ---------------- demo 文件管理 ----------------
def demo_real_time(filename: str) -> str | None:
    """从 demo 文件名推比赛结束时刻（本地时区）。

    Steam 分给每场比赛的 id（就是 demo 文件名第一段）高 33 位是 unix 时间戳：
        id >> 31  ==  比赛结束时刻（秒）
    拿一场已知时间的比赛验证过，和 Steam 比赛历史页显示的相差 53 秒（结算延迟）。

    比文件 mtime 靠谱得多——mtime 是 demo 下载/复制到你机器上的时间，
    实测能差三天。
    """
    import datetime

    stem = filename
    for ext in (".dem.bz2", ".dem.gz", ".dem"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    part0 = (stem.split("_")[0] or "").lstrip("0")
    if not part0.isdigit():
        return None
    v = int(part0)
    if v.bit_length() < 40:          # 位数不够，不像 Steam id，别乱推
        return None
    try:
        return datetime.datetime.fromtimestamp(v >> 31).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return None


def relink_demos(conn: sqlite3.Connection, fallback_steamid=None) -> int:
    """按文件名把 demos 和 matches 重新接上，顺手补 my_steamid。

    症状：列表里 K/D/ADR 全是横线，但回放打得开。
    原因：matches 有数据、pms 也有，但 demos.match_id 是空的或者指向已删的旧 match
    （重新解析时 match 会重建，id 变了）。回放走缓存文件所以不受影响。

    还有一条更隐蔽的：matches.my_steamid 为空时，列表那条
    `LEFT JOIN pms p ON p.steamid = (SELECT my_steamid FROM matches WHERE id=d.match_id)`
    会退化成 p.steamid = NULL，行行匹配不上，同样是满屏横线。
    这种情况 relink 完 match_id 也没用，得把 my_steamid 补回去。
    """
    cur = conn.execute(
        """UPDATE demos SET
             match_id = (SELECT m.id FROM matches m WHERE m.file = demos.name),
             analyzed = 1,
             error    = NULL
           WHERE EXISTS (SELECT 1 FROM matches m WHERE m.file = demos.name)
             AND (match_id IS NULL
                  OR match_id NOT IN (SELECT id FROM matches))""")
    fixed = cur.rowcount

    # my_steamid 缺失 / 为 0 / 或者干脆是个脏值（那一场里根本没这个人）：
    # 用 settings 里的 steamid 补。这是「我是谁」的唯一可信来源。
    # 真实踩过的坑：库里 25 场 my_steamid 全是 ...970，而 players 249 行里
    # 没有这个人，正确的 ...967 出现 24 场 —— JOIN 不上 pms，列表满屏横线。
    if fallback_steamid:
        try:
            sid = int(str(fallback_steamid).strip())
        except (TypeError, ValueError):
            sid = 0
        if sid:
            cur2 = conn.execute(
                """UPDATE matches SET my_steamid = ?
                   WHERE my_steamid IS NULL OR my_steamid = 0 OR my_steamid = ''
                      OR (my_steamid <> ?
                          AND NOT EXISTS (SELECT 1 FROM players p
                                          WHERE p.match_id = matches.id
                                            AND p.steamid = matches.my_steamid))""",
                (sid, sid))
            fixed += cur2.rowcount

    # 投降局回填：老数据解析时还没有自动识别这一步，这里补上。
    # 整场投了（某个回合的 reason 带 surrender），标 excluded 不计入平均。
    cur3 = conn.execute(
        """UPDATE matches SET excluded = 1,
                  exclude_note = COALESCE(exclude_note, '投降（历史回填）')
           WHERE (excluded IS NULL OR excluded = 0)
             AND EXISTS (SELECT 1 FROM rounds r
                         WHERE r.match_id = matches.id
                           AND LOWER(COALESCE(r.reason,'')) LIKE '%surrender%')""")
    fixed += cur3.rowcount
    conn.commit()
    return fixed


def scan_demos(conn: sqlite3.Connection, demo_dir: str, my_steamid=None) -> dict:
    """扫描目录，把新文件登记进 demos 表。返回统计。"""
    os.makedirs(demo_dir, exist_ok=True)
    found = []
    for fn in sorted(os.listdir(demo_dir)):
        if not fn.lower().endswith((".dem", ".dem.bz2", ".dem.gz")):
            continue
        p = os.path.join(demo_dir, fn)
        if not os.path.isfile(p):
            continue
        st = os.stat(p)
        # 优先用文件名里的真实比赛时间；推不出来才退回文件 mtime
        t = demo_real_time(fn) or __import__("datetime").datetime.fromtimestamp(
            st.st_mtime).strftime("%Y-%m-%d %H:%M")
        found.append((fn, st.st_size, t))

    known = {r["name"] for r in conn.execute("SELECT name FROM demos")}
    added = 0
    with conn:
        for fn, size, mt in found:
            if fn in known:
                continue
            conn.execute(
                "INSERT INTO demos (name, size, mtime, analyzed) VALUES (?,?,?,0)",
                (fn, size, mt),
            )
            added += 1
    # 扫完顺手把断掉的 demos.match_id 接回去（重新解析后 match 会重建、id 变，
    # 老 match_id 就指向空，列表于是全是横线）
    fixed = relink_demos(conn, my_steamid)
    if fixed:
        print(f"  重连 {fixed} 条 demos ↔ matches")
    # 同步删除：文件已不在目录里的，连同分析结果一起清掉
    names = {f[0] for f in found}
    removed = []
    with conn:
        for r in conn.execute("SELECT name FROM demos").fetchall():
            if r["name"] in names:
                continue
            fn = r["name"]
            row = conn.execute("SELECT id FROM matches WHERE file=?", (fn,)).fetchone()
            if row:
                mid = row["id"]
                for t in MATCH_CHILD_TABLES:
                    try:
                        conn.execute(f"DELETE FROM {t} WHERE match_id=?", (mid,))
                    except sqlite3.OperationalError:
                        pass
                conn.execute("DELETE FROM matches WHERE id=?", (mid,))
            conn.execute("DELETE FROM demos WHERE name=?", (fn,))
            removed.append(fn)
    total = conn.execute("SELECT COUNT(*) c FROM demos").fetchone()["c"]
    done = conn.execute("SELECT COUNT(*) c FROM demos WHERE analyzed=1").fetchone()["c"]
    return {"found": len(found), "added": added, "removed": removed,
            "total": total, "analyzed": done}


def list_demos(conn: sqlite3.Connection, my_steamid: int | None = None) -> list[dict]:
    """demos 列表 + 每场「我」的数据。

    my_steamid 由调用方传「当前看谁」（server._me 的结果）。不能直接拿
    matches.my_steamid 做 JOIN —— 那是每场解析时落的快照，历史脏值（真实案例：
    25 场全写成 ...970，而 pms 里根本没有这个号）会让整张表的 K/D/ADR 全空，
    和概览（走 settings）自相矛盾。传 None 时退回库里的值，兼容旧调用。
    """
    rows = conn.execute(
        """SELECT d.*, m.map AS m_map, m.platform AS m_platform,
                  m.duration_s, m.played_at, m.my_steamid,
                  m.excluded, m.exclude_note,
                  (SELECT COUNT(*) FROM rounds r WHERE r.match_id=d.match_id) AS rounds,
                  (SELECT SUM(a_win) FROM rounds r WHERE r.match_id=d.match_id) AS wins,
                  -- 客观比分（阵营视角）：这场没有我时也要能显示出「谁赢了多少回合」
                  (SELECT SUM(winner='T') FROM rounds r WHERE r.match_id=d.match_id) AS t_wins,
                  (SELECT SUM(winner='CT') FROM rounds r WHERE r.match_id=d.match_id) AS ct_wins,
                  (SELECT first_side FROM players pl
                    WHERE pl.match_id=d.match_id
                      AND pl.steamid=COALESCE(:sid, m.my_steamid)) AS my_side,
                  (SELECT COUNT(*) FROM pms p2 WHERE p2.match_id=d.match_id
                      AND p2.steamid=COALESCE(:sid, m.my_steamid)) AS me_in,
                  p.kills AS me_kills, p.deaths AS me_deaths, p.assists AS me_assists,
                  p.adr AS me_adr, p.kast AS me_kast, p.rating AS me_rating,
                  p.hs AS me_hs, p.fk AS me_fk, p.impact AS me_impact,
                  p.fire_count AS me_fire, p.stop_shots AS me_stop,
                  p.tkills, p.t_deaths, p.ct_kills, p.ct_deaths,
                  p.t_dmg, p.ct_dmg, p.t_rounds, p.ct_rounds
           FROM demos d
           LEFT JOIN matches m ON m.id = d.match_id
           LEFT JOIN pms p ON p.match_id = d.match_id
                          AND p.steamid = COALESCE(:sid, m.my_steamid)
           ORDER BY COALESCE(d.mtime,'') DESC, d.name""",
        {"sid": my_steamid},
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["map"] = d.get("m_map") or d.get("map")
        d["platform"] = d.get("m_platform") or d.get("platform")
        # 分阵营 ADR（前端直接可用）
        if d.get("t_rounds") and d.get("t_dmg") is not None:
            d["t_adr"] = round(d["t_dmg"] / d["t_rounds"], 1)
        if d.get("ct_rounds") and d.get("ct_dmg") is not None:
            d["ct_adr"] = round(d["ct_dmg"] / d["ct_rounds"], 1)
        # pms 里的比率是原始浮点（如 61.47618865966797），API 出去前统一舍入
        for _k, _nd in (("me_adr", 1), ("me_kast", 1), ("me_rating", 2),
                        ("me_impact", 2), ("me_hs", 0)):
            if isinstance(d.get(_k), float):
                d[_k] = round(d[_k], _nd)
        out.append(d)
    return out


def mark_analyzed(conn: sqlite3.Connection, name: str, match_id: int,
                  map_name: str, platform: str, server: str) -> None:
    with conn:
        conn.execute("UPDATE demos SET analyzed=1, match_id=?, map=?, platform=?, server=?, error=NULL "
                     "WHERE name=?", (match_id, map_name, platform, server, name))


def mark_error(conn: sqlite3.Connection, name: str, err: str) -> None:
    with conn:
        conn.execute("UPDATE demos SET error=?, analyzed=0 WHERE name=?", (err[:300], name))


def insert_players(conn, match_id, rows):
    _insert_many(conn, "players", rows)


def _insert_many(conn: sqlite3.Connection, table: str, rows: Sequence[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0].keys())
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])


def insert_many(conn, table, rows):
    _insert_many(conn, table, rows)


def delete_match(conn: sqlite3.Connection, match_id: int) -> None:
    for t in MATCH_CHILD_TABLES:
        conn.execute(f"DELETE FROM {t} WHERE match_id = ?", (match_id,))
    conn.execute("UPDATE demos SET analyzed=0, match_id=NULL WHERE match_id=?", (match_id,))
    conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))


def q(conn, sql, params=()) -> list[sqlite3.Row]:
    return conn.execute(sql, tuple(params)).fetchall()
