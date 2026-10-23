"""能力画像 + 历史快照 + 趋势/退步预警。

设计要点：
- 每场一算，结果落 snapshots 表；缺的会自动补齐（ensure）。
- 趋势用「最近 N 场均值 vs 之前 N 场均值」，不是单场对比（单场波动太大）。
- 退步判定：相对下滑 >= warn_pct 且绝对变化超过阈值（避免小数抖动报警）。
"""
from __future__ import annotations

import sqlite3


# ---- 历史基线：样本不足时用这套兜底（只在头 3 场之前生效）----
FALLBACK = {
    "adr": 90.0, "dpr": 0.72, "impact": 1.20, "inv_rate": 45.0, "fk_wr": 65.0,
}
MIN_SAMPLE = 3          # 少于这么多场，基线不可信


def _clamp(v: float, lo=0.0, hi=100.0) -> float:
    return max(lo, min(hi, v))


def _baseline(conn: sqlite3.Connection, steamid: int) -> tuple[dict, int, bool]:
    """历史均值作为基线。返回 (基线, 样本数, 是否为真实基线)。"""
    rows = [dict(r) for r in conn.execute(
        "SELECT s.adr, s.dpr, s.impact, s.inv_rate, s.fk_wr FROM snapshots s "
        "JOIN matches m ON m.id=s.match_id "
        "WHERE s.steamid=? AND (m.excluded IS NULL OR m.excluded=0)",
        (steamid,))]
    if len(rows) < MIN_SAMPLE:
        return dict(FALLBACK), len(rows), False
    out = {}
    for k, fb in FALLBACK.items():
        vals = [r[k] for r in rows if r.get(k) is not None]
        out[k] = round(sum(vals) / len(vals), 3) if vals else fb
    return out, len(rows), True


def _dimensions(vals: dict, base: dict) -> dict:
    """以基线为 50 分做归一化：高于基线向上，低于基线向下，2 倍封顶。"""
    def sc(key, v, higher_better=True):
        b = base.get(key) or 1
        if v is None:
            return 50.0
        r = (v / b) if higher_better else (b / max(v, 0.01))
        return round(_clamp(50.0 * r), 1)

    return {
        "fire": sc("adr", vals.get("adr")),
        "survive": sc("dpr", vals.get("dpr"), higher_better=False),
        "impact": sc("impact", vals.get("impact")),
        "economy": sc("inv_rate", vals.get("inv_rate")),
        "opening": sc("fk_wr", vals.get("fk_wr")),
    }


def _first_kill_winrate(conn: sqlite3.Connection, match_id: int, steamid: int):
    """该场：我方拿到首杀的回合里赢了几成。"""
    mates = {}
    for r in conn.execute("SELECT steamid sid, first_side fs FROM players WHERE match_id=?",
                          (match_id,)):
        mates[r["sid"]] = r["fs"]
    my_fs = mates.get(steamid)
    a0 = conn.execute("SELECT a_side FROM rounds WHERE match_id=? ORDER BY round LIMIT 1",
                      (match_id,)).fetchone()
    a_side0 = a0["a_side"] if a0 else None
    rows = conn.execute(
        """SELECT k.attacker_steamid att, r.a_win, r.a_side
           FROM kills k
           JOIN (SELECT round, MIN(tick) mt FROM kills WHERE match_id=? GROUP BY round) f
             ON f.round = k.round AND f.mt = k.tick
           JOIN rounds r ON r.match_id = k.match_id AND r.round = k.round
           WHERE k.match_id = ?""", (match_id, match_id)).fetchall()
    n = w = 0
    for r in rows:
        att = r["att"]
        if not att:
            continue
        # 我方是否 A 队（用该场第一回合比对）
        is_a_side = (my_fs == a_side0) if (my_fs and a_side0) else True
        won = bool(r["a_win"]) if is_a_side else not bool(r["a_win"])
        # 首杀者是否我方
        if att == steamid or (my_fs and mates.get(att) == my_fs):
            n += 1
            w += 1 if won else 0
    return (round(w / n * 100) if n else None), n


def compute_snapshot(conn: sqlite3.Connection, match_id: int, steamid: int) -> dict | None:
    p = conn.execute("SELECT * FROM pms WHERE match_id=? AND steamid=?",
                     (match_id, steamid)).fetchone()
    if not p:
        return None
    m = conn.execute("SELECT map, played_at FROM matches WHERE id=?", (match_id,)).fetchone()
    fk_wr, _ = _first_kill_winrate(conn, match_id, steamid)

    # 装备保留率 = 回合初继承装备 ÷ 每回合装备价值
    # 语义：你每回合的装备里有多大比例是上一回合带过来、不用重新买的。
    # 不用 economy 表的 pre_bal/post_bal —— 那两个字段实际写的是
    # 「回合初装备价值」和「冻结时现金」（量纲不同），相减算不出支出，
    # 曾导致 inv_rate 算出 10276%，能力画像的「经济」维度被 clamp 成恒满分。
    eq_start = p["equip_round_start"] or 0
    eq_avg = p["equip_value"] or 0
    inv_rate = round(eq_start / eq_avg * 100, 1) if eq_avg else None

    return {
        "match_id": match_id, "steamid": steamid,
        "played_at": (m["played_at"] if m else "") or "",
        "map": (m["map"] if m else "") or "",
        "adr": p["adr"], "kast": p["kast"], "rating": p["rating"],
        "kd": round((p["kills"] or 0) / max(p["deaths"] or 1, 1), 2),
        "kpr": p["kpr"], "dpr": p["dpr"], "impact": p["impact"],
        "hs_pct": round((p["hs"] or 0) / max(p["kills"] or 1, 1) * 100, 1),
        "rounds": p["rounds"], "fk": p["fk"], "fd": p["fd"], "fk_wr": fk_wr,
        "spent_avg": round((p["spent"] or 0) / max(p["rounds"] or 1, 1)), "inv_rate": inv_rate,
    }


def ensure_snapshots(conn: sqlite3.Connection) -> int:
    """补齐缺失的快照，返回新增条数。"""
    added = 0
    for r in conn.execute(
        """SELECT x.match_id, x.steamid FROM pms x
           LEFT JOIN snapshots s ON s.match_id=x.match_id AND s.steamid=x.steamid
           WHERE s.match_id IS NULL"""):
        snap = compute_snapshot(conn, r["match_id"], r["steamid"])
        if not snap:
            continue
        cols = ",".join(snap.keys())
        ph = ",".join(["?"] * len(snap))
        with conn:
            conn.execute(f"INSERT OR REPLACE INTO snapshots ({cols}) VALUES ({ph})",
                         tuple(snap.values()))
        added += 1
    return added


def _avg(rows: list[dict], key: str):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


# ---- 指标定义：key -> (显示名, 单位, 方向, 报警阈值%, 绝对阈值) ----
METRICS = [
    ("adr", "ADR", "", 1, 6.0, 2.0),
    ("kast", "KAST", "%", 1, 5.0, 1.5),
    ("rating", "Rating", "", 1, 8.0, 0.08),
    ("kd", "K/D", "", 1, 8.0, 0.08),
    ("impact", "Impact", "", 1, 10.0, 0.10),
    ("hs_pct", "爆头率", "%", 1, 8.0, 2.0),
    ("fk_wr", "首杀转化", "%", 1, 8.0, 3.0),
    ("inv_rate", "装备保留率", "%", 1, 10.0, 3.0),
]


def trend(conn: sqlite3.Connection, steamid: int, window: int = 5) -> dict:
    """最近 window 场 vs 之前 window 场。"""
    rows = [dict(r) for r in conn.execute(
        "SELECT s.* FROM snapshots s JOIN matches m ON m.id=s.match_id "
        "WHERE s.steamid=? AND (m.excluded IS NULL OR m.excluded=0) "
        "ORDER BY s.played_at, s.match_id", (steamid,))]
    out = {"n": len(rows), "window": window, "items": [],
           "alerts": [], "radar_now": None, "radar_prev": None,
           "rows": rows}
    if not rows:
        return out

    recent = rows[-window:]
    prev = rows[-2 * window:-window] if len(rows) >= 2 * window else []

    base, base_n, base_real = _baseline(conn, steamid)
    now_vals = {k: _avg(recent, k) for k in FALLBACK}
    prev_vals = {k: _avg(prev, k) for k in FALLBACK} if prev else {}
    radar_now = _dimensions(now_vals, base)
    radar_prev = _dimensions(prev_vals, base) if prev else None
    out["radar_now"] = radar_now
    out["radar_prev"] = radar_prev
    out["baseline"] = base
    out["baseline_real"] = base_real
    out["baseline_n"] = base_n
    out["now_raw"] = now_vals

    if not prev:
        out["items"] = [{"key": k, "label": lb, "unit": u,
                         "now": _avg(recent, k), "prev": None,
                         "delta": None, "pct": None, "state": "n/a"}
                        for k, lb, u, *_ in METRICS]
        out["note"] = f"需要至少 {2 * window} 场才能判断趋势（当前 {len(rows)} 场）"
        return out

    for key, label, unit, direction, warn_pct, warn_abs in METRICS:
        now = _avg(recent, key)
        was = _avg(prev, key)
        if now is None or was is None:
            out["items"].append({"key": key, "label": label, "unit": unit,
                                 "now": now, "prev": was, "delta": None,
                                 "pct": None, "state": "n/a"})
            continue
        delta = round(now - was, 2)
        pct = round(delta / abs(was) * 100, 1) if was else None
        # 方向：1 = 越高越好
        bad = (delta < 0) if direction == 1 else (delta > 0)
        state = "flat"
        if bad and pct is not None and abs(pct) >= warn_pct and abs(delta) >= warn_abs:
            state = "down"
        elif (not bad) and pct is not None and abs(pct) >= warn_pct and abs(delta) >= warn_abs:
            state = "up"
        out["items"].append({"key": key, "label": label, "unit": unit,
                             "now": now, "prev": was, "delta": delta,
                             "pct": pct, "state": state})
        if state == "down":
            out["alerts"].append(f"{label} 从 {was}{unit} 掉到 {now}{unit}"
                                 f"（{pct:+.1f}%）")
    return out
